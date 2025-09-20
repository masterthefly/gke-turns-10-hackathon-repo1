#!/bin/bash
# Deploy script for the GKE hackathon project
# TODO: clean this up later, but it works for now

# Default values
PROJECT_ID=""
GEMINI_API_KEY=""
SKIP_INFRASTRUCTURE=false
FORCE_REDEPLOY=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -p|--project-id)
      PROJECT_ID="$2"
      shift 2
      ;;
    -g|--gemini-api-key)
      GEMINI_API_KEY="$2"
      shift 2
      ;;
    -s|--skip-infrastructure)
      SKIP_INFRASTRUCTURE=true
      shift
      ;;
    -f|--force-redeploy)
      FORCE_REDEPLOY=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  -p, --project-id PROJECT_ID      GCP Project ID"
      echo "  -g, --gemini-api-key API_KEY     Gemini API Key"
      echo "  -s, --skip-infrastructure        Skip infrastructure deployment"
      echo "  -f, --force-redeploy             Force redeploy of existing services"
      echo "  -h, --help                       Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option $1"
      exit 1
      ;;
  esac
done

# Figure out project - this is kinda messy but whatever
if [[ -z "$PROJECT_ID" ]]; then
    PROJECT_ID="$PROJECT_ID"
fi

if [[ -z "$PROJECT_ID" ]]; then
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null | tr -d '\n')
fi

if [[ -z "$PROJECT_ID" ]]; then
    echo "ERROR: No project ID found. Run setup.sh or use -p/--project-id"
    exit 1
fi

# Set up vars
export PROJECT_ID="$PROJECT_ID"
REGION="us-central1"
ZONE="us-central1-a"
REPO="gke-turns-10-repo"

echo "=== Deploying to GKE ==="
echo "Project: $PROJECT_ID"
echo "Using GKE Autopilot (machine types managed automatically)"

gcloud config set project "$PROJECT_ID"

# Infrastructure stuff
if [[ "$SKIP_INFRASTRUCTURE" != true ]]; then
    echo "Building infrastructure with terraform..."
    
    if [[ ! -d "terraform-gke" ]]; then
        echo "No terraform-gke directory found!"
        exit 1
    fi
    
    cd terraform-gke
    
    # Write terraform vars
    cat > terraform.tfvars <<EOF
project_id   = "$PROJECT_ID"
region       = "$REGION"
zone         = "$ZONE"
EOF
    
    # Init if needed
    if [[ ! -d ".terraform" ]]; then
        terraform init
    fi
    
    terraform plan -out=tfplan
    if [[ $? -ne 0 ]]; then exit 1; fi
    
    echo "Applying terraform (this takes forever)..."
    terraform apply tfplan
    if [[ $? -ne 0 ]]; then exit 1; fi
    
    cd ..
fi

# Connect to cluster
echo "Getting cluster credentials..."
gcloud container clusters get-credentials gke-turns-10-hackathon --region="$REGION" --project="$PROJECT_ID"

# Wait for nodes - sometimes they're slow
echo "Checking if nodes are up..."
for ((i=0; i<10; i++)); do
    nodes=$(kubectl get nodes --no-headers 2>/dev/null)
    if [[ -n "$nodes" ]]; then
        echo "Nodes are ready"
        break
    fi
    echo "Still waiting for nodes... ($((i+1))/10)"
    sleep 30
done

# Make sure docker repo exists
echo "Setting up docker registry..."
gcloud artifacts repositories create "$REPO" --repository-format=docker --location="$REGION" 2>/dev/null
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

# Boutique demo - optional
read -p "Deploy boutique demo? [Y/n] " -n 1 -r do_boutique
echo
if [[ ! "$do_boutique" =~ ^[Nn]$ ]]; then
    if [[ -f "microservices-demo/release/kubernetes-manifests.yaml" ]]; then
        kubectl apply -f microservices-demo/release/kubernetes-manifests.yaml
        echo "Boutique deployed"
    fi
fi

# Now the real apps
echo "Deploying our apps..."

# Build and deploy function - probably could be cleaner but works
build_and_deploy() {
    local app="$1"
    local port="$2"
    local service_type="${3:-ClusterIP}"
    
    echo "--- Building $app ---"
    
    if [[ ! -d "$app" ]]; then
        echo "$app directory not found, skipping"
        return
    fi
    
    if [[ ! -f "$app/Dockerfile" ]]; then
        echo "No Dockerfile in $app, skipping"
        return
    fi
    
    local old_location=$(pwd)
    cd "$app"
    
    # Use timestamp for unique tags so k8s pulls new images
    local timestamp=$(date +"%Y%m%d-%H%M%S")
    local image_name="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/${app}:$timestamp"
    
    # Build
    echo "Building docker image with tag $timestamp..."
    docker build -t "$image_name" .
    if [[ $? -ne 0 ]]; then
        echo "Build failed for $app"
        cd "$old_location"
        return
    fi
    
    # Push
    echo "Pushing to registry..."
    docker push "$image_name"
    if [[ $? -ne 0 ]]; then
        echo "Push failed for $app"
        cd "$old_location"
        return
    fi
    
    # Clean up old images to save space
    echo "Cleaning up old images for $app..."
    
    # Remove old local images for this app (keep only the latest one we just built)
    local old_local_images=$(docker images "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/${app}" --format "table {{.Repository}}:{{.Tag}}" | tail -n +2)
    if [[ -n "$old_local_images" ]]; then
        while IFS= read -r image; do
            if [[ -n "$image" && "$image" != "$image_name" ]]; then
                echo "Removing old local image: $image"
                docker rmi "$image" 2>/dev/null
            fi
        done <<< "$old_local_images"
    fi
    
    # Clean up old images in the repository (keep only the 3 most recent)
    {
        local repo_images=$(gcloud artifacts docker images list "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$app" --format="value(image)" --sort-by="~CREATE_TIME" 2>/dev/null)
        if [[ -n "$repo_images" ]]; then
            local image_count=$(echo "$repo_images" | wc -l)
            if [[ $image_count -gt 3 ]]; then
                local images_to_delete=$(echo "$repo_images" | tail -n +4)
                while IFS= read -r image_to_delete; do
                    if [[ -n "$image_to_delete" ]]; then
                        echo "Removing old repository image: $image_to_delete"
                        gcloud artifacts docker images delete "$image_to_delete" --quiet 2>/dev/null
                    fi
                done <<< "$images_to_delete"
            fi
        fi
    } || {
        echo "Note: Could not clean repository images (may not have permission)"
    }
    
    cd "$old_location"
    
    # Check if deployment exists
    local existing_deploy=$(kubectl get deployment "$app" 2>/dev/null)
    if [[ -n "$existing_deploy" && "$FORCE_REDEPLOY" == true ]]; then
        echo "Force redeploy - deleting existing deployment..."
        kubectl delete deployment "$app"
        kubectl delete service "$app-service" 2>/dev/null
        sleep 5
    fi
    
    # Deploy to k8s
    echo "Deploying to kubernetes..."
    
    local yaml=$(cat <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: $app
  template:
    metadata:
      labels:
        app: $app
    spec:
      containers:
      - name: $app
        image: $image_name
        imagePullPolicy: Always
        ports:
        - containerPort: $port
        env:
        - name: PORT
          value: "$port"
        - name: GEMINI_API_KEY
          valueFrom:
            secretKeyRef:
              name: gemini-api-key
              key: api-key
        resources:
          requests:
            memory: "256Mi"
            cpu: "200m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        volumeMounts:
        - name: gemini-secret-volume
          mountPath: /etc/secrets
          readOnly: true
      volumes:
      - name: gemini-secret-volume
        secret:
          secretName: gemini-api-key
---
apiVersion: v1
kind: Service
metadata:
  name: $app-service
spec:
  selector:
    app: $app
  ports:
  - port: $port
    targetPort: $port
  type: $service_type
EOF
)
    
    echo "$yaml" | kubectl apply -f -
    
    if [[ $? -eq 0 ]]; then
        echo "$app deployed successfully"
        
        # Wait for rollout to complete
        echo "Waiting for $app rollout..."
        kubectl rollout status deployment/"$app" --timeout=300s
        
    else
        echo "Deployment failed for $app"
    fi
}

# Deploy the apps
build_and_deploy "mcp-server" 8080
build_and_deploy "adk-agents" 8000
build_and_deploy "streamlit-ui" 8501 "LoadBalancer"

# Gemini key if provided
if [[ -n "$GEMINI_API_KEY" ]]; then
    kubectl create secret generic gemini-api-key --from-literal=api-key="$GEMINI_API_KEY" --dry-run=client -o yaml | kubectl apply -f -
    echo "Gemini API key set"
fi

# Give things a moment to start
sleep 20

echo ""
echo "=== DEPLOYMENT DONE ==="

# Show what we got
kubectl get pods
kubectl get services

echo ""
echo "Check logs with:"
echo "kubectl logs -l app=mcp-server"
echo "kubectl logs -l app=adk-agents" 
echo "kubectl logs -l app=streamlit-ui"
echo ""
echo "Port forward to access:"
echo "kubectl port-forward service/streamlit-ui-service 8501:8501"

# Check for external IPs
lb_svcs=$(kubectl get svc -o jsonpath='{.items[?(@.spec.type=="LoadBalancer")].metadata.name}' 2>/dev/null)
if [[ -n "$lb_svcs" ]]; then
    echo ""
    echo "LoadBalancer services (external IP may take a few minutes):"
    kubectl get svc -l 'app in (streamlit-ui)'
fi
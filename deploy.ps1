# Deploy script for the GKE hackathon project
# TODO: clean this up later, but it works for now

param(
    [string]$ProjectId = "",
    [string]$GeminiApiKey = "",
    [switch]$SkipInfrastructure = $false,
    [switch]$ForceRedeploy = $false
)

# figure out project - this is kinda messy but whatever
if (!$ProjectId) {
    $ProjectId = $env:PROJECT_ID
}

if (!$ProjectId) {
    $ProjectId = (gcloud config get-value project).Trim()
}

if (!$ProjectId) {
    Write-Host "ERROR: No project ID found. Run setup.ps1 or use -ProjectId"
    exit 1
}

# set up vars
$env:PROJECT_ID = $ProjectId
$REGION = "us-central1"
$ZONE = "us-central1-a" 
$REPO = "gke-turns-10-repo"

Write-Host "=== Deploying to GKE ==="
Write-Host "Project: $env:PROJECT_ID"
Write-Host "Using GKE Autopilot (machine types managed automatically)"

gcloud config set project $env:PROJECT_ID

# infrastructure stuff
if (!$SkipInfrastructure) {
    Write-Host "Building infrastructure with terraform..."
    
    if (!(Test-Path "terraform-gke")) {
        Write-Host "No terraform-gke directory found!"
        exit 1
    }
    
    cd terraform-gke
    
    # write terraform vars
    @"
project_id   = "$env:PROJECT_ID"
region       = "$REGION"
zone         = "$ZONE"
"@ | Out-File terraform.tfvars -Encoding utf8
    
    # init if needed
    if (!(Test-Path ".terraform")) {
        terraform init
    }
    
    terraform plan -out=tfplan
    if ($LASTEXITCODE -ne 0) { exit 1 }
    
    Write-Host "Applying terraform (this takes forever)..."
    terraform apply tfplan
    if ($LASTEXITCODE -ne 0) { exit 1 }
    
    cd ..
}

# connect to cluster
Write-Host "Getting cluster credentials..."
gcloud container clusters get-credentials gke-turns-10-hackathon --region=$REGION --project=$env:PROJECT_ID

# wait for nodes - sometimes they're slow
Write-Host "Checking if nodes are up..."
for ($i = 0; $i -lt 10; $i++) {
    $nodes = kubectl get nodes --no-headers 2>$null
    if ($nodes) {
        Write-Host "Nodes are ready"
        break
    }
    Write-Host "Still waiting for nodes... ($($i+1)/10)"
    Start-Sleep 30
}

# make sure docker repo exists
Write-Host "Setting up docker registry..."
gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION 2>$null
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

# boutique demo - optional
$doBoutique = Read-Host "Deploy boutique demo? [Y/n]"
if ($doBoutique -ne "n") {
    if (Test-Path "microservices-demo/release/kubernetes-manifests.yaml") {
        kubectl apply -f microservices-demo/release/kubernetes-manifests.yaml
        Write-Host "Boutique deployed"
    }
}

# now the real apps
Write-Host "Deploying our apps..."

# build and deploy function - probably could be cleaner but works
function BuildAndDeploy($app, $port, $serviceType = "ClusterIP") {
    Write-Host "--- Building $app ---"
    
    if (!(Test-Path $app)) {
        Write-Host "$app directory not found, skipping"
        return
    }
    
    if (!(Test-Path "$app/Dockerfile")) {
        Write-Host "No Dockerfile in $app, skipping"
        return
    }
    
    $oldLocation = Get-Location
    cd $app
    
    # use timestamp for unique tags so k8s pulls new images
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $imageName = "$REGION-docker.pkg.dev/$env:PROJECT_ID/$REPO/${app}:$timestamp"
    
    # build
    Write-Host "Building docker image with tag $timestamp..."
    docker build -t $imageName .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Build failed for $app"
        cd $oldLocation
        return
    }
    
    # push
    Write-Host "Pushing to registry..."
    docker push $imageName
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Push failed for $app"
        cd $oldLocation
        return
    }
    
    # clean up old images to save space
    Write-Host "Cleaning up old images for $app..."
    
    # remove old local images for this app (keep only the latest one we just built)
    $oldLocalImages = docker images "$REGION-docker.pkg.dev/$env:PROJECT_ID/$REPO/${app}" --format "table {{.Repository}}:{{.Tag}}" | Select-Object -Skip 1
    foreach ($image in $oldLocalImages) {
        if ($image -and $image -ne $imageName) {
            Write-Host "Removing old local image: $image"
            docker rmi $image 2>$null
        }
    }
    
    # clean up old images in the repository (keep only the 3 most recent)
    try {
        $repoImages = gcloud artifacts docker images list "$REGION-docker.pkg.dev/$env:PROJECT_ID/$REPO/$app" --format="value(image)" --sort-by="~CREATE_TIME" 2>$null
        if ($repoImages -and $repoImages.Count -gt 3) {
            $imagesToDelete = $repoImages | Select-Object -Skip 3
            foreach ($imageToDelete in $imagesToDelete) {
                Write-Host "Removing old repository image: $imageToDelete"
                gcloud artifacts docker images delete $imageToDelete --quiet 2>$null
            }
        }
    } catch {
        Write-Host "Note: Could not clean repository images (may not have permission)"
    }
    
    cd $oldLocation
    
    # check if deployment exists
    $existingDeploy = kubectl get deployment $app 2>$null
    if ($existingDeploy -and $ForceRedeploy) {
        Write-Host "Force redeploy - deleting existing deployment..."
        kubectl delete deployment $app
        kubectl delete service $app-service 2>$null
        Start-Sleep 5
    }
    
    # deploy to k8s
    Write-Host "Deploying to kubernetes..."
    
    $yaml = @"
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
        image: $imageName
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
  type: $serviceType
"@
    
    $yaml | kubectl apply -f -
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "$app deployed successfully"
        
        # wait for rollout to complete
        Write-Host "Waiting for $app rollout..."
        kubectl rollout status deployment/$app --timeout=300s
        
    } else {
        Write-Host "Deployment failed for $app"
    }
}

# deploy the apps
BuildAndDeploy "mcp-server" 8080
BuildAndDeploy "adk-agents" 8000
BuildAndDeploy "streamlit-ui" 8501 "LoadBalancer"

# gemini key if provided
if ($GeminiApiKey) {
    kubectl create secret generic gemini-api-key --from-literal=api-key=$GeminiApiKey --dry-run=client -o yaml | kubectl apply -f -
    Write-Host "Gemini API key set"
}

# give things a moment to start
Start-Sleep 20

Write-Host ""
Write-Host "=== DEPLOYMENT DONE ==="

# show what we got
kubectl get pods
kubectl get services

Write-Host ""
Write-Host "Check logs with:"
Write-Host "kubectl logs -l app=mcp-server"
Write-Host "kubectl logs -l app=adk-agents" 
Write-Host "kubectl logs -l app=streamlit-ui"
Write-Host ""
Write-Host "Port forward to access:"
Write-Host "kubectl port-forward service/streamlit-ui-service 8501:8501"

# check for external IPs
$lbSvcs = kubectl get svc -o jsonpath='{.items[?(@.spec.type=="LoadBalancer")].metadata.name}' 2>$null
if ($lbSvcs) {
    Write-Host ""
    Write-Host "LoadBalancer services (external IP may take a few minutes):"
    kubectl get svc -l 'app in (streamlit-ui)'
}
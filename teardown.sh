#!/bin/bash

# Default values
PROJECT_ID=""
DELETE_PROJECT=false
FORCE=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -p|--project-id)
      PROJECT_ID="$2"
      shift 2
      ;;
    -d|--delete-project)
      DELETE_PROJECT=true
      shift
      ;;
    -f|--force)
      FORCE=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  -p, --project-id PROJECT_ID     GCP Project ID"
      echo "  -d, --delete-project            Delete the entire project (irreversible)"
      echo "  -f, --force                     Skip confirmation prompts"
      echo "  -h, --help                      Show this help message"
      echo ""
      echo "Examples:"
      echo "  $0 -p my-project                # Destroy infrastructure, keep project"
      echo "  $0 -p my-project -d             # Destroy everything including project"
      echo "  $0 -p my-project -d -f          # Force destroy everything without prompts"
      exit 0
      ;;
    *)
      echo "Unknown option $1"
      exit 1
      ;;
  esac
done

# Get project ID
if [[ -z "$PROJECT_ID" ]]; then
    PROJECT_ID="$PROJECT_ID"
    if [[ -z "$PROJECT_ID" ]]; then
        PROJECT_ID=$(gcloud config get-value project 2>/dev/null | tr -d '\n')
    fi
fi

if [[ -z "$PROJECT_ID" ]]; then
    echo "No project ID found. Please provide -p/--project-id parameter"
    exit 1
fi

export PROJECT_ID="$PROJECT_ID"
export REGION="us-central1"
export ZONE="us-central1-a"

echo "========================================="
echo "GKE TURNS 10 HACKATHON TEARDOWN"
echo "========================================="
echo "Project: $PROJECT_ID"
echo ""

if [[ "$FORCE" != true ]]; then
    echo -e "${YELLOW}This will destroy all resources in the project!${NC}"
    echo ""
    
    if [[ "$DELETE_PROJECT" == true ]]; then
        echo -e "${RED}The entire project will be PERMANENTLY DELETED!${NC}"
        echo -e "${RED}This action is IRREVERSIBLE!${NC}"
    fi
    
    echo ""
    read -p "Type 'DESTROY' to confirm destruction: " confirm
    if [[ "$confirm" != "DESTROY" ]]; then
        echo "Teardown cancelled"
        exit 0
    fi
fi

gcloud config set project "$PROJECT_ID"

# Step 1: Clean up Kubernetes resources
echo "=== CLEANING KUBERNETES RESOURCES ==="
{
    gcloud container clusters get-credentials gke-turns-10-hackathon --zone="$ZONE" --project="$PROJECT_ID" 2>/dev/null
    
    echo "Deleting all custom deployments and services..."
    kubectl delete --all deployments,services,pods --timeout=60s 2>/dev/null
    
    # Clean up Online Boutique if it exists
    if [[ -f "microservices-demo/release/kubernetes-manifests.yaml" ]]; then
        echo "Cleaning up Online Boutique..."
        kubectl delete -f microservices-demo/release/kubernetes-manifests.yaml --ignore-not-found=true 2>/dev/null
    fi
    
    echo "✓ Kubernetes resources cleaned"
} || {
    echo "⚠ Could not clean Kubernetes resources (cluster may not exist)"
}

# Step 2: Destroy Terraform infrastructure
echo ""
echo "=== DESTROYING INFRASTRUCTURE ==="
if [[ -d "terraform-gke" ]]; then
    cd terraform-gke
    
    if [[ -f "terraform.tfstate" ]]; then
        echo "Destroying Terraform infrastructure..."
        terraform destroy -auto-approve
        
        if [[ $? -eq 0 ]]; then
            echo "✓ Terraform infrastructure destroyed"
        else
            echo -e "${YELLOW}⚠ Some Terraform resources may not have been destroyed${NC}"
        fi
    else
        echo "No Terraform state found, skipping..."
    fi
    
    cd ..
else
    echo "No terraform-gke directory found, skipping..."
fi

# Step 3: Clean up any remaining GCP resources
echo ""
echo "=== CLEANING REMAINING GCP RESOURCES ==="

# Delete any remaining compute instances
echo "Checking for remaining compute instances..."
instances=$(gcloud compute instances list --project="$PROJECT_ID" --format="value(name,zone)" 2>/dev/null)
if [[ -n "$instances" ]]; then
    while IFS=$'\t' read -r name zone; do
        if [[ -n "$name" && -n "$zone" ]]; then
            echo "Deleting instance: $name in $zone"
            gcloud compute instances delete "$name" --zone="$zone" --project="$PROJECT_ID" --quiet
        fi
    done <<< "$instances"
fi

# Delete container images from Artifact Registry
echo "Cleaning up container images..."
repos=$(gcloud artifacts repositories list --location="$REGION" --project="$PROJECT_ID" --format="value(name)" 2>/dev/null)
while read -r repo; do
    if [[ "$repo" == *"gke-turns-10-repo"* ]]; then
        echo "Deleting repository: $repo"
        gcloud artifacts repositories delete "$repo" --location="$REGION" --project="$PROJECT_ID" --quiet
    fi
done <<< "$repos"

# Delete any remaining disks
echo "Checking for remaining persistent disks..."
disks=$(gcloud compute disks list --project="$PROJECT_ID" --format="value(name,zone)" 2>/dev/null)
if [[ -n "$disks" ]]; then
    while IFS=$'\t' read -r name zone; do
        if [[ -n "$name" && -n "$zone" ]]; then
            echo "Deleting disk: $name in $zone"
            gcloud compute disks delete "$name" --zone="$zone" --project="$PROJECT_ID" --quiet
        fi
    done <<< "$disks"
fi

# Step 4: Optionally delete the entire project
if [[ "$DELETE_PROJECT" == true ]]; then
    echo ""
    echo "=== DELETING PROJECT ==="
    
    if [[ "$FORCE" != true ]]; then
        echo ""
        echo -e "${RED}FINAL CONFIRMATION REQUIRED!${NC}"
        echo -e "${RED}This will PERMANENTLY DELETE the entire project: $PROJECT_ID${NC}"
        echo -e "${RED}ALL DATA, CONFIGURATIONS, AND HISTORY WILL BE LOST!${NC}"
        echo ""
        
        read -p "Type the project name '$PROJECT_ID' to confirm deletion: " final_confirm
        if [[ "$final_confirm" != "$PROJECT_ID" ]]; then
            echo "Project name doesn't match. Project deletion cancelled."
            echo "Infrastructure has been destroyed but project preserved."
            exit 0
        fi
    fi
    
    echo "Deleting project completely..."
    gcloud projects delete "$PROJECT_ID" --quiet
    
    if [[ $? -eq 0 ]]; then
        echo "✓ Project deleted successfully"
    else
        echo -e "${YELLOW}⚠ Project deletion may have failed${NC}"
    fi
else
    echo ""
    echo "Project preserved. Infrastructure destroyed."
    echo "To delete the project completely, run:"
    echo "  ./teardown.sh -p '$PROJECT_ID' -d"
fi

echo ""
echo "========================================="
echo "TEARDOWN COMPLETED"
echo "========================================="
echo "💰 Billing Impact: Resources destroyed"

if [[ "$DELETE_PROJECT" != true ]]; then
    echo ""
    echo "The project still exists with:"
    echo "  • APIs enabled (no cost)"
    echo "  • IAM policies (no cost)"
    echo "  • Project billing link (no cost)"
    echo ""
    echo "You can reuse this project by running:"
    echo "  ./deploy.sh -p '$PROJECT_ID'"
fi
#!/bin/bash
# Project setup script for GKE hackathon
# I got tired of doing this manually every time, so here's a script that does it all

# Default values
PROJECT_ID=""
BILLING_ACCOUNT_ID=""
GEMINI_API_KEY=""
REGION="us-central1"
ZONE="us-central1-a"

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
    -b|--billing-account-id)
      BILLING_ACCOUNT_ID="$2"
      shift 2
      ;;
    -g|--gemini-api-key)
      GEMINI_API_KEY="$2"
      shift 2
      ;;
    -r|--region)
      REGION="$2"
      shift 2
      ;;
    -z|--zone)
      ZONE="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  -p, --project-id PROJECT_ID          GCP Project ID"
      echo "  -b, --billing-account-id BILLING_ID  GCP Billing Account ID"
      echo "  -g, --gemini-api-key API_KEY         Gemini API Key"
      echo "  -r, --region REGION                  GCP Region (default: us-central1)"
      echo "  -z, --zone ZONE                      GCP Zone (default: us-central1-a)"
      echo "  -h, --help                           Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option $1"
      exit 1
      ;;
  esac
done

check_tools() {
    echo "Making sure we have the right tools installed..."
    local tools_valid=true
    
    # Check for gcloud
    if command -v gcloud &> /dev/null; then
        local gcloud_check=$(gcloud version --format="text" 2>/dev/null | grep "Google Cloud SDK")
        if [[ -n "$gcloud_check" ]]; then
            echo -e "${GREEN}✓ Found Google Cloud SDK${NC}"
        else
            echo -e "${RED}✗ You need to install the Google Cloud SDK first${NC}"
            echo "Get it here: https://cloud.google.com/sdk/docs/install"
            tools_valid=false
        fi
    else
        echo -e "${RED}✗ You need to install the Google Cloud SDK first${NC}"
        echo "Get it here: https://cloud.google.com/sdk/docs/install"
        tools_valid=false
    fi
    
    # Check for kubectl  
    if command -v kubectl &> /dev/null; then
        if kubectl version --client &> /dev/null; then
            echo -e "${GREEN}✓ Found kubectl${NC}"
        else
            echo -e "${RED}✗ You need kubectl installed too${NC}"
            tools_valid=false
        fi
    else
        echo -e "${RED}✗ You need kubectl installed too${NC}"
        tools_valid=false
    fi
    
    # Check for terraform
    if command -v terraform &> /dev/null; then
        if terraform version &> /dev/null; then
            echo -e "${GREEN}✓ Found Terraform${NC}"
        else
            echo -e "${YELLOW}⚠️ Terraform not found - will skip terraform operations${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️ Terraform not found - will skip terraform operations${NC}"
    fi
    
    # Check if Docker is running
    if command -v docker &> /dev/null; then
        if docker ps &> /dev/null; then
            echo -e "${GREEN}✓ Docker is running${NC}"
        else
            echo -e "${RED}✗ Docker is not running or not installed${NC}"
            echo -e "${RED}Please start Docker daemon and try again${NC}"
            echo -e "${GRAY}Try: sudo systemctl start docker${NC}"
            tools_valid=false
        fi
    else
        echo -e "${RED}✗ Docker is not running or not installed${NC}"
        echo -e "${RED}Please start Docker daemon and try again${NC}"
        echo -e "${GRAY}Try: sudo systemctl start docker${NC}"
        tools_valid=false
    fi
    
    # Check if Kubernetes is available (kubectl context)
    if kubectl cluster-info --request-timeout=5s &> /dev/null; then
        echo -e "${GREEN}✓ Kubernetes cluster is accessible${NC}"
    else
        echo -e "${YELLOW}⚠️ Kubernetes cluster not accessible${NC}"
        echo -e "${YELLOW}This is normal if you haven't set up a cluster yet${NC}"
        echo -e "${YELLOW}Make sure you have access to a Kubernetes cluster (minikube, k3s, etc.)${NC}"
    fi
    
    # Exit if any required tools are missing
    if [[ "$tools_valid" != true ]]; then
        echo ""
        echo -e "${RED}❌ Required tools are missing. Please install them and try again.${NC}"
        exit 1
    fi
}

clean_terraform_directory() {
    local terraform_dir="$1"
    
    if [[ -d "$terraform_dir" ]]; then
        echo -e "${YELLOW}🧹 Cleaning up previous Terraform state in $terraform_dir...${NC}"
        
        {
            # Remove terraform state files
            local state_files=("terraform.tfstate" "terraform.tfstate.backup" ".terraform.lock.hcl")
            for file in "${state_files[@]}"; do
                local full_path="$terraform_dir/$file"
                if [[ -f "$full_path" ]]; then
                    rm -f "$full_path"
                    echo -e "${GRAY}  ✓ Removed $file${NC}"
                fi
            done
            
            # Remove .terraform directory
            local terraform_sub_dir="$terraform_dir/.terraform"
            if [[ -d "$terraform_sub_dir" ]]; then
                rm -rf "$terraform_sub_dir"
                echo -e "${GRAY}  ✓ Removed .terraform directory${NC}"
            fi
            
            # Remove plan files
            find "$terraform_dir" -name "*.tfplan" -type f -delete 2>/dev/null
            
            # Remove tfplan file specifically
            local tfplan_path="$terraform_dir/tfplan"
            if [[ -f "$tfplan_path" ]]; then
                rm -f "$tfplan_path"
                echo -e "${GRAY}  ✓ Removed tfplan${NC}"
            fi
            
            echo -e "${GREEN}  ✅ Terraform directory cleaned${NC}"
        } || {
            echo -e "${YELLOW}  ⚠️ Error cleaning terraform directory${NC}"
        }
    fi
}

setup_project_specific_terraform() {
    local project_id="$1"
    local region="$2"
    local zone="$3"
    
    local terraform_dir="terraform-gke-$project_id"
    local template_dir="terraform-gke"
    
    echo -e "${CYAN}📁 Setting up project-specific Terraform directory: $terraform_dir${NC}"
    
    {
        # Create project-specific directory
        if [[ ! -d "$terraform_dir" ]]; then
            mkdir -p "$terraform_dir"
            echo -e "${GREEN}  ✓ Created directory $terraform_dir${NC}"
        fi
        
        # Copy terraform files from template if they exist
        if [[ -d "$template_dir" ]]; then
            find "$template_dir" -name "*.tf" -exec cp {} "$terraform_dir/" \; 2>/dev/null
            echo -e "${GRAY}  ✓ Copied .tf files${NC}"
            
            # Copy outputs.tf if it exists
            if [[ -f "$template_dir/outputs.tf" ]]; then
                cp "$template_dir/outputs.tf" "$terraform_dir/"
                echo -e "${GRAY}  ✓ Copied outputs.tf${NC}"
            fi
        fi
        
        # Create/update terraform.tfvars with project-specific values
        local tfvars_path="$terraform_dir/terraform.tfvars"
        cat > "$tfvars_path" <<EOF
# Project Configuration - Generated by setup.sh
project_id = "$project_id"
region     = "$region"
zone       = "$zone"
cluster_name = "gke-turns-10-hackathon"
# AutoPilot clusters don't use manual node pools
node_count = 1
machine_type = "e2-standard-2"
disk_size_gb = 20

# Repository Configuration
repo_name = "gke-turns-10-repo"
EOF
        
        echo -e "${GREEN}  ✓ Created terraform.tfvars with project settings${NC}"
        echo "$terraform_dir"
    } || {
        echo -e "${RED}  ✗ Error setting up terraform directory${NC}"
        echo "$template_dir"  # Fallback to original directory
    }
}

# Make up a project ID if they didn't give us one
if [[ -z "$PROJECT_ID" ]]; then
    today=$(date +"%m%d")
    random_num=$(shuf -i 1000-9999 -n 1)
    PROJECT_ID="gke-hackathon-$today-$random_num"
fi

export PROJECT_ID="$PROJECT_ID"
export REGION="$REGION"
export ZONE="$ZONE"
export REPO_NAME="gke-turns-10-repo"

echo ""
echo "Setting up GKE environment..."  
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Zone: $ZONE"
echo ""

# Make sure they're logged into gcloud
current_user=$(gcloud config get-value account 2>/dev/null)
if [[ -z "$current_user" ]]; then
    echo "You need to login to Google Cloud first"
    gcloud auth login
fi

check_tools

# Check if project already exists and handle cleanup
echo "🔍 Checking project status..."
project_check=$(gcloud projects describe "$PROJECT_ID" 2>/dev/null)
project_exists=$?

if [[ $project_exists -eq 0 ]]; then
    echo -e "${YELLOW}⚠️  Project '$PROJECT_ID' already exists!${NC}"
    echo ""
    echo "This project may have existing resources that could:"
    echo "• Conflict with new deployments"
    echo "• Continue charging costs"
    echo "• Have inconsistent configurations"
    echo ""
    
    read -p "Do you want to clean up existing project resources? (yes/no/cancel): " cleanup_choice
    
    case "${cleanup_choice,,}" in
        "yes")
            echo -e "${YELLOW}🧹 Starting cleanup of existing project resources...${NC}"
            
            # Clean up GKE clusters
            echo "Checking for existing GKE clusters..."
            clusters=$(gcloud container clusters list --project="$PROJECT_ID" --format="value(name,zone)" 2>/dev/null)
            if [[ -n "$clusters" ]]; then
                echo "Found existing clusters. Deleting them..."
                while IFS=$'\t' read -r cluster_name cluster_zone; do
                    if [[ -n "$cluster_name" && -n "$cluster_zone" ]]; then
                        echo "  Deleting cluster: $cluster_name in $cluster_zone"
                        gcloud container clusters delete "$cluster_name" --zone="$cluster_zone" --project="$PROJECT_ID" --quiet
                    fi
                done <<< "$clusters"
            fi
            
            # Clean up Artifact Registry repositories
            echo "Checking for Artifact Registry repositories..."
            repos=$(gcloud artifacts repositories list --project="$PROJECT_ID" --format="value(name)" 2>/dev/null)
            if [[ -n "$repos" ]]; then
                echo "Found existing repositories. Deleting them..."
                while read -r repo; do
                    if [[ -n "$repo" ]]; then
                        echo "  Deleting repository: $repo"
                        gcloud artifacts repositories delete "$repo" --project="$PROJECT_ID" --quiet
                    fi
                done <<< "$repos"
            fi
            
            echo -e "${GREEN}✅ Project cleanup completed${NC}"
            ;;
        "no")
            echo -e "${YELLOW}⚠️  Continuing with existing project (resources may conflict)${NC}"
            ;;
        "cancel")
            echo -e "${RED}❌ Setup cancelled by user${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}❌ Invalid choice. Setup cancelled.${NC}"
            exit 1
            ;;
    esac
else
    echo -e "${CYAN}📝 Creating new project: $PROJECT_ID${NC}"
    gcloud projects create "$PROJECT_ID" --quiet
    if [[ $? -ne 0 ]]; then
        echo -e "${RED}✗ Failed to create project. It may already exist or you may lack permissions.${NC}"
        exit 1
    fi
    sleep 5
    echo -e "${GREEN}✅ Project created successfully${NC}"
fi

# Clean up any existing terraform state
echo ""
echo -e "${CYAN}🧹 Cleaning up previous Terraform states...${NC}"

# Clean the original terraform-gke directory
clean_terraform_directory "terraform-gke"

# Clean any existing project-specific directories
for dir in terraform-gke-*; do
    if [[ -d "$dir" ]]; then
        echo "  Found existing directory: $dir"
        clean_terraform_directory "$dir"
    fi
done

gcloud config set project "$PROJECT_ID"

# Deal with billing - this is the annoying part
echo "Handling billing setup..."
billing_status=$(gcloud billing projects describe "$PROJECT_ID" --format="value(billingEnabled)" 2>/dev/null)

if [[ "$billing_status" != "True" ]]; then
    if [[ -n "$BILLING_ACCOUNT_ID" ]]; then
        gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID" --quiet
        echo "Linked billing account"
    else
        echo "Need a billing account. Here's what you have:"
        gcloud billing accounts list
        echo ""
        echo "Run again with your billing account:"
        echo "./setup.sh -p '$PROJECT_ID' -b 'YOUR_BILLING_ID'"
        exit 1
    fi
else
    echo "Billing already set up"
fi

# Turn on the APIs we need
echo "Enabling APIs (this takes a minute)..."
needed_apis=(
    "container.googleapis.com"
    "artifactregistry.googleapis.com"
    "cloudbuild.googleapis.com"
    "compute.googleapis.com"
)

for api in "${needed_apis[@]}"; do
    gcloud services enable "$api" --project="$PROJECT_ID" --quiet
    echo "Enabled $api"
done

# Set up default credentials
echo "Setting up authentication..."
gcloud auth application-default login --quiet
gcloud auth application-default set-quota-project "$PROJECT_ID" --quiet
echo "Auth configured"

# Setup project-specific terraform directory
echo ""
terraform_directory=$(setup_project_specific_terraform "$PROJECT_ID" "$REGION" "$ZONE")

# Store terraform directory for other scripts to use
export TERRAFORM_DIR="$terraform_directory"
echo -e "${CYAN}🔧 Terraform directory set to: $terraform_directory${NC}"

# Save configuration for other scripts
config_path=".setup-config.sh"
cat > "$config_path" <<EOF
# Auto-generated configuration from setup.sh
# Do not edit manually - this file is overwritten on each setup run

export PROJECT_ID="$PROJECT_ID"
export REGION="$REGION"
export ZONE="$ZONE"
export REPO_NAME="$REPO_NAME"
export TERRAFORM_DIR="$terraform_directory"
EOF

if [[ -n "$GEMINI_API_KEY" ]]; then
    echo "export GEMINI_API_KEY=\"$GEMINI_API_KEY\"" >> "$config_path"
fi

echo -e "${GRAY}💾 Saved configuration to $config_path${NC}"

# Handle API key if they gave us one
if [[ -n "$GEMINI_API_KEY" ]]; then
    export GEMINI_API_KEY="$GEMINI_API_KEY"
    echo "Set Gemini API key"
else
    echo "No API key provided - you can set it later with:"
    echo "export GEMINI_API_KEY='your-key'"
fi

echo ""
echo -e "${GREEN}🎉 Setup completed successfully!${NC}"
echo ""
echo -e "${CYAN}📋 Configuration Summary:${NC}"
echo "  Project ID: $PROJECT_ID" 
echo "  Region: $REGION"
echo "  Zone: $ZONE"
echo "  Terraform Dir: $terraform_directory"
if [[ -n "$GEMINI_API_KEY" ]]; then
    echo -e "${GREEN}  Gemini API: Configured ✓${NC}"
else
    echo -e "${YELLOW}  Gemini API: Not configured ⚠️${NC}"
fi
echo ""
echo -e "${CYAN}📋 Next Steps:${NC}"
echo "1. Run ./deploy.sh to deploy the GKE cluster and applications"
echo "2. Run ./manage.sh status to check cluster status"  
echo "3. Run ./manage.sh pause to save costs when not using"
echo "4. Run ./teardown.sh when you're completely done"
echo ""
if [[ -z "$GEMINI_API_KEY" ]]; then
    echo -e "${YELLOW}💡 Pro tip: Set your Gemini API key for enhanced AI features:${NC}"
    echo "   export GEMINI_API_KEY='your-api-key-here'"
    echo ""
fi
echo -e "${YELLOW}💰 Cost reminder: Remember to pause/teardown when not actively developing!${NC}"
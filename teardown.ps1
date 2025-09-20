#Requires -Version 5.1

param(
    [Parameter(Mandatory=$false)]
    [string]$ProjectId = "",
    [Parameter(Mandatory=$false)]
    [switch]$DeleteProject = $false,
    [Parameter(Mandatory=$false)]
    [switch]$Force = $false
)

# Get project ID
if (-not $ProjectId) {
    $ProjectId = $env:PROJECT_ID
    if (-not $ProjectId) {
        $ProjectId = (gcloud config get-value project).Trim()
    }
}

if (-not $ProjectId) {
    Write-Error "No project ID found. Please provide -ProjectId parameter"
    exit 1
}

$env:PROJECT_ID = $ProjectId
$env:REGION = "us-central1"
$env:ZONE = "us-central1-a"

Write-Host "========================================="
Write-Host "GKE TURNS 10 HACKATHON TEARDOWN"
Write-Host "========================================="
Write-Host "Project: $env:PROJECT_ID"
Write-Host ""

if (-not $Force) {
    Write-Warning "This will destroy all resources in the project!"
    Write-Host ""
    
    if ($DeleteProject) {
        Write-Warning "The entire project will be PERMANENTLY DELETED!"
        Write-Host "This action is IRREVERSIBLE!"
    }
    
    Write-Host ""
    $confirm = Read-Host "Type 'DESTROY' to confirm destruction"
    if ($confirm -ne "DESTROY") {
        Write-Host "Teardown cancelled"
        exit 0
    }
}

gcloud config set project $env:PROJECT_ID

# Step 1: Clean up Kubernetes resources
Write-Host "=== CLEANING KUBERNETES RESOURCES ==="
try {
    gcloud container clusters get-credentials gke-turns-10-hackathon --zone=$env:ZONE --project=$env:PROJECT_ID 2>$null
    
    Write-Host "Deleting all custom deployments and services..."
    kubectl delete --all deployments,services,pods --timeout=60s 2>$null
    
    # Clean up Online Boutique if it exists
    if (Test-Path "microservices-demo/release/kubernetes-manifests.yaml") {
        Write-Host "Cleaning up Online Boutique..."
        kubectl delete -f microservices-demo/release/kubernetes-manifests.yaml --ignore-not-found=true 2>$null
    }
    
    Write-Host "✓ Kubernetes resources cleaned"
}
catch {
    Write-Host "⚠ Could not clean Kubernetes resources (cluster may not exist)"
}

# Step 2: Destroy Terraform infrastructure
Write-Host ""
Write-Host "=== DESTROYING INFRASTRUCTURE ==="
if (Test-Path "terraform-gke") {
    Set-Location "terraform-gke"
    
    if (Test-Path "terraform.tfstate") {
        Write-Host "Destroying Terraform infrastructure..."
        terraform destroy -auto-approve
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Terraform infrastructure destroyed"
        } else {
            Write-Warning "⚠ Some Terraform resources may not have been destroyed"
        }
    } else {
        Write-Host "No Terraform state found, skipping..."
    }
    
    Set-Location ".."
} else {
    Write-Host "No terraform-gke directory found, skipping..."
}

# Step 3: Clean up any remaining GCP resources
Write-Host ""
Write-Host "=== CLEANING REMAINING GCP RESOURCES ==="

# Delete any remaining compute instances
Write-Host "Checking for remaining compute instances..."
$instances = gcloud compute instances list --project=$env:PROJECT_ID --format="value(name,zone)" 2>$null
if ($instances) {
    foreach ($instance in $instances) {
        $parts = $instance -split '\t'
        $name = $parts[0]
        $zone = $parts[1]
        Write-Host "Deleting instance: $name in $zone"
        gcloud compute instances delete $name --zone=$zone --project=$env:PROJECT_ID --quiet
    }
}

# Delete container images from Artifact Registry
Write-Host "Cleaning up container images..."
$repos = gcloud artifacts repositories list --location=$env:REGION --project=$env:PROJECT_ID --format="value(name)" 2>$null
foreach ($repo in $repos) {
    if ($repo -like "*gke-turns-10-repo*") {
        Write-Host "Deleting repository: $repo"
        gcloud artifacts repositories delete $repo --location=$env:REGION --project=$env:PROJECT_ID --quiet
    }
}

# Delete any remaining disks
Write-Host "Checking for remaining persistent disks..."
$disks = gcloud compute disks list --project=$env:PROJECT_ID --format="value(name,zone)" 2>$null
if ($disks) {
    foreach ($disk in $disks) {
        $parts = $disk -split '\t'
        $name = $parts[0]
        $zone = $parts[1]
        Write-Host "Deleting disk: $name in $zone"
        gcloud compute disks delete $name --zone=$zone --project=$env:PROJECT_ID --quiet
    }
}

# Step 4: Optionally delete the entire project
if ($DeleteProject) {
    Write-Host ""
    Write-Host "=== DELETING PROJECT ==="
    
    if (-not $Force) {
        Write-Host ""
        Write-Warning "FINAL CONFIRMATION REQUIRED!"
        Write-Warning "This will PERMANENTLY DELETE the entire project: $env:PROJECT_ID"
        Write-Warning "ALL DATA, CONFIGURATIONS, AND HISTORY WILL BE LOST!"
        Write-Host ""
        
        $finalConfirm = Read-Host "Type the project name '$env:PROJECT_ID' to confirm deletion"
        if ($finalConfirm -ne $env:PROJECT_ID) {
            Write-Host "Project name doesn't match. Project deletion cancelled."
            Write-Host "Infrastructure has been destroyed but project preserved."
            exit 0
        }
    }
    
    Write-Host "Deleting project completely..."
    gcloud projects delete $env:PROJECT_ID --quiet
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Project deleted successfully"
    } else {
        Write-Warning "⚠ Project deletion may have failed"
    }
} else {
    Write-Host ""
    Write-Host "Project preserved. Infrastructure destroyed."
    Write-Host "To delete the project completely, run:"
    Write-Host "  .\teardown.ps1 -ProjectId '$env:PROJECT_ID' -DeleteProject"
}

Write-Host ""
Write-Host "========================================="
Write-Host "TEARDOWN COMPLETED"
Write-Host "========================================="
Write-Host "💰 Billing Impact: Resources destroyed"

if (-not $DeleteProject) {
    Write-Host ""
    Write-Host "The project still exists with:"
    Write-Host "  • APIs enabled (no cost)"
    Write-Host "  • IAM policies (no cost)"
    Write-Host "  • Project billing link (no cost)"
    Write-Host ""
    Write-Host "You can reuse this project by running:"
    Write-Host "  .\deploy.ps1 -ProjectId '$env:PROJECT_ID'"
}
# Project setup script for GKE hackathon
# I got tired of doing this manually every time, so here's a script that does it all

param(
    [string]$ProjectId = "",
    [string]$BillingAccountId = "",  
    [string]$GeminiApiKey = "",
    [string]$Region = "us-central1",
    [string]$Zone = "us-central1-a"
)

function Check-Tools {
    Write-Host "Making sure we have the right tools installed..."
    $isWindowsOS = $PSVersionTable.PSVersion.Major -ge 6 -and $IsWindows -or $PSVersionTable.PSVersion.Major -lt 6
    $toolsValid = $true
    
    # Check for gcloud
    try {
        if ($isWindowsOS) {
            $gcloudCheck = & gcloud version --format="text" 2>$null | Select-String "Google Cloud SDK"
        } else {
            $gcloudCheck = gcloud version --format="text" 2>/dev/null | grep "Google Cloud SDK"
        }
        if (-not $gcloudCheck) { 
            throw "Can't find gcloud" 
        }
        Write-Host "[OK] Found Google Cloud SDK" -ForegroundColor Green
    }
    catch {
        Write-Host "[ERROR] You need to install the Google Cloud SDK first" -ForegroundColor Red
        Write-Host "Get it here: https://cloud.google.com/sdk/docs/install"
        $toolsValid = $false
    }
    
    # Check for kubectl  
    try {
        if ($isWindowsOS) {
            $kubectlCheck = & kubectl version --client 2>$null
        } else {
            $kubectlCheck = kubectl version --client 2>/dev/null
        }
        if ($LASTEXITCODE -ne 0 -or -not $kubectlCheck) { 
            throw "Can't find kubectl" 
        }
        Write-Host "[OK] Found kubectl" -ForegroundColor Green
    }
    catch {
        Write-Host "[ERROR] You need kubectl installed too" -ForegroundColor Red
        $toolsValid = $false
    }
    
    # Check for terraform
    try {
        if ($isWindowsOS) {
            $terraformCheck = & terraform version 2>$null
        } else {
            $terraformCheck = terraform version 2>/dev/null
        }
        if ($LASTEXITCODE -ne 0 -or -not $terraformCheck) { 
            throw "Can't find terraform" 
        }
        Write-Host "[OK] Found Terraform" -ForegroundColor Green
    }
    catch {
        Write-Host "[WARNING] Terraform not found - will skip terraform operations" -ForegroundColor Yellow
    }
    
    # Check if Docker is running
    try {
        if ($isWindowsOS) {
            $dockerCheck = & docker ps 2>$null
        } else {
            $dockerCheck = docker ps 2>/dev/null
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Docker not running"
        }
        Write-Host "[OK] Docker is running" -ForegroundColor Green
    }
    catch {
        Write-Host "[ERROR] Docker is not running or not installed" -ForegroundColor Red
        if ($isWindowsOS) {
            Write-Host "Please start Docker Desktop and try again" -ForegroundColor Red
        } else {
            Write-Host "Please start Docker daemon and try again" -ForegroundColor Red
            Write-Host "Try: sudo systemctl start docker" -ForegroundColor Gray
        }
        $toolsValid = $false
    }
    
    # Check if Kubernetes is available (kubectl context)
    try {
        if ($isWindowsOS) {
            $kubeCheck = & kubectl cluster-info --request-timeout=5s 2>$null
        } else {
            $kubeCheck = kubectl cluster-info --request-timeout=5s 2>/dev/null
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Kubernetes not available"
        }
        Write-Host "[OK] Kubernetes cluster is accessible" -ForegroundColor Green
    }
    catch {
        Write-Host "[WARNING] Kubernetes cluster not accessible" -ForegroundColor Yellow
        Write-Host "This is normal if you haven't set up a cluster yet" -ForegroundColor Yellow
        if ($isWindowsOS) {
            Write-Host "Make sure Docker Desktop has Kubernetes enabled or you have access to a cluster" -ForegroundColor Yellow
        } else {
            Write-Host "Make sure you have access to a Kubernetes cluster (minikube, k3s, etc.)" -ForegroundColor Yellow
        }
    }
    
    # Exit if any required tools are missing
    if (-not $toolsValid) {
        Write-Host ""
        Write-Host "[FATAL] Required tools are missing. Please install them and try again." -ForegroundColor Red
        exit 1
    }
}

function Clean-TerraformDirectory {
    param([string]$TerraformDir)
    
    if (Test-Path $TerraformDir) {
        Write-Host "Cleaning up previous Terraform state in $TerraformDir..." -ForegroundColor Yellow
        
        try {
            # Remove terraform state files
            $stateFiles = @("terraform.tfstate", "terraform.tfstate.backup", ".terraform.lock.hcl")
            foreach ($file in $stateFiles) {
                $fullPath = Join-Path $TerraformDir $file
                if (Test-Path $fullPath) {
                    Remove-Item $fullPath -Force
                    Write-Host "  [OK] Removed $file" -ForegroundColor Gray
                }
            }
            
            # Remove .terraform directory
            $terraformSubDir = Join-Path $TerraformDir ".terraform"
            if (Test-Path $terraformSubDir) {
                Remove-Item $terraformSubDir -Recurse -Force
                Write-Host "  [OK] Removed .terraform directory" -ForegroundColor Gray
            }
            
            # Remove plan files
            $planFiles = Get-ChildItem $TerraformDir -Filter "*.tfplan" -ErrorAction SilentlyContinue
            foreach ($planFile in $planFiles) {
                Remove-Item $planFile.FullName -Force
                Write-Host "  [OK] Removed $($planFile.Name)" -ForegroundColor Gray
            }
            
            # Remove tfplan file specifically
            $tfplanPath = Join-Path $TerraformDir "tfplan"
            if (Test-Path $tfplanPath) {
                Remove-Item $tfplanPath -Force
                Write-Host "  [OK] Removed tfplan" -ForegroundColor Gray
            }
            
            Write-Host "  [SUCCESS] Terraform directory cleaned" -ForegroundColor Green
        }
        catch {
            Write-Host "  [WARNING] Error cleaning terraform directory: $_" -ForegroundColor Yellow
        }
    }
}

function Setup-ProjectSpecificTerraform {
    param([string]$ProjectId, [string]$Region, [string]$Zone)
    
    $terraformDir = "terraform-gke-$ProjectId"
    $templateDir = "terraform-gke"
    
    Write-Host "Setting up project-specific Terraform directory: $terraformDir" -ForegroundColor Cyan
    
    try {
        # Create project-specific directory
        if (-not (Test-Path $terraformDir)) {
            New-Item -ItemType Directory -Path $terraformDir -Force | Out-Null
            Write-Host "  [OK] Created directory $terraformDir" -ForegroundColor Green
        }
        
        # Copy terraform files from template if they exist
        if (Test-Path $templateDir) {
            $terraformFiles = Get-ChildItem $templateDir -Filter "*.tf" -ErrorAction SilentlyContinue
            foreach ($file in $terraformFiles) {
                Copy-Item $file.FullName -Destination $terraformDir -Force
                Write-Host "  [OK] Copied $($file.Name)" -ForegroundColor Gray
            }
            
            # Copy outputs.tf if it exists
            $outputsFile = Join-Path $templateDir "outputs.tf"
            if (Test-Path $outputsFile) {
                Copy-Item $outputsFile -Destination $terraformDir -Force
                Write-Host "  [OK] Copied outputs.tf" -ForegroundColor Gray
            }
        }
        
        # Create/update terraform.tfvars with project-specific values
        $tfvarsPath = Join-Path $terraformDir "terraform.tfvars"
        $tfvarsContent = @"
# Project Configuration - Generated by setup.ps1
project_id = "$ProjectId"
region     = "$Region"
zone       = "$Zone"
cluster_name = "gke-turns-10-hackathon"
# AutoPilot clusters don't use manual node pools
node_count = 1
machine_type = "e2-standard-2"
disk_size_gb = 20

# Repository Configuration
repo_name = "gke-turns-10-repo"
"@
        
        $tfvarsContent | Set-Content $tfvarsPath -Force
        Write-Host "  [OK] Created terraform.tfvars with project settings" -ForegroundColor Green
        
        return $terraformDir
    }
    catch {
        Write-Host "  [ERROR] Error setting up terraform directory: $_" -ForegroundColor Red
        return $templateDir  # Fallback to original directory
    }
}

# Make up a project ID if they didn't give us one
if (-not $ProjectId) {
    $today = Get-Date -Format "MMdd"
    $randomNum = Get-Random -Maximum 9999
    $ProjectId = "gke-hackathon-$today-$randomNum"
}

$env:PROJECT_ID = $ProjectId
$env:REGION = $Region  
$env:ZONE = $Zone
$env:REPO_NAME = "gke-turns-10-repo"

Write-Host ""
Write-Host "Setting up GKE environment..."  
Write-Host "Project: $env:PROJECT_ID"
Write-Host "Region: $env:REGION"
Write-Host "Zone: $env:ZONE"
Write-Host ""

# Make sure they're logged into gcloud
$currentUser = gcloud config get-value account 2>$null
if (-not $currentUser) {
    Write-Host "You need to login to Google Cloud first"
    gcloud auth login
}

Check-Tools

# Check if project already exists and handle cleanup
Write-Host "Checking project status..."
$projectCheck = gcloud projects describe $env:PROJECT_ID 2>$null
$projectExists = $projectCheck -ne $null

if ($projectExists) {
    Write-Host "[WARNING] Project '$env:PROJECT_ID' already exists!" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "This project may have existing resources that could:"
    Write-Host "- Conflict with new deployments"
    Write-Host "- Continue charging costs"
    Write-Host "- Have inconsistent configurations"
    Write-Host ""
    
    $cleanupChoice = Read-Host "Do you want to clean up existing project resources? (yes/no/cancel)"
    
    switch ($cleanupChoice.ToLower()) {
        "yes" {
            Write-Host "Starting cleanup of existing project resources..." -ForegroundColor Yellow
            
            # Clean up GKE clusters
            Write-Host "Checking for existing GKE clusters..."
            $clusters = gcloud container clusters list --project=$env:PROJECT_ID --format="value(name,zone)" 2>$null
            if ($clusters) {
                Write-Host "Found existing clusters. Deleting them..."
                foreach ($clusterInfo in $clusters) {
                    if ($clusterInfo.Trim()) {
                        $parts = $clusterInfo -split "`t"
                        if ($parts.Length -ge 2) {
                            $clusterName = $parts[0].Trim()
                            $clusterZone = $parts[1].Trim()
                            Write-Host "  Deleting cluster: $clusterName in $clusterZone"
                            gcloud container clusters delete $clusterName --zone=$clusterZone --project=$env:PROJECT_ID --quiet
                        }
                    }
                }
            }
            
            # Clean up Artifact Registry repositories
            Write-Host "Checking for Artifact Registry repositories..."
            $repos = gcloud artifacts repositories list --project=$env:PROJECT_ID --format="value(name)" 2>$null
            if ($repos) {
                Write-Host "Found existing repositories. Deleting them..."
                foreach ($repo in $repos) {
                    if ($repo.Trim()) {
                        Write-Host "  Deleting repository: $repo"
                        gcloud artifacts repositories delete $repo --project=$env:PROJECT_ID --quiet
                    }
                }
            }
            
            Write-Host "[SUCCESS] Project cleanup completed" -ForegroundColor Green
        }
        "no" {
            Write-Host "[WARNING] Continuing with existing project (resources may conflict)" -ForegroundColor Yellow
        }
        "cancel" {
            Write-Host "[INFO] Setup cancelled by user" -ForegroundColor Red
            exit 0
        }
        default {
            Write-Host "[ERROR] Invalid choice. Setup cancelled." -ForegroundColor Red
            exit 1
        }
    }
} else {
    Write-Host "Creating new project: $env:PROJECT_ID" -ForegroundColor Cyan
    gcloud projects create $env:PROJECT_ID --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create project. It may already exist or you may lack permissions." -ForegroundColor Red
        exit 1
    }
    Start-Sleep -Seconds 5
    Write-Host "[SUCCESS] Project created successfully" -ForegroundColor Green
}

# Clean up any existing terraform state
Write-Host ""
Write-Host "Cleaning up previous Terraform states..." -ForegroundColor Cyan

# Clean the original terraform-gke directory
Clean-TerraformDirectory "terraform-gke"

# Clean any existing project-specific directories
$existingTerraformDirs = Get-ChildItem -Directory -Name "terraform-gke-*" -ErrorAction SilentlyContinue
foreach ($dir in $existingTerraformDirs) {
    Write-Host "  Found existing directory: $dir"
    Clean-TerraformDirectory $dir
}

gcloud config set project $env:PROJECT_ID

# Deal with billing - this is the annoying part
Write-Host "Handling billing setup..."
$billingStatus = gcloud billing projects describe $env:PROJECT_ID --format="value(billingEnabled)" 2>$null

if ($billingStatus -ne "True") {
    if ($BillingAccountId) {
        gcloud billing projects link $env:PROJECT_ID --billing-account=$BillingAccountId --quiet
        Write-Host "Linked billing account"
    } else {
        Write-Host "Need a billing account. Here's what you have:"
        gcloud billing accounts list
        Write-Host ""
        Write-Host "Run again with your billing account:"
        Write-Host ".\setup.ps1 -ProjectId '$env:PROJECT_ID' -BillingAccountId 'YOUR_BILLING_ID'"
        exit 1
    }
} else {
    Write-Host "Billing already set up"
}

# Turn on the APIs we need
Write-Host "Enabling APIs (this takes a minute)..."
$neededApis = @(
    "container.googleapis.com",
    "artifactregistry.googleapis.com", 
    "cloudbuild.googleapis.com",
    "compute.googleapis.com"
)

foreach ($api in $neededApis) {
    gcloud services enable $api --project=$env:PROJECT_ID --quiet
    Write-Host "Enabled $api"
}

# Set up default credentials
Write-Host "Setting up authentication..."
gcloud auth application-default login --quiet
gcloud auth application-default set-quota-project $env:PROJECT_ID --quiet
Write-Host "Auth configured"

# Setup project-specific terraform directory
Write-Host ""
$terraformDirectory = Setup-ProjectSpecificTerraform $env:PROJECT_ID $env:REGION $env:ZONE

# Store terraform directory for other scripts to use
$env:TERRAFORM_DIR = $terraformDirectory
Write-Host "Terraform directory set to: $terraformDirectory" -ForegroundColor Cyan

# Save configuration for other scripts
$configPath = ".setup-config.ps1"
$configContent = @"
# Auto-generated configuration from setup.ps1
# Do not edit manually - this file is overwritten on each setup run

`$env:PROJECT_ID = "$env:PROJECT_ID"
`$env:REGION = "$env:REGION"
`$env:ZONE = "$env:ZONE"
`$env:REPO_NAME = "$env:REPO_NAME"
`$env:TERRAFORM_DIR = "$terraformDirectory"
"@

if ($GeminiApiKey) {
    $env:GEMINI_API_KEY = $GeminiApiKey
    $configContent += "`n`$env:GEMINI_API_KEY = `"$env:GEMINI_API_KEY`""
}

$configContent | Set-Content $configPath
Write-Host "Saved configuration to $configPath" -ForegroundColor Gray

# Handle API key if they gave us one
if ($GeminiApiKey) {
    Write-Host "Set Gemini API key"
} else {
    Write-Host "No API key provided - you can set it later with:"
    Write-Host "`$env:GEMINI_API_KEY = 'your-key'"
}

Write-Host ""
Write-Host "[SUCCESS] Setup completed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Configuration Summary:" -ForegroundColor Cyan
Write-Host "  Project ID: $env:PROJECT_ID" 
Write-Host "  Region: $env:REGION"
Write-Host "  Zone: $env:ZONE"
Write-Host "  Terraform Dir: $terraformDirectory"
if ($env:GEMINI_API_KEY) {
    Write-Host "  Gemini API: Configured [OK]" -ForegroundColor Green
} else {
    Write-Host "  Gemini API: Not configured [WARNING]" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. Run .\deploy.ps1 to deploy the GKE cluster and applications"
Write-Host "2. Run .\manage.ps1 -Action status to check cluster status"  
Write-Host "3. Run .\manage.ps1 -Action pause to save costs when not using"
Write-Host "4. Run .\teardown.ps1 when you're completely done"
Write-Host ""
if (-not $env:GEMINI_API_KEY) {
    Write-Host "Pro tip: Set your Gemini API key for enhanced AI features:" -ForegroundColor Yellow
    Write-Host "   `$env:GEMINI_API_KEY = 'your-api-key-here'"
    Write-Host ""
}
Write-Host "Cost reminder: Remember to pause/teardown when not actively developing!" -ForegroundColor Yellow
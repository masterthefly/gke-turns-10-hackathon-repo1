#Requires -Version 5.1

<#
.SYNOPSIS
    GKE Cluster Pause/Resume Script for Cost Optimization
    
.DESCRIPTION
    ⚠️  WARNING: This script is designed for STANDARD GKE clusters with manual node pools.
    ⚠️  For AUTOPILOT clusters, use manage.ps1 instead as AutoPilot manages nodes automatically.
    
    This script can pause (scale down to 0) or resume a GKE cluster and all its workloads
    to minimize billing costs while preserving the ability to quickly restore.
    
    PAUSE MODE: Scales node pools to 0 and deployments to 0 replicas
    RESUME MODE: Restores previous scales from saved state file
    
    NOTE: AutoPilot clusters don't support manual node pool scaling operations.
    
.PARAMETER ClusterName
    Name of the GKE cluster
    
.PARAMETER Zone
    GCP zone where cluster is located (for zonal clusters)
    
.PARAMETER Region  
    GCP region where cluster is located (for regional clusters)
    
.PARAMETER Project
    GCP project ID
    
.PARAMETER Action
    Action to perform: 'pause', 'resume', or 'delete'
    
.PARAMETER StateFile
    Path to save/restore cluster state (default: cluster-state.json)
    
.PARAMETER Force
    Skip confirmation prompts
    
.EXAMPLE
    .\gke-pause.ps1 -ClusterName "my-cluster" -Zone "us-central1-a" -Project "my-project" -Action "pause"
    
.EXAMPLE  
    .\gke-pause.ps1 -ClusterName "my-cluster" -Region "us-central1" -Project "my-project" -Action "resume"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ClusterName,
    
    [Parameter(Mandatory=$false)]
    [string]$Zone,
    
    [Parameter(Mandatory=$false)]
    [string]$Region,
    
    [Parameter(Mandatory=$true)]
    [string]$Project,
    
    [Parameter(Mandatory=$true)]
    [ValidateSet('pause', 'resume', 'delete')]
    [string]$Action,
    
    [Parameter(Mandatory=$false)]
    [string]$StateFile = "cluster-state-$ClusterName.json",
    
    [Parameter(Mandatory=$false)]
    [switch]$Force
)

# Color functions for better output
function Write-ColorText {
    param(
        [string]$Text,
        [string]$Color = "White"
    )
    Write-Host $Text -ForegroundColor $Color
}

function Write-Success { param([string]$Text) Write-ColorText $Text "Green" }
function Write-Warning { param([string]$Text) Write-ColorText $Text "Yellow" }  
function Write-Error { param([string]$Text) Write-ColorText $Text "Red" }
function Write-Info { param([string]$Text) Write-ColorText $Text "Cyan" }

# Validate prerequisites
function Test-Prerequisites {
    Write-Info "Checking prerequisites..."
    
    # Check if gcloud is installed
    try {
        $gcloudVersion = gcloud version --format="value(Google Cloud SDK)" 2>$null
        if (-not $gcloudVersion) {
            throw "gcloud not found"
        }
        Write-Success "✓ Google Cloud SDK found: $gcloudVersion"
    }
    catch {
        Write-Error "❌ Google Cloud SDK not found. Please install: https://cloud.google.com/sdk/docs/install"
        exit 1
    }
    
    # Check if kubectl is installed  
    try {
        $kubectlVersion = kubectl version --client --short 2>$null
        if (-not $kubectlVersion) {
            throw "kubectl not found"
        }
        Write-Success "✓ kubectl found: $($kubectlVersion -split '\n' | Select-Object -First 1)"
    }
    catch {
        Write-Error "❌ kubectl not found. Please install: https://kubernetes.io/docs/tasks/tools/install-kubectl/"
        exit 1
    }
    
    # Check authentication
    try {
        $currentProject = gcloud config get-value project 2>$null
        if ($currentProject -ne $Project) {
            Write-Warning "⚠️  Current project ($currentProject) differs from specified ($Project)"
            gcloud config set project $Project
        }
        Write-Success "✓ Authenticated to project: $Project"
    }
    catch {
        Write-Error "❌ Not authenticated to GCP. Run: gcloud auth login"
        exit 1
    }
}

# Get cluster credentials and basic info
function Get-ClusterInfo {
    Write-Info "Getting cluster information..."
    
    $locationFlag = if ($Zone) { "--zone=$Zone" } elseif ($Region) { "--region=$Region" } else { 
        Write-Error "❌ Must specify either -Zone or -Region"
        exit 1 
    }
    
    try {
        # Get cluster credentials
        Write-Info "Getting cluster credentials..."
        gcloud container clusters get-credentials $ClusterName $locationFlag --project=$Project
        if ($LASTEXITCODE -ne 0) { throw "Failed to get credentials" }
        
        # Check if cluster exists and get info
        $clusterInfo = gcloud container clusters describe $ClusterName $locationFlag --project=$Project --format=json | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw "Cluster not found" }
        
        Write-Success "✓ Connected to cluster: $ClusterName"
        Write-Info "  Status: $($clusterInfo.status)"
        Write-Info "  Location: $($clusterInfo.location)"
        Write-Info "  Node Count: $($clusterInfo.currentNodeCount)"
        
        return $clusterInfo
    }
    catch {
        Write-Error "❌ Failed to connect to cluster: $_"
        exit 1
    }
}

# Save current cluster state
function Save-ClusterState {
    Write-Info "Saving current cluster state..."
    
    $state = @{
        timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ"
        clusterName = $ClusterName
        project = $Project
        zone = $Zone
        region = $Region
        nodePools = @()
        workloads = @()
    }
    
    try {
        # Save node pool information
        Write-Info "Saving node pool states..."
        $locationFlag = if ($Zone) { "--zone=$Zone" } else { "--region=$Region" }
        
        $nodePools = gcloud container node-pools list --cluster=$ClusterName $locationFlag --project=$Project --format=json | ConvertFrom-Json
        
        foreach ($pool in $nodePools) {
            $poolState = @{
                name = $pool.name
                initialNodeCount = $pool.initialNodeCount
                status = $pool.status
                nodeCount = $pool.initialNodeCount
                autoscaling = $null
            }
            
            # Check if autoscaling is enabled
            if ($pool.autoscaling) {
                $poolState.autoscaling = @{
                    enabled = $pool.autoscaling.enabled
                    minNodeCount = $pool.autoscaling.minNodeCount  
                    maxNodeCount = $pool.autoscaling.maxNodeCount
                }
            }
            
            $state.nodePools += $poolState
            Write-Success "  ✓ Saved node pool: $($pool.name) (nodes: $($pool.initialNodeCount))"
        }
        
        # Save workload states (deployments, statefulsets, daemonsets)
        Write-Info "Saving workload states..."
        
        # Get deployments
        $deployments = kubectl get deployments --all-namespaces -o json | ConvertFrom-Json
        foreach ($deploy in $deployments.items) {
            $workload = @{
                type = "deployment"
                name = $deploy.metadata.name
                namespace = $deploy.metadata.namespace
                replicas = $deploy.spec.replicas
            }
            $state.workloads += $workload
            Write-Success "  ✓ Saved deployment: $($deploy.metadata.namespace)/$($deploy.metadata.name) (replicas: $($deploy.spec.replicas))"
        }
        
        # Get statefulsets  
        $statefulsets = kubectl get statefulsets --all-namespaces -o json | ConvertFrom-Json
        foreach ($sts in $statefulsets.items) {
            $workload = @{
                type = "statefulset"
                name = $sts.metadata.name
                namespace = $sts.metadata.namespace
                replicas = $sts.spec.replicas
            }
            $state.workloads += $workload
            Write-Success "  ✓ Saved statefulset: $($sts.metadata.namespace)/$($sts.metadata.name) (replicas: $($sts.spec.replicas))"
        }
        
        # Save state to file
        $state | ConvertTo-Json -Depth 10 | Out-File -FilePath $StateFile -Encoding UTF8
        Write-Success "✓ Cluster state saved to: $StateFile"
        
        return $state
    }
    catch {
        Write-Error "❌ Failed to save cluster state: $_"
        exit 1
    }
}

# Pause cluster (scale everything to 0)
function Invoke-ClusterPause {
    param([object]$ClusterState)
    
    Write-Warning "🔄 PAUSING CLUSTER - This will scale down all resources to minimize costs"
    
    if (-not $Force) {
        $confirm = Read-Host "Are you sure you want to pause cluster '$ClusterName'? (yes/no)"
        if ($confirm -ne "yes") {
            Write-Info "Operation cancelled."
            return
        }
    }
    
    try {
        # Scale deployments to 0
        Write-Info "Scaling deployments to 0 replicas..."
        foreach ($workload in $ClusterState.workloads) {
            if ($workload.type -eq "deployment" -and $workload.replicas -gt 0) {
                kubectl scale deployment $workload.name --namespace=$workload.namespace --replicas=0
                if ($LASTEXITCODE -eq 0) {
                    Write-Success "  ✓ Scaled deployment: $($workload.namespace)/$($workload.name) to 0"
                }
                else {
                    Write-Warning "  ⚠️  Failed to scale deployment: $($workload.namespace)/$($workload.name)"
                }
            }
        }
        
        # Scale statefulsets to 0  
        Write-Info "Scaling statefulsets to 0 replicas..."
        foreach ($workload in $ClusterState.workloads) {
            if ($workload.type -eq "statefulset" -and $workload.replicas -gt 0) {
                kubectl scale statefulset $workload.name --namespace=$workload.namespace --replicas=0
                if ($LASTEXITCODE -eq 0) {
                    Write-Success "  ✓ Scaled statefulset: $($workload.namespace)/$($workload.name) to 0"
                }
                else {
                    Write-Warning "  ⚠️  Failed to scale statefulset: $($workload.namespace)/$($workload.name)"
                }
            }
        }
        
        # Wait for pods to terminate
        Write-Info "Waiting for pods to terminate..."
        Start-Sleep -Seconds 30
        
        # Scale node pools to 0
        Write-Info "Scaling node pools to 0 nodes..."
        $locationFlag = if ($Zone) { "--zone=$Zone" } else { "--region=$Region" }
        
        foreach ($pool in $ClusterState.nodePools) {
            if ($pool.nodeCount -gt 0) {
                Write-Info "  Scaling node pool '$($pool.name)' to 0 nodes..."
                
                # Disable autoscaling first if enabled
                if ($pool.autoscaling -and $pool.autoscaling.enabled) {
                    gcloud container clusters update $ClusterName $locationFlag --no-enable-autoscaling --node-pool=$pool.name --project=$Project --quiet
                }
                
                # Scale to 0
                gcloud container clusters resize $ClusterName --node-pool=$pool.name --num-nodes=0 $locationFlag --project=$Project --quiet
                
                if ($LASTEXITCODE -eq 0) {
                    Write-Success "  ✓ Scaled node pool '$($pool.name)' to 0 nodes"
                }
                else {
                    Write-Warning "  ⚠️  Failed to scale node pool: $($pool.name)"
                }
            }
        }
        
        Write-Success "🎉 CLUSTER PAUSED SUCCESSFULLY!"
        Write-Info "💰 Billing Impact:"
        Write-Info "  • Node compute costs: ~$0/hour (nodes scaled to 0)"
        Write-Info "  • Control plane cost: ~$0.10/hour (GKE management fee)"  
        Write-Info "  • Storage costs: Unchanged (persistent volumes retained)"
        Write-Info ""
        Write-Info "📋 To resume: .\gke-pause.ps1 -ClusterName '$ClusterName' -Project '$Project' $(if($Zone){"-Zone '$Zone'"}else{"-Region '$Region'"}) -Action resume"
        
    }
    catch {
        Write-Error "❌ Failed to pause cluster: $_"
        exit 1
    }
}

# Resume cluster (restore previous state)
function Invoke-ClusterResume {
    Write-Info "🔄 RESUMING CLUSTER from saved state..."
    
    if (-not (Test-Path $StateFile)) {
        Write-Error "❌ State file not found: $StateFile"
        Write-Info "Cannot resume without saved state. You may need to manually scale resources."
        exit 1
    }
    
    try {
        $savedState = Get-Content $StateFile -Raw | ConvertFrom-Json
        Write-Info "📋 Found saved state from: $($savedState.timestamp)"
        
        if (-not $Force) {
            $confirm = Read-Host "Resume cluster '$ClusterName' to previous state? (yes/no)"
            if ($confirm -ne "yes") {
                Write-Info "Operation cancelled."
                return
            }
        }
        
        # Scale node pools back up
        Write-Info "Scaling node pools back to original sizes..."
        $locationFlag = if ($Zone) { "--zone=$Zone" } else { "--region=$Region" }
        
        foreach ($pool in $savedState.nodePools) {
            if ($pool.nodeCount -gt 0) {
                Write-Info "  Scaling node pool '$($pool.name)' to $($pool.nodeCount) nodes..."
                
                gcloud container clusters resize $ClusterName --node-pool=$pool.name --num-nodes=$pool.nodeCount $locationFlag --project=$Project --quiet
                
                if ($LASTEXITCODE -eq 0) {
                    Write-Success "  ✓ Scaled node pool '$($pool.name)' to $($pool.nodeCount) nodes"
                }
                else {
                    Write-Warning "  ⚠️  Failed to scale node pool: $($pool.name)"
                }
                
                # Re-enable autoscaling if it was enabled
                if ($pool.autoscaling -and $pool.autoscaling.enabled) {
                    Write-Info "  Re-enabling autoscaling for '$($pool.name)'..."
                    gcloud container clusters update $ClusterName $locationFlag --enable-autoscaling --min-nodes=$($pool.autoscaling.minNodeCount) --max-nodes=$($pool.autoscaling.maxNodeCount) --node-pool=$pool.name --project=$Project --quiet
                }
            }
        }
        
        # Wait for nodes to be ready
        Write-Info "Waiting for nodes to become ready..."
        Start-Sleep -Seconds 60
        
        # Scale workloads back up
        Write-Info "Scaling workloads back to original sizes..."
        foreach ($workload in $savedState.workloads) {
            if ($workload.replicas -gt 0) {
                if ($workload.type -eq "deployment") {
                    kubectl scale deployment $workload.name --namespace=$workload.namespace --replicas=$workload.replicas
                    if ($LASTEXITCODE -eq 0) {
                        Write-Success "  ✓ Scaled deployment: $($workload.namespace)/$($workload.name) to $($workload.replicas)"
                    }
                }
                elseif ($workload.type -eq "statefulset") {
                    kubectl scale statefulset $workload.name --namespace=$workload.namespace --replicas=$workload.replicas
                    if ($LASTEXITCODE -eq 0) {
                        Write-Success "  ✓ Scaled statefulset: $($workload.namespace)/$($workload.name) to $($workload.replicas)"
                    }
                }
            }
        }
        
        Write-Success "🎉 CLUSTER RESUMED SUCCESSFULLY!"
        Write-Info "💰 Billing Impact: Normal cluster costs restored"
        Write-Info "📋 Check cluster status: kubectl get nodes,pods --all-namespaces"
        
    }
    catch {
        Write-Error "❌ Failed to resume cluster: $_"
        exit 1
    }
}

# Delete cluster completely (true zero cost)
function Invoke-ClusterDelete {
    Write-Warning "⚠️  DANGER: This will PERMANENTLY DELETE the entire cluster!"
    Write-Warning "💀 ALL DATA AND CONFIGURATIONS WILL BE LOST!"
    Write-Info "💰 This achieves true $0 billing but requires complete recreation."
    
    if (-not $Force) {
        Write-Host ""
        $confirm1 = Read-Host "Type the cluster name '$ClusterName' to confirm deletion"
        if ($confirm1 -ne $ClusterName) {
            Write-Info "Cluster name doesn't match. Deletion cancelled."
            return
        }
        
        $confirm2 = Read-Host "Type 'DELETE' to confirm permanent deletion"
        if ($confirm2 -ne "DELETE") {
            Write-Info "Confirmation failed. Deletion cancelled."
            return
        }
    }
    
    try {
        $locationFlag = if ($Zone) { "--zone=$Zone" } else { "--region=$Region" }
        
        Write-Warning "🗑️  Deleting cluster '$ClusterName'..."
        gcloud container clusters delete $ClusterName $locationFlag --project=$Project --quiet
        
        if ($LASTEXITCODE -eq 0) {
            Write-Success "✅ Cluster '$ClusterName' deleted successfully"
            Write-Info "💰 Billing Impact: $0/hour (complete deletion)"
            
            # Clean up state file
            if (Test-Path $StateFile) {
                Remove-Item $StateFile -Force
                Write-Info "🧹 Cleaned up state file: $StateFile"
            }
        }
        else {
            Write-Error "❌ Failed to delete cluster"
            exit 1
        }
    }
    catch {
        Write-Error "❌ Failed to delete cluster: $_"
        exit 1
    }
}

# Show current cluster costs estimate
function Show-CostEstimate {
    param([object]$ClusterInfo)
    
    Write-Info "📊 CURRENT COST ESTIMATE (USD/hour):"
    
    $nodeCount = $ClusterInfo.currentNodeCount
    $machineType = "Unknown"
    
    if ($ClusterInfo.nodePools -and $ClusterInfo.nodePools.Count -gt 0) {
        $machineType = $ClusterInfo.nodePools[0].config.machineType
    }
    
    # Rough cost estimates (varies by region/machine type)
    $controlPlaneCost = 0.10
    $nodeCostPerHour = switch -Regex ($machineType) {
        "e2-micro" { 0.006 }
        "e2-small" { 0.012 }
        "e2-medium" { 0.024 }  
        "n1-standard-1" { 0.048 }
        "n1-standard-2" { 0.095 }
        "n1-standard-4" { 0.190 }
        default { 0.048 }  # Default estimate
    }
    
    $totalNodeCost = $nodeCount * $nodeCostPerHour
    $totalCost = $controlPlaneCost + $totalNodeCost
    
    Write-Info "  • Control Plane: ~$controlPlaneCost/hour"
    Write-Info "  • Nodes ($nodeCount x $machineType): ~$totalNodeCost/hour"  
    Write-Info "  • Total Current: ~$totalCost/hour (~$($totalCost * 24 * 30)/month)"
    Write-Info ""
    Write-Info "  💡 After PAUSE: ~$controlPlaneCost/hour (~$($controlPlaneCost * 24 * 30)/month)"
    Write-Info "  💡 After DELETE: $0/hour (complete removal)"
}

# Main execution
function Main {
    Write-Info "🚀 GKE Cluster Cost Management Script"
    Write-Info "Cluster: $ClusterName | Project: $Project | Action: $Action"
    Write-Info ""
    
    Test-Prerequisites
    $clusterInfo = Get-ClusterInfo
    Show-CostEstimate -ClusterInfo $clusterInfo
    
    Write-Info ""
    
    switch ($Action.ToLower()) {
        "pause" {
            $state = Save-ClusterState
            Invoke-ClusterPause -ClusterState $state
        }
        "resume" {
            Invoke-ClusterResume
        }
        "delete" {
            # Save state before deletion (in case user changes mind)
            if (-not (Test-Path $StateFile)) {
                Save-ClusterState | Out-Null
            }
            Invoke-ClusterDelete
        }
        default {
            Write-Error "❌ Invalid action: $Action"
            exit 1
        }
    }
}

# Run main function
Main
# ⚠️  DEPRECATED: This is a backup of the manage.ps1 script
# ⚠️  Use manage.ps1 instead - it has been updated for AutoPilot compatibility
# ⚠️  This version contains node pool operations that don't work with AutoPilot clusters
#
# Cluster management script - check status, pause/resume, debug issues
# The most important one is "pause" - saves you money when not using the cluster

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('status', 'pause', 'resume', 'debug', 'logs')]
    [string]$Action,
    [string]$ProjectId = "",
    [string]$AppName = ""
)

# Figure out the project to work with
if (-not $ProjectId) {
    $ProjectId = $env:PROJECT_ID
    if (-not $ProjectId) {
        $ProjectId = (gcloud config get-value project).Trim()
    }
}

if (-not $ProjectId) {
    Write-Host "Need a project ID. Run setup.ps1 first or use -ProjectId"
    exit 1
}

$env:PROJECT_ID = $ProjectId
$env:ZONE = "us-central1-a"

Write-Host "Managing cluster in project: $env:PROJECT_ID"
Write-Host "Action: $Action"
Write-Host ""

gcloud config set project $env:PROJECT_ID

switch ($Action.ToLower()) {
    "status" {
        Write-Host "=== CLUSTER STATUS ==="
        
        # Cluster info
        Write-Host "`nCluster Information:"
        gcloud container clusters describe gke-turns-10-hackathon --zone=$env:ZONE --project=$env:PROJECT_ID --format="table(name,status,currentNodeCount,location)"
        
        # Node status
        Write-Host "`nNode Status:"
        kubectl get nodes -o wide
        
        # Application workloads
        Write-Host "`nApplication Workloads:"
        kubectl get pods,services -o wide
        
        # Cost estimation
        Write-Host "`n=== COST TRACKING ==="
        
        try {
            $nodeCount = (kubectl get nodes --no-headers 2>$null | Measure-Object).Count
            $runningPods = (kubectl get pods --field-selector=status.phase=Running --no-headers 2>$null | Measure-Object).Count
            
            # More accurate pricing for GKE
            $hourlyPerNode = 0.048  # e2-standard-2 in us-central1
            $controlPlaneHourly = 0.10  # GKE control plane
            $currentHourly = ($nodeCount * $hourlyPerNode) + $controlPlaneHourly
            $dailyEstimate = $currentHourly * 24
            $monthlyEstimate = $dailyEstimate * 30
            
            Write-Host "Cluster Status:"
            Write-Host "  Active nodes: $nodeCount"
            Write-Host "  Running pods: $runningPods"
            
            if ($nodeCount -eq 0) {
                Write-Host "  Status: PAUSED ⏸️" -ForegroundColor Cyan
                Write-Host "  💰 Control plane only: `$0.10/hour" -ForegroundColor Green
                Write-Host "  💰 Daily cost: `$2.40" -ForegroundColor Green
                Write-Host "  💰 Monthly estimate: `$72.00" -ForegroundColor Green
            } else {
                Write-Host "  Status: ACTIVE 🟢" -ForegroundColor Green
                Write-Host "  💰 Hourly cost: `$$($currentHourly.ToString('F2'))" -ForegroundColor $(if ($currentHourly -gt 2) { 'Yellow' } else { 'Green' })
                Write-Host "  💰 Daily estimate: `$$($dailyEstimate.ToString('F2'))" -ForegroundColor $(if ($dailyEstimate -gt 48) { 'Yellow' } else { 'Green' })
                Write-Host "  💰 Monthly estimate: `$$($monthlyEstimate.ToString('F2'))" -ForegroundColor $(if ($monthlyEstimate -gt 100) { 'Red' } elseif ($monthlyEstimate -gt 50) { 'Yellow' } else { 'Green' })
            }
            
            # Cost warnings
            if ($nodeCount -gt 0) {
                if ($monthlyEstimate -gt 100) {
                    Write-Host ""
                    Write-Host "⚠️  HIGH COST WARNING!" -ForegroundColor Red
                    Write-Host "   Consider pausing the cluster when not in use" -ForegroundColor Red
                    Write-Host "   Run: .\manage.ps1 -Action pause" -ForegroundColor Red
                } elseif ($monthlyEstimate -gt 50) {
                    Write-Host ""
                    Write-Host "💡 Cost optimization tip:" -ForegroundColor Yellow
                    Write-Host "   Pause cluster when not developing: .\manage.ps1 -Action pause" -ForegroundColor Yellow
                }
            } else {
                Write-Host ""
                Write-Host "✅ Cluster is paused - costs minimized!" -ForegroundColor Green
                Write-Host "   To resume: .\manage.ps1 -Action resume" -ForegroundColor Gray
            }
            
        } catch {
            Write-Host "Error calculating costs: $_" -ForegroundColor Red
            Write-Host "Unable to determine cluster status" -ForegroundColor Red
        }
    }
    
    "pause" {
        Write-Host "=== PAUSING CLUSTER ==="
        Write-Warning "This will scale down all resources to minimize costs"
        
        $confirm = Read-Host "Are you sure you want to pause the cluster? (yes/no)"
        if ($confirm -ne "yes") {
            Write-Host "Operation cancelled"
            return
        }
        
        try {
            # Scale deployments to 0
            Write-Host "Scaling deployments to 0 replicas..."
            $deployments = kubectl get deployments -o name 2>$null
            if ($deployments) {
                foreach ($deployment in $deployments) {
                    if ($deployment.Trim()) {
                        Write-Host "  Scaling $deployment to 0..."
                        kubectl scale $deployment --replicas=0 --timeout=60s
                        if ($LASTEXITCODE -eq 0) {
                            Write-Host "  ✓ Scaled $deployment to 0" -ForegroundColor Green
                        } else {
                            Write-Host "  ⚠ Failed to scale $deployment" -ForegroundColor Yellow
                        }
                    }
                }
            } else {
                Write-Host "  No deployments found to scale"
            }
            
            # Wait for pods to terminate
            Write-Host "Waiting for pods to terminate..."
            $timeout = 120
            $elapsed = 0
            do {
                $runningPods = (kubectl get pods --field-selector=status.phase=Running --no-headers 2>$null | Measure-Object).Count
                if ($runningPods -eq 0) {
                    Write-Host "  ✓ All pods terminated" -ForegroundColor Green
                    break
                }
                Start-Sleep -Seconds 5
                $elapsed += 5
                Write-Host "  Waiting... $runningPods pods still running"
            } while ($elapsed -lt $timeout)
            
            # Scale node pool to 0
            Write-Host "Scaling node pool to 0..."
            $result = gcloud container clusters resize gke-turns-10-hackathon --node-pool=gke-turns-10-nodes --num-nodes=0 --zone=$env:ZONE --project=$env:PROJECT_ID --quiet 2>&1
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  ✓ Node pool resize initiated" -ForegroundColor Green
                
                # Wait for nodes to be removed
                Write-Host "Waiting for nodes to be removed..."
                $timeout = 300  # 5 minutes
                $elapsed = 0
                do {
                    $nodeCount = (kubectl get nodes --no-headers 2>$null | Measure-Object).Count
                    if ($nodeCount -eq 0) {
                        Write-Host "  ✓ All nodes removed" -ForegroundColor Green
                        break
                    }
                    Start-Sleep -Seconds 10
                    $elapsed += 10
                    Write-Host "  Waiting... $nodeCount nodes still present"
                } while ($elapsed -lt $timeout)
                
                if ($nodeCount -gt 0) {
                    Write-Host "  ⚠ Timeout waiting for nodes to be removed, but resize was initiated" -ForegroundColor Yellow
                }
            } else {
                Write-Host "  ✗ Failed to resize node pool: $result" -ForegroundColor Red
                Write-Host "  You may need to manually scale the node pool in the GCP console"
                return
            }
            
            Write-Host ""
            Write-Host "✓ Cluster paused successfully" -ForegroundColor Green
            Write-Host "Estimated cost: ~`$0.10/hour (control plane only)" -ForegroundColor Cyan
            Write-Host "📊 To verify pause status, run: .\manage.ps1 -Action status" -ForegroundColor Gray
            
        } catch {
            Write-Host "✗ Error during pause operation: $_" -ForegroundColor Red
            Write-Host "You may need to complete the pause manually in the GCP console"
        }
    }
    
    "resume" {
        Write-Host "=== RESUMING CLUSTER ==="
        
        $confirm = Read-Host "Resume cluster to normal operation? (yes/no)"
        if ($confirm -ne "yes") {
            Write-Host "Operation cancelled"
            return
        }
        
        try {
            # Scale node pool back up
            Write-Host "Scaling node pool to 1 node..."
            $result = gcloud container clusters resize gke-turns-10-hackathon --node-pool=gke-turns-10-nodes --num-nodes=1 --zone=$env:ZONE --project=$env:PROJECT_ID --quiet 2>&1
            
            if ($LASTEXITCODE -ne 0) {
                Write-Host "✗ Failed to resize node pool: $result" -ForegroundColor Red
                return
            }
            
            Write-Host "  ✓ Node pool resize initiated" -ForegroundColor Green
            
            # Wait for nodes to be ready
            Write-Host "Waiting for nodes to be ready..."
            $timeout = 300  # 5 minutes
            $elapsed = 0
            do {
                $readyNodes = (kubectl get nodes --field-selector=spec.unschedulable!=true --no-headers 2>$null | Where-Object { $_ -match "\sReady\s" } | Measure-Object).Count
                if ($readyNodes -ge 1) {
                    Write-Host "  ✓ Node is ready" -ForegroundColor Green
                    break
                }
                Start-Sleep -Seconds 10
                $elapsed += 10
                Write-Host "  Waiting for node to be ready... ($elapsed/$timeout seconds)"
            } while ($elapsed -lt $timeout)
            
            if ($readyNodes -eq 0) {
                Write-Host "  ⚠ Timeout waiting for nodes to be ready" -ForegroundColor Yellow
                Write-Host "  Proceeding anyway, deployments may take longer to start"
            }
            
            # Scale deployments back up with better error handling
            Write-Host "Scaling deployments back up..."
            
            $deployments = @("mcp-server", "adk-agents", "streamlit-ui")
            foreach ($deployment in $deployments) {
                Write-Host "  Scaling deployment/$deployment to 1 replica..."
                kubectl scale deployment/$deployment --replicas=1 --timeout=60s 2>$null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  ✓ Scaled deployment/$deployment" -ForegroundColor Green
                } else {
                    Write-Host "  ⚠ Failed to scale deployment/$deployment (may not exist)" -ForegroundColor Yellow
                }
            }
            
            # Wait for pods to be ready
            Write-Host "Waiting for pods to be ready..."
            $timeout = 180  # 3 minutes
            $elapsed = 0
            do {
                $readyPods = (kubectl get pods --field-selector=status.phase=Running --no-headers 2>$null | Measure-Object).Count
                $totalPods = (kubectl get pods --no-headers 2>$null | Where-Object { $_ -notmatch "Completed|Succeeded" } | Measure-Object).Count
                
                if ($readyPods -gt 0 -and $readyPods -eq $totalPods) {
                    Write-Host "  ✓ All pods are running ($readyPods/$totalPods)" -ForegroundColor Green
                    break
                }
                Start-Sleep -Seconds 10
                $elapsed += 10
                Write-Host "  Waiting for pods... ($readyPods/$totalPods running)"
            } while ($elapsed -lt $timeout)
            
            Write-Host ""
            Write-Host "✓ Cluster resumed successfully" -ForegroundColor Green
            Write-Host "🚀 Applications should be available shortly" -ForegroundColor Cyan
            Write-Host "📊 Run .\manage.ps1 -Action status to verify all services are running" -ForegroundColor Gray
            
        } catch {
            Write-Host "✗ Error during resume operation: $_" -ForegroundColor Red
            Write-Host "You may need to complete the resume manually in the GCP console"
        }
    }
    
    "debug" {
        Write-Host "=== DEBUGGING CLUSTER ==="
        
        try {
            # Cluster basic info
            Write-Host "`nCluster Overview:"
            $nodeCount = (kubectl get nodes --no-headers 2>$null | Measure-Object).Count
            $podCount = (kubectl get pods --no-headers 2>$null | Measure-Object).Count
            $runningPods = (kubectl get pods --field-selector=status.phase=Running --no-headers 2>$null | Measure-Object).Count
            
            Write-Host "  Nodes: $nodeCount"
            Write-Host "  Total Pods: $podCount"
            Write-Host "  Running Pods: $runningPods"
            
            if ($nodeCount -eq 0) {
                Write-Host "  ⚠️ No nodes available - cluster may be paused" -ForegroundColor Yellow
                Write-Host "  Run: .\manage.ps1 -Action resume" -ForegroundColor Gray
                return
            }
            
            # Pod status
            Write-Host "`nPod Status:"
            kubectl get pods -o wide --sort-by=.metadata.name
            
            # Services status
            Write-Host "`nServices:"
            kubectl get services -o wide
            
            # Recent events (more detailed)
            Write-Host "`nRecent Events (Last 30):"
            kubectl get events --sort-by=.metadata.creationTimestamp --field-selector type!=Normal | Select-Object -Last 30
            
            # Node resource usage
            Write-Host "`nNode Resource Usage:"
            $topResult = kubectl top nodes 2>$null
            if ($LASTEXITCODE -eq 0) {
                $topResult
            } else {
                Write-Host "  Metrics server not available"
            }
            
            # Pod resource usage
            Write-Host "`nPod Resource Usage:"
            $topResult = kubectl top pods 2>$null
            if ($LASTEXITCODE -eq 0) {
                $topResult
            } else {
                Write-Host "  Metrics server not available"
            }
            
            # Describe problematic pods
            $failedPods = kubectl get pods --field-selector=status.phase!=Running --no-headers 2>$null
            if ($failedPods) {
                Write-Host "`n=== PROBLEMATIC PODS ===" -ForegroundColor Red
                foreach ($pod in $failedPods) {
                    if ($pod.Trim()) {
                        $podName = ($pod -split "\s+")[0]
                        $podStatus = ($pod -split "\s+")[2]
                        Write-Host "`n--- $podName (Status: $podStatus) ---" -ForegroundColor Yellow
                        kubectl describe pod $podName | Select-Object -First 50
                        Write-Host "`nRecent logs for $podName:" -ForegroundColor Yellow
                        kubectl logs $podName --tail=10 2>$null
                    }
                }
            } else {
                Write-Host "`n✅ No problematic pods found" -ForegroundColor Green
            }
            
            # Deployment status
            Write-Host "`n=== DEPLOYMENT STATUS ===" 
            kubectl get deployments -o wide
            
            # Summary and recommendations
            Write-Host "`n=== RECOMMENDATIONS ===" -ForegroundColor Cyan
            if ($runningPods -eq 0 -and $nodeCount -gt 0) {
                Write-Host "• No pods running but nodes available - try resuming deployments"
                Write-Host "  kubectl scale deployment/mcp-server --replicas=1"
                Write-Host "  kubectl scale deployment/adk-agents --replicas=1" 
                Write-Host "  kubectl scale deployment/streamlit-ui --replicas=1"
            } elseif ($podCount -ne $runningPods) {
                Write-Host "• Some pods are not running - check events and pod logs above"
            } else {
                Write-Host "• Cluster appears healthy"
            }
            
        } catch {
            Write-Host "Error during debug: $_" -ForegroundColor Red
        }
    }
    
    "logs" {
        if ($AppName) {
            Write-Host "=== LOGS FOR $AppName ==="
            kubectl logs -l app=$AppName --tail=50 -f
        } else {
            Write-Host "=== APPLICATION LOGS ==="
            Write-Host "Available applications:"
            kubectl get deployments -o name
            Write-Host ""
            Write-Host "Usage: .\manage.ps1 -Action logs -AppName <app-name>"
            Write-Host "Example: .\manage.ps1 -Action logs -AppName mcp-server"
        }
    }
}

Write-Host ""
Write-Host "Available management commands:"
Write-Host "  .\manage.ps1 -Action status     # Show cluster status"
Write-Host "  .\manage.ps1 -Action pause      # Pause cluster to save costs"
Write-Host "  .\manage.ps1 -Action resume     # Resume paused cluster"
Write-Host "  .\manage.ps1 -Action debug      # Debug cluster issues"
Write-Host "  .\manage.ps1 -Action logs -AppName <app>  # View application logs"
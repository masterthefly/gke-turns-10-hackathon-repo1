#!/bin/bash
# Cluster management script - check status, pause/resume, debug issues
# The most important one is "pause" - saves you money when not using the cluster

# Default values
ACTION=""
PROJECT_ID=""
APP_NAME=""

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
    -a|--action|status|pause|resume|debug|logs)
      if [[ "$1" =~ ^(status|pause|resume|debug|logs)$ ]]; then
        ACTION="$1"
      else
        ACTION="$2"
        shift
      fi
      shift
      ;;
    -p|--project-id)
      PROJECT_ID="$2"
      shift 2
      ;;
    -n|--app-name)
      APP_NAME="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 ACTION [OPTIONS]"
      echo ""
      echo "Actions:"
      echo "  status              Show cluster status and cost information"
      echo "  pause               Pause cluster to minimize costs"
      echo "  resume              Resume paused cluster"
      echo "  debug               Debug cluster issues"
      echo "  logs                Show application logs"
      echo ""
      echo "Options:"
      echo "  -p, --project-id PROJECT_ID     GCP Project ID"
      echo "  -n, --app-name APP_NAME         Application name for logs"
      echo "  -h, --help                      Show this help message"
      echo ""
      echo "Examples:"
      echo "  $0 status"
      echo "  $0 pause -p my-project"
      echo "  $0 logs -n mcp-server"
      exit 0
      ;;
    *)
      echo "Unknown option $1"
      exit 1
      ;;
  esac
done

# Validate action
if [[ -z "$ACTION" ]]; then
    echo "Error: Action is required"
    echo "Available actions: status, pause, resume, debug, logs"
    echo "Use -h or --help for more information"
    exit 1
fi

if [[ ! "$ACTION" =~ ^(status|pause|resume|debug|logs)$ ]]; then
    echo "Error: Invalid action '$ACTION'"
    echo "Available actions: status, pause, resume, debug, logs"
    exit 1
fi

# Figure out the project to work with
if [[ -z "$PROJECT_ID" ]]; then
    PROJECT_ID="$PROJECT_ID"
    if [[ -z "$PROJECT_ID" ]]; then
        PROJECT_ID=$(gcloud config get-value project 2>/dev/null | tr -d '\n')
    fi
fi

if [[ -z "$PROJECT_ID" ]]; then
    echo "Need a project ID. Run setup.sh first or use -p/--project-id"
    exit 1
fi

export PROJECT_ID="$PROJECT_ID"
export REGION="us-central1"

echo "Managing cluster in project: $PROJECT_ID"
echo "Action: $ACTION"
echo ""

gcloud config set project "$PROJECT_ID"

case "${ACTION,,}" in
    "status")
        echo "=== CLUSTER STATUS ==="
        
        # Cluster info
        echo -e "\nCluster Information:"
        gcloud container clusters describe gke-turns-10-hackathon --region="$REGION" --project="$PROJECT_ID" --format="table(name,status,currentNodeCount,location)"
        
        # Node status
        echo -e "\nNode Status:"
        kubectl get nodes -o wide
        
        # Application workloads
        echo -e "\nApplication Workloads:"
        kubectl get pods,services -o wide
        
        # Cost estimation
        echo -e "\n=== COST TRACKING ==="
        
        {
            node_count=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
            running_pods=$(kubectl get pods --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
            
            # More accurate pricing for GKE
            hourly_per_node=0.048  # e2-standard-2 in us-central1
            control_plane_hourly=0.10  # GKE control plane
            current_hourly=$(echo "$node_count * $hourly_per_node + $control_plane_hourly" | bc -l)
            daily_estimate=$(echo "$current_hourly * 24" | bc -l)
            monthly_estimate=$(echo "$daily_estimate * 30" | bc -l)
            
            echo "Cluster Status:"
            echo "  Active nodes: $node_count"
            echo "  Running pods: $running_pods"
            
            if [[ $node_count -eq 0 ]]; then
                echo -e "${CYAN}  Status: PAUSED${NC}"
                echo -e "${GREEN}  Control plane only: \$0.10/hour${NC}"
                echo -e "${GREEN}  Daily cost: \$2.40${NC}"
                echo -e "${GREEN}  Monthly estimate: \$72.00${NC}"
            else
                echo -e "${GREEN}  Status: ACTIVE${NC}"
                printf "  Hourly cost: \$%.2f\n" "$current_hourly"
                printf "  Daily estimate: \$%.2f\n" "$daily_estimate"
                printf "  Monthly estimate: \$%.2f\n" "$monthly_estimate"
                
                # Color coding for costs
                if (( $(echo "$current_hourly > 2" | bc -l) )); then
                    echo -e "${YELLOW}  (Higher cost)${NC}"
                fi
            fi
            
            # Cost warnings
            if [[ $node_count -gt 0 ]]; then
                if (( $(echo "$monthly_estimate > 100" | bc -l) )); then
                    echo ""
                    echo -e "${RED}HIGH COST WARNING!${NC}"
                    echo -e "${RED}   Consider pausing the cluster when not in use${NC}"
                    echo -e "${RED}   Run: ./manage.sh pause${NC}"
                elif (( $(echo "$monthly_estimate > 50" | bc -l) )); then
                    echo ""
                    echo -e "${YELLOW}Cost optimization tip:${NC}"
                    echo -e "${YELLOW}   Pause cluster when not developing: ./manage.sh pause${NC}"
                fi
            else
                echo ""
                echo -e "${GREEN}Cluster is paused - costs minimized!${NC}"
                echo -e "${GRAY}   To resume: ./manage.sh resume${NC}"
            fi
            
        } || {
            echo -e "${RED}Error calculating costs${NC}"
            echo -e "${RED}Unable to determine cluster status${NC}"
        }
        ;;
    
    "pause")
        echo "=== PAUSING AUTOPILOT CLUSTER ==="
        echo -e "${YELLOW}This will scale down all deployments to minimize costs${NC}"
        echo "Note: AutoPilot clusters automatically scale nodes based on workload demand"
        
        read -p "Are you sure you want to pause the cluster? (yes/no): " confirm
        if [[ "$confirm" != "yes" ]]; then
            echo "Operation cancelled"
            exit 0
        fi
        
        {
            # Scale deployments to 0
            echo "Scaling deployments to 0 replicas..."
            deployments=$(kubectl get deployments -o name 2>/dev/null)
            if [[ -n "$deployments" ]]; then
                while read -r deployment; do
                    if [[ -n "$deployment" ]]; then
                        echo "  Scaling $deployment to 0..."
                        if kubectl scale "$deployment" --replicas=0 --timeout=60s; then
                            echo -e "${GREEN}  Scaled $deployment to 0${NC}"
                        else
                            echo -e "${YELLOW}  Failed to scale $deployment${NC}"
                        fi
                    fi
                done <<< "$deployments"
            else
                echo "  No deployments found to scale"
            fi
            
            # Wait for pods to terminate
            echo "Waiting for pods to terminate..."
            timeout=120
            elapsed=0
            while [[ $elapsed -lt $timeout ]]; do
                running_pods=$(kubectl get pods --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
                if [[ $running_pods -eq 0 ]]; then
                    echo -e "${GREEN}  All pods terminated${NC}"
                    break
                fi
                sleep 5
                elapsed=$((elapsed + 5))
                echo "  Waiting... $running_pods pods still running"
            done
            
            # AutoPilot will automatically scale down nodes when no workloads are running
            echo "Waiting for AutoPilot to scale down nodes..."
            timeout=300  # 5 minutes
            elapsed=0
            while [[ $elapsed -lt $timeout ]]; do
                node_count=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
                if [[ $node_count -eq 0 ]]; then
                    echo -e "${GREEN}  All nodes scaled down by AutoPilot${NC}"
                    break
                fi
                sleep 15
                elapsed=$((elapsed + 15))
                echo "  Waiting for AutoPilot to scale down... $node_count nodes still present"
            done
            
            echo ""
            echo -e "${GREEN}AutoPilot cluster paused successfully${NC}"
            echo -e "${CYAN}AutoPilot will automatically manage node scaling based on workload demand${NC}"
            echo -e "${CYAN}Estimated cost: ~\$0.10/hour (control plane only when no workloads)${NC}"
            echo -e "${GRAY}To verify pause status, run: ./manage.sh status${NC}"
            
        } || {
            echo -e "${RED}Error during pause operation${NC}"
            echo "AutoPilot clusters manage nodes automatically, so manual intervention may not be needed"
        }
        ;;
    
    "resume")
        echo "=== RESUMING AUTOPILOT CLUSTER ==="
        echo "Note: AutoPilot will automatically provision nodes as deployments are scaled up"
        
        read -p "Resume cluster to normal operation? (yes/no): " confirm
        if [[ "$confirm" != "yes" ]]; then
            echo "Operation cancelled"
            exit 0
        fi
        
        {
            # Scale deployments back up with better error handling
            echo "Scaling deployments back up..."
            echo "AutoPilot will automatically provision nodes as needed"
            
            deployments=("mcp-server" "adk-agents" "streamlit-ui")
            for deployment in "${deployments[@]}"; do
                echo "  Scaling deployment/$deployment to 1 replica..."
                if kubectl scale deployment/"$deployment" --replicas=1 --timeout=60s 2>/dev/null; then
                    echo -e "${GREEN}  Scaled deployment/$deployment${NC}"
                else
                    echo -e "${YELLOW}  Failed to scale deployment/$deployment (may not exist)${NC}"
                fi
            done
            
            # Wait for AutoPilot to provision nodes
            echo "Waiting for AutoPilot to provision nodes..."
            timeout=300  # 5 minutes for AutoPilot to provision nodes
            elapsed=0
            ready_nodes=0
            while [[ $elapsed -lt $timeout ]]; do
                ready_nodes=$(kubectl get nodes --field-selector=spec.unschedulable!=true --no-headers 2>/dev/null | grep -c "Ready")
                if [[ $ready_nodes -ge 1 ]]; then
                    echo -e "${GREEN}  AutoPilot provisioned $ready_nodes node(s)${NC}"
                    break
                fi
                sleep 15
                elapsed=$((elapsed + 15))
                echo "  Waiting for AutoPilot to provision nodes... ($elapsed/$timeout seconds)"
            done
            
            if [[ $ready_nodes -eq 0 ]]; then
                echo -e "${YELLOW}  AutoPilot is still provisioning nodes, deployments may take longer to start${NC}"
            fi
            
            # Wait for pods to be ready
            echo "Waiting for pods to be ready..."
            timeout=300  # 5 minutes for pods to start (AutoPilot needs more time)
            elapsed=0
            while [[ $elapsed -lt $timeout ]]; do
                ready_pods=$(kubectl get pods --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
                total_pods=$(kubectl get pods --no-headers 2>/dev/null | grep -v -E "Completed|Succeeded" | wc -l)
                
                if [[ $ready_pods -gt 0 && $ready_pods -eq $total_pods ]]; then
                    echo -e "${GREEN}  All pods are running ($ready_pods/$total_pods)${NC}"
                    break
                fi
                sleep 15
                elapsed=$((elapsed + 15))
                echo "  Waiting for pods... ($ready_pods/$total_pods running)"
            done
            
            echo ""
            echo -e "${GREEN}AutoPilot cluster resumed successfully${NC}"
            echo -e "${CYAN}AutoPilot has automatically managed node provisioning${NC}"
            echo -e "${CYAN}Applications should be available shortly${NC}"
            echo -e "${GRAY}Run ./manage.sh status to verify all services are running${NC}"
            
        } || {
            echo -e "${RED}Error during resume operation${NC}"
            echo "AutoPilot clusters manage nodes automatically, check pod status with kubectl"
        }
        ;;
    
    "debug")
        echo "=== DEBUGGING CLUSTER ==="
        
        {
            # Cluster basic info
            echo -e "\nCluster Overview:"
            node_count=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
            pod_count=$(kubectl get pods --no-headers 2>/dev/null | wc -l)
            running_pods=$(kubectl get pods --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
            
            echo "  Nodes: $node_count"
            echo "  Total Pods: $pod_count"
            echo "  Running Pods: $running_pods"
            
            if [[ $node_count -eq 0 ]]; then
                echo -e "${YELLOW}  No nodes available - cluster may be paused${NC}"
                echo -e "${GRAY}  Run: ./manage.sh resume${NC}"
                exit 0
            fi
            
            # Pod status
            echo -e "\nPod Status:"
            kubectl get pods -o wide --sort-by=.metadata.name
            
            # Services status
            echo -e "\nServices:"
            kubectl get services -o wide
            
            # Recent events (more detailed)
            echo -e "\nRecent Events (Last 30):"
            kubectl get events --sort-by=.metadata.creationTimestamp --field-selector type!=Normal | tail -30
            
            # Node resource usage
            echo -e "\nNode Resource Usage:"
            if kubectl top nodes 2>/dev/null; then
                : # Command succeeded
            else
                echo "  Metrics server not available"
            fi
            
            # Pod resource usage
            echo -e "\nPod Resource Usage:"
            if kubectl top pods 2>/dev/null; then
                : # Command succeeded
            else
                echo "  Metrics server not available"
            fi
            
            # Describe problematic pods
            failed_pods=$(kubectl get pods --field-selector=status.phase!=Running --no-headers 2>/dev/null)
            if [[ -n "$failed_pods" ]]; then
                echo -e "\n${RED}=== PROBLEMATIC PODS ===${NC}"
                while IFS= read -r pod_line; do
                    if [[ -n "$pod_line" ]]; then
                        pod_name=$(echo "$pod_line" | awk '{print $1}')
                        pod_status=$(echo "$pod_line" | awk '{print $3}')
                        echo -e "\n${YELLOW}--- $pod_name (Status: $pod_status) ---${NC}"
                        kubectl describe pod "$pod_name" | head -50
                        echo -e "\n${YELLOW}Recent logs for $pod_name:${NC}"
                        kubectl logs "$pod_name" --tail=10 2>/dev/null
                    fi
                done <<< "$failed_pods"
            else
                echo -e "\n${GREEN}No problematic pods found${NC}"
            fi
            
            # Deployment status
            echo -e "\n=== DEPLOYMENT STATUS ===" 
            kubectl get deployments -o wide
            
            # Summary and recommendations
            echo -e "\n${CYAN}=== RECOMMENDATIONS ===${NC}"
            if [[ $running_pods -eq 0 && $node_count -gt 0 ]]; then
                echo "• No pods running but nodes available - try resuming deployments"
                echo "  kubectl scale deployment/mcp-server --replicas=1"
                echo "  kubectl scale deployment/adk-agents --replicas=1" 
                echo "  kubectl scale deployment/streamlit-ui --replicas=1"
            elif [[ $pod_count -ne $running_pods ]]; then
                echo "• Some pods are not running - check events and pod logs above"
            else
                echo "• Cluster appears healthy"
            fi
            
        } || {
            echo -e "${RED}Error during debug${NC}"
        }
        ;;
    
    "logs")
        if [[ -n "$APP_NAME" ]]; then
            echo "=== LOGS FOR $APP_NAME ==="
            kubectl logs -l app="$APP_NAME" --tail=50 -f
        else
            echo "=== APPLICATION LOGS ==="
            echo "Available applications:"
            kubectl get deployments -o name
            echo ""
            echo "Usage: ./manage.sh logs -n <app-name>"
            echo "Example: ./manage.sh logs -n mcp-server"
        fi
        ;;
esac

echo ""
echo "Available management commands:"
echo "  ./manage.sh status              # Show cluster status"
echo "  ./manage.sh pause               # Pause cluster to save costs"
echo "  ./manage.sh resume              # Resume paused cluster"
echo "  ./manage.sh debug               # Debug cluster issues"
echo "  ./manage.sh logs -n <app>       # View application logs"
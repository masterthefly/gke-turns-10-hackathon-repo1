# GKE Hackathon Project

This is my cleaned up GKE environment for the Turns 10 hackathon. I got tired of having a dozen scattered PowerShell scripts everywhere, so I consolidated everything down to just 4 essential scripts that actually work.

## What This Is

A ready-to-deploy GKE setup that includes:
- Infrastructure deployment via Terraform
- Multiple applications (MCP server, ADK agents, Streamlit UI)
- Cost management features (super important!)
- Proper monitoring and debugging tools

The original setup was a mess with like 10+ different scripts doing overlapping things. This version is clean and actually works.

## Quick Setup

You need these installed first:
- Google Cloud SDK 
- Terraform
- Docker
- kubectl
- PowerShell

Then just run these commands:

```powershell
# Create project and set everything up

# Check if everything is working
.\manage.ps1 -Action status

# Clean up when done
.\teardown.ps1
```

That's it. Takes about 20-30 minutes total.

## The Scripts

**setup.ps1** - Does the boring GCP project setup stuff. Creates project, enables APIs, sets up billing, configures authentication. Run this once.

**deploy.ps1** - The main deployment script. Runs Terraform to create the cluster, builds Docker images, deploys everything to Kubernetes. This is where the magic happens.

**manage.ps1** - Swiss army knife for cluster management. Check status, view logs, debug issues, and most importantly - pause the cluster to save money.

**teardown.ps1** - Nuclear option. Destroys everything. Use when you're completely done.

## Cost Management (READ THIS)

This is the most important part. GKE costs money - about $40/month if you leave it running.

The manage script has a pause feature that scales everything down to zero nodes. This drops your cost to like $3/month (just the control plane). 

```powershell
# Before you go to bed or stop working
.\manage.ps1 -Action pause

# When you want to work again  
.\manage.ps1 -Action resume
```

Don't learn this the hard way after getting a $120 bill one month.

## What Gets Deployed

**Infrastructure:**
- GKE cluster with e2-standard-2 nodes (8GB RAM each)
- Artifact Registry for Docker images
- Service accounts with proper permissions
- All the networking stuff

**Applications:**
- MCP Server - Model Context Protocol implementation
- ADK Agents - Google's Agent Development Kit
- Streamlit UI - Web interface you can actually use
- Online Boutique - Google's demo app (optional)

The Streamlit UI gets an external LoadBalancer IP so you can access it from your browser.

## Finding Your Billing Account ID

Go to Google Cloud Console > Billing, click your billing account, copy the Account ID. It looks like "XXXXXX-YYYYYY-ZZZZZZ".

## Common Issues I Fixed

**Pods not starting** - Original setup used tiny e2-micro nodes with 1GB RAM. Pods couldn't schedule. Fixed by using e2-standard-2 with 8GB RAM.

**Image pull failures** - Docker auth gets messed up sometimes. The deploy script reconfigures it automatically.

**LoadBalancer stuck** - Sometimes takes 5-10 minutes to get an external IP. Be patient or use port-forward as backup.

**Terraform state issues** - I reset the terraform directory so you get a clean start.

## Monitoring Commands

```powershell
# See everything that's running and what it costs
.\manage.ps1 -Action status

# Debug when things break
.\manage.ps1 -Action debug  

# Watch application logs
.\manage.ps1 -Action logs -AppName streamlit-ui

# Basic kubectl commands
kubectl get pods
kubectl get services
kubectl top nodes
```

## Directory Structure

```
gke-turns-10-hackathon/
├── setup.ps1              # Initial GCP setup
├── deploy.ps1             # Main deployment 
├── manage.ps1             # Cluster management
├── teardown.ps1           # Cleanup everything
├── terraform-gke/        # Infrastructure code
├── mcp-server/           # MCP server app
├── adk-agents/           # ADK agents app  
├── streamlit-ui/         # Web interface
└── microservices-demo/   # Google's demo 
```

## Troubleshooting

**"Insufficient CPU/Memory"** - The new nodes should fix this. If not, check `kubectl top nodes`.

**"Image not found"** - Docker push probably failed. Check the deploy script output.

**"LoadBalancer pending"** - Just wait. Or try `kubectl port-forward service/streamlit-ui-service 8501:8501` and use localhost.

**Billing issues** - Make sure your billing account ID is correct and has a valid payment method.

**API not enabled** - The setup script should handle this, but you can manually enable APIs in the console.

## Cost Breakdown

| State | Monthly Cost | Notes |
|-------|-------------|-------|
| Running (1 node) | ~$40 | Normal development |
| Paused (0 nodes) | ~$3 | Just control plane |  
| Deleted | $0 | Nuclear option |

Always pause when not using it. Seriously.

## Getting Help

The manage script has built-in debugging:
```powershell
.\manage.ps1 -Action debug
```

This shows pod status, events, resource usage, and other useful info.

You can also check the Google Cloud Console:
- [Kubernetes clusters](https://console.cloud.google.com/kubernetes)
- [Billing dashboard](https://console.cloud.google.com/billing)

## Success Checklist

After running the deploy script, you should have:
- Cluster showing as running in GCP console
- All pods in "Running" state: `kubectl get pods`
- Streamlit UI accessible via external IP: `kubectl get services`
- No errors in: `.\manage.ps1 -Action status`

If something's not working, run the debug command and check the output.

## Testing Your Deployed Application

Once everything is deployed successfully, here's how to actually test it:

### 1. Get the External IP
```powershell
kubectl get services
```
Look for `streamlit-ui-service` and wait for it to get an `EXTERNAL-IP`. Takes about 2-5 minutes.

### 2. Access the Web Interface
Open your browser and go to: `http://YOUR_EXTERNAL_IP`

You should see the "AI Shopping Concierge" interface.

### 3. Test Basic Functionality

**Search for products:**
- Try searching for "red shoes" or "kitchen tools"  
- Should show products from the Online Boutique catalog

**Chat with the AI:**
- Ask things like "I need running shoes for jogging"
- "Show me something for cooking"
- "What's good for a birthday gift?"

### 4. Test Semantic Search Features

The ADK agents include semantic search that understands context, not just keywords:

**Try these semantic queries:**
- "Something for a workout" (should find athletic gear)
- "Gift for someone who loves to cook" (should find kitchen items)
- "Professional attire" (should find business clothes)
- "Items for staying warm" (should find jackets, etc.)

**Check if semantic search is working:**
- Go to `http://YOUR_EXTERNAL_IP/adk-agents/health` 
- Should show `"semantic_search": "enabled"`

### 5. Test the MCP Server Directly

**List all products:**
```bash
curl http://YOUR_EXTERNAL_IP/mcp-server/list_products
```

**Search products:**
```bash
curl -X POST http://YOUR_EXTERNAL_IP/mcp-server/search_products \
  -H "Content-Type: application/json" \
  -d '{"query": "shoes"}'
```

### 6. Monitor Resource Usage

Check if everything is running smoothly:
```powershell
.\manage.ps1 -Action status
```

Watch the logs:
```powershell
.\manage.ps1 -Action logs -AppName streamlit-ui
.\manage.ps1 -Action logs -AppName adk-agents
.\manage.ps1 -Action logs -AppName mcp-server
```

### 7. Port Forward (If LoadBalancer Doesn't Work)

Sometimes the external IP takes forever. Use port-forward as backup:

```bash
# For main UI
kubectl port-forward service/streamlit-ui-service 8501:8501

# For ADK agents directly  
kubectl port-forward service/adk-agents-service 8000:8000

# For MCP server directly
kubectl port-forward service/mcp-server-service 8080:8080
```

Then access at:
- Main UI: http://localhost:8501
- ADK Agents: http://localhost:8000
- MCP Server: http://localhost:8080

### 8. What Should Work

If everything deployed correctly:

** Web Interface:**
- Shopping assistant chat interface loads
- You can type messages and get responses
- Product search returns results from Online Boutique

** Semantic Search:**  
- Natural language queries work (not just exact keywords)
- ADK agents understand context and intent
- Similarity scoring shows relevant matches

** Integration:**
- Chat responses include actual products
- Product data flows from Online Boutique → MCP Server → ADK Agents → UI
- All services communicate with each other

### 9. Common Issues and Fixes

**"Service unavailable" errors:**
- Check if all pods are running: `kubectl get pods`
- Wait longer - services take time to start up

**No external IP:**
- Use port-forward instead
- Check LoadBalancer quota in Google Cloud Console

**Semantic search disabled:**
- Check ADK agents logs: `.\manage.ps1 -Action logs -AppName adk-agents`
- ML libraries might not have loaded properly

**Products not showing:**
- Make sure Online Boutique is deployed
- Check MCP server logs for connection errors

Remember to pause the cluster when you're done working to save money!

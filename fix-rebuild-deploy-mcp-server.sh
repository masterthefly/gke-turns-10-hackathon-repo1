cd mcp-server

# Update server.py with the fix above, then rebuild
PROJECT_ID=$(gcloud config get-value project)
MCP_IMAGE="us-central1-docker.pkg.dev/$PROJECT_ID/gke-turns-10-repo/mcp-server:fixed"

docker build -t $MCP_IMAGE .
docker push $MCP_IMAGE

# Update the deployment
kubectl set image deployment/mcp-server mcp-server=$MCP_IMAGE

# Wait for rollout
kubectl rollout status deployment/mcp-server

# Test the fix
kubectl exec deployment/mcp-server -- curl -s http://localhost:8080/list_products | head -20
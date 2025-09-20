output "cluster_name" {
  description = "GKE cluster name"
  value       = google_container_cluster.main.name
}

output "cluster_zone" {
  description = "GKE cluster zone"
  value       = google_container_cluster.main.location
}

output "cluster_endpoint" {
  description = "GKE cluster endpoint"
  value       = google_container_cluster.main.endpoint
  sensitive   = true
}

output "registry_url" {
  description = "Artifact Registry URL for pushing images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}"
}

output "service_account_email" {
  description = "Service account email for workload identity"
  value       = google_service_account.gke_sa.email
}

output "kubernetes_service_account" {
  description = "Kubernetes service account name"
  value       = kubernetes_service_account.ksa.metadata[0].name
}

# Node pool outputs not applicable in Autopilot mode
# GKE Autopilot automatically manages node provisioning and scaling

output "kubectl_connection_command" {
  description = "Command to connect kubectl to the cluster"
  value       = "gcloud container clusters get-credentials ${google_container_cluster.main.name} --zone ${var.zone} --project ${var.project_id}"
}

output "docker_push_command_example" {
  description = "Example command to push Docker images to the registry"
  value       = "docker push ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/your-image:tag"
}

output "monthly_cost_estimate" {
  description = "Estimated monthly cost for GKE Autopilot cluster"
  value       = "GKE Autopilot: Pay only for running pods (CPU/memory/storage). Typically 20-30% less than standard clusters with no node management overhead."
}

output "resource_recommendations" {
  description = "Recommendations for pod resource requests"
  value = {
    small_pod = {
      cpu_request    = "100m"
      memory_request = "128Mi"
      cpu_limit      = "200m" 
      memory_limit   = "256Mi"
    }
    medium_pod = {
      cpu_request    = "200m"
      memory_request = "256Mi"
      cpu_limit      = "500m"
      memory_limit   = "512Mi"
    }
    large_pod = {
      cpu_request    = "500m"
      memory_request = "512Mi" 
      cpu_limit      = "1000m"
      memory_limit   = "1Gi"
    }
  }
}

output "cluster_status_check_commands" {
  description = "Commands to check cluster and pod status"
  value = [
    "kubectl get nodes -o wide",
    "kubectl get pods --all-namespaces",
    "kubectl top nodes",
    "kubectl describe pod <pod-name>"
  ]
}
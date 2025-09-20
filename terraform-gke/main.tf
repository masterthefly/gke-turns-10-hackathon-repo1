terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# Add this after the google provider
data "google_client_config" "default" {}

provider "kubernetes" {
  host                   = "https://${google_container_cluster.main.endpoint}"
  token                  = data.google_client_config.default.access_token
  cluster_ca_certificate = base64decode(google_container_cluster.main.master_auth.0.cluster_ca_certificate)
}

# enable apis we need
resource "google_project_service" "apis" {
  for_each = toset([
    "container.googleapis.com",
    "compute.googleapis.com", 
    "artifactregistry.googleapis.com",
    "aiplatform.googleapis.com"
  ])

  service            = each.value
  project            = var.project_id
  disable_on_destroy = false
}

# main gke autopilot cluster - simplified management
resource "google_container_cluster" "main" {
  name     = "gke-turns-10-hackathon"
  location = var.region
  project  = var.project_id

  enable_autopilot = true

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  network    = "default"
  subnetwork = "default"

  # keep logging minimal to save money
  logging_config {
    enable_components = ["SYSTEM_COMPONENTS"]
  }

  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]  
  }

  # Set release channel to REGULAR for AutoPilot (required)
  release_channel {
    channel = "REGULAR"
  }

  depends_on = [google_project_service.apis]
}


# container registry
resource "google_artifact_registry_repository" "repo" {
  project       = var.project_id
  location      = var.region  
  repository_id = "gke-turns-10-repo"
  description   = "containers for hackathon"
  format        = "DOCKER"
  
  depends_on = [google_project_service.apis]
}

# service account for workload identity
resource "google_service_account" "gke_sa" {
  account_id   = "gke-turns-10-sa"
  display_name = "GKE Turns 10 Service Account"
  project      = var.project_id
}

resource "google_project_iam_member" "sa_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.gke_sa.email}"
}

resource "google_project_iam_member" "sa_storage" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.gke_sa.email}"
}

# bind workload identity - wait for cluster to be fully ready
resource "google_service_account_iam_member" "workload_identity" {
  service_account_id = google_service_account.gke_sa.name
  role               = "roles/iam.workloadIdentityUser" 
  member             = "serviceAccount:${var.project_id}.svc.id.goog[default/gke-turns-10-ksa]"
  
  # Ensure cluster is fully created before binding workload identity
  depends_on = [
    google_container_cluster.main
  ]
}

resource "kubernetes_service_account" "ksa" {
  metadata {
    name      = "gke-turns-10-ksa"
    namespace = "default"
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.gke_sa.email
    }
  }

  depends_on = [google_container_cluster.main]
}

# AutoPilot clusters manage resources automatically, so resource quotas and limits are not needed
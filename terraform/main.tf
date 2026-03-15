# GenAI MLOps Platform — Terraform Helm Deployment
#
# Manages the two-tier Helm release deployment to any Kubernetes cluster.
# For local k3d: terraform apply -var-file=environments/k3d.tfvars
# For cloud:     terraform apply -var-file=environments/aws.tfvars (future)
#
# The cluster itself is NOT provisioned here — k3d is managed via Taskfile,
# cloud clusters would be provisioned by a separate cloud-infra module.

provider "helm" {
  kubernetes {
    config_path    = pathexpand(var.kubeconfig_path)
    config_context = var.kubeconfig_context
  }
}

provider "kubernetes" {
  config_path    = pathexpand(var.kubeconfig_path)
  config_context = var.kubeconfig_context
}

# ── Namespace ──

resource "kubernetes_namespace" "genai" {
  metadata {
    name = var.namespace
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
      "app.kubernetes.io/part-of"    = "genai-mlops"
    }
  }
}

# ── Infrastructure Tier ──
# PostgreSQL x3, pgvector, MinIO, Neo4j

resource "helm_release" "genai_infra" {
  count = var.deploy_infra ? 1 : 0

  name      = "genai-infra"
  chart     = "${var.charts_dir}/genai-infra"
  namespace = kubernetes_namespace.genai.metadata[0].name
  timeout   = var.helm_timeout
  wait      = true

  values = [
    for f in var.infra_values_files :
    file("${var.charts_dir}/genai-infra/${f}")
  ]

  depends_on = [kubernetes_namespace.genai]
}

# ── Application Tier ──
# n8n, MLflow, Langfuse, LiteLLM, streaming-proxy, mcp-gateway

resource "helm_release" "genai_apps" {
  count = var.deploy_apps ? 1 : 0

  name      = "genai-apps"
  chart     = "${var.charts_dir}/genai-apps"
  namespace = kubernetes_namespace.genai.metadata[0].name
  timeout   = var.helm_timeout
  wait      = true

  values = [
    for f in var.apps_values_files :
    file("${var.charts_dir}/genai-apps/${f}")
  ]

  depends_on = [
    kubernetes_namespace.genai,
    helm_release.genai_infra,
  ]
}

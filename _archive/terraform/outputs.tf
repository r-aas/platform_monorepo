output "namespace" {
  description = "Kubernetes namespace for genai stack"
  value       = kubernetes_namespace.genai.metadata[0].name
}

output "infra_release" {
  description = "Infrastructure tier Helm release status"
  value = var.deploy_infra ? {
    name      = helm_release.genai_infra[0].name
    version   = helm_release.genai_infra[0].version
    status    = helm_release.genai_infra[0].status
    namespace = helm_release.genai_infra[0].namespace
  } : null
}

output "apps_release" {
  description = "Application tier Helm release status"
  value = var.deploy_apps ? {
    name      = helm_release.genai_apps[0].name
    version   = helm_release.genai_apps[0].version
    status    = helm_release.genai_apps[0].status
    namespace = helm_release.genai_apps[0].namespace
  } : null
}

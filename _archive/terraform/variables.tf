# ── Cluster connection ──

variable "kubeconfig_path" {
  description = "Path to kubeconfig file"
  type        = string
  default     = "~/.kube/config"
}

variable "kubeconfig_context" {
  description = "Kubeconfig context to use"
  type        = string
  default     = "k3d-mewtwo"
}

# ── Namespace ──

variable "namespace" {
  description = "Kubernetes namespace for genai stack"
  type        = string
  default     = "genai"
}

# ── Chart paths ──

variable "charts_dir" {
  description = "Path to Helm charts directory"
  type        = string
  default     = "../charts"
}

# ── Feature flags ──

variable "deploy_infra" {
  description = "Deploy the infrastructure tier (databases, MinIO, Neo4j)"
  type        = bool
  default     = true
}

variable "deploy_apps" {
  description = "Deploy the application tier (n8n, MLflow, Langfuse, LiteLLM)"
  type        = bool
  default     = true
}

# ── Helm timeout ──

variable "helm_timeout" {
  description = "Timeout in seconds for Helm operations"
  type        = number
  default     = 300
}

# ── Environment-specific values files ──

variable "infra_values_files" {
  description = "List of values files for genai-infra chart"
  type        = list(string)
  default     = ["values.yaml", "values-k3d.yaml"]
}

variable "apps_values_files" {
  description = "List of values files for genai-apps chart"
  type        = list(string)
  default     = ["values.yaml", "values-k3d.yaml"]
}

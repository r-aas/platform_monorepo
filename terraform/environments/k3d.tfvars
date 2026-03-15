# Local k3d cluster (default)
kubeconfig_path    = "~/.kube/config"
kubeconfig_context = "k3d-mewtwo"
namespace          = "genai"
charts_dir         = "../charts"
infra_values_files = ["values.yaml", "values-k3d.yaml"]
apps_values_files  = ["values.yaml", "values-k3d.yaml"]

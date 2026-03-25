#!/usr/bin/env bash
# Generate C4 Context diagram from live k3d cluster
set -euo pipefail

OUT="${1:-docs/architecture/c4-context.mmd}"
PLATFORM_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PLATFORM_DIR"

# Discover namespaces (exclude kube-system, kube-public, kube-node-lease, default)
NAMESPACES=$(kubectl get ns -o name | sed 's|namespace/||' | grep -vE '^(kube-system|kube-public|kube-node-lease|default)$' | sort)

cat > "$OUT" << 'HEADER'
%% C4 Context Diagram — Auto-generated from live k3d cluster
%% Re-generate: task arch:context
C4Context
  title Platform Context — mewtwo k3d cluster

  Person(r, "R", "Platform engineer")
  Person(ci, "GitLab CI", "CI/CD runner")

  System_Ext(ollama, "Ollama", "LLM inference (native Mac, Metal GPU)")
  System_Ext(browser, "Browser", "Web UIs via ingress")

HEADER

# Add platform boundary with namespace subsystems
echo '  Enterprise_Boundary(platform, "mewtwo k3d cluster") {' >> "$OUT"
for ns in $NAMESPACES; do
  svc_count=$(kubectl get svc -n "$ns" --no-headers 2>/dev/null | wc -l | tr -d ' ')
  desc=$(kubectl get svc -n "$ns" --no-headers 2>/dev/null | awk '{print $1}' | sed 's/^genai-//;s/^platform-//' | head -5 | tr '\n' ', ' | sed 's/,$//')
  echo "    System(ns_${ns}, \"${ns}\", \"${svc_count} services: ${desc}\")" >> "$OUT"
done
echo '  }' >> "$OUT"

# Relationships
cat >> "$OUT" << 'RELS'

  Rel(r, ns_genai, "Chat, eval, monitor")
  Rel(r, ns_platform, "GitOps, CI/CD")
  Rel(ci, ns_platform, "Pipeline triggers")
  Rel(browser, ns_genai, "Web UIs (n8n, MLflow, MinIO)")
  Rel(browser, ns_platform, "Web UIs (ArgoCD, GitLab)")
  Rel(ns_genai, ollama, "LLM inference via LiteLLM proxy")
RELS

echo ""
echo "Generated $OUT ($(wc -l < "$OUT" | tr -d ' ') lines)"

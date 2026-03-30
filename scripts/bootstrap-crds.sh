#!/usr/bin/env bash
# Bootstrap platform CRDs — must run before ArgoCD syncs charts that use them.
# CRDs exceed the 262KB annotation limit for normal kubectl apply,
# so we use server-side apply with force-conflicts.
#
# CRD sources:
#   kagent v0.8.0: https://github.com/kagent-dev/kagent
#   agentgateway v1.0.1: https://github.com/agentgateway/agentgateway
#
# Usage: ./scripts/bootstrap-crds.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRD_DIR="$SCRIPT_DIR/../manifests/crds"

if [ ! -d "$CRD_DIR" ]; then
  echo "ERROR: CRD manifests not found at $CRD_DIR"
  exit 1
fi

echo "=== Installing platform CRDs (server-side apply) ==="

for crd_file in "$CRD_DIR"/*.yaml; do
  name=$(basename "$crd_file" .yaml)
  echo -n "  $name ... "
  kubectl apply --server-side --force-conflicts -f "$crd_file" 2>&1 | tail -1
done

echo ""
echo "=== CRD bootstrap complete ==="
kubectl get crds | grep -E 'kagent|agentgateway'

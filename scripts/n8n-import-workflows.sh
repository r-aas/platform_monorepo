#!/usr/bin/env bash
set -euo pipefail

# Import n8n workflows from genai-mlops into k3d.
# Copies workflow JSONs, patches service URLs for k3d networking,
# imports via n8n CLI, and activates webhook-bearing workflows.
#
# Usage:
#   bash scripts/n8n-import-workflows.sh
#
# Requires:
#   - n8n pod running in genai namespace
#   - genai-mlops repo at ~/work/repos/genai-mlops
#   - n8n-api-credentials secret (from n8n-setup.sh)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="genai"
N8N_SVC="genai-n8n"
N8N_PORT=5678
WORKFLOWS_DIR="${HOME}/work/repos/genai-mlops/n8n-data/workflows"
TMPDIR=$(mktemp -d)
PF_PID=""
trap 'rm -rf "$TMPDIR"; [ -n "$PF_PID" ] && kill "$PF_PID" 2>/dev/null || true' EXIT

# k3d service URLs (replace docker-compose service names)
K3D_MLFLOW="http://genai-mlflow.genai.svc.cluster.local"
K3D_LITELLM="http://genai-litellm.genai.svc.cluster.local:4000"
K3D_N8N="http://genai-n8n.genai.svc.cluster.local:5678"
K3D_OLLAMA="http://192.168.5.2:11434"

echo "── n8n Workflow Import ──"

# ── Validate source ──────────────────────────────────────────────────────────
if [ ! -d "$WORKFLOWS_DIR" ]; then
  echo "  ✗ Workflow source not found: $WORKFLOWS_DIR"
  echo "  Clone genai-mlops: git clone <url> ~/work/repos/genai-mlops"
  exit 1
fi

WF_COUNT=$(ls -1 "$WORKFLOWS_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ')
echo "  Found ${WF_COUNT} workflows in ${WORKFLOWS_DIR}"

# ── Patch URLs for k3d ───────────────────────────────────────────────────────
echo "  Patching service URLs for k3d..."
for f in "$WORKFLOWS_DIR"/*.json; do
  name=$(basename "$f")
  sed \
    -e "s|http://mlflow:5050|${K3D_MLFLOW}|g" \
    -e "s|http://litellm:4000|${K3D_LITELLM}|g" \
    -e "s|http://n8n:5678|${K3D_N8N}|g" \
    -e "s|http://localhost:5678|${K3D_N8N}|g" \
    -e "s|http://host.docker.internal:11434|${K3D_OLLAMA}|g" \
    "$f" > "$TMPDIR/$name"
done
echo "  ✓ ${WF_COUNT} workflows patched"

# ── Get n8n pod name ─────────────────────────────────────────────────────────
N8N_POD=$(kubectl get pod -n ${NAMESPACE} -l app.kubernetes.io/instance=${N8N_SVC} \
  --no-headers -o custom-columns=NAME:.metadata.name | head -1)

if [ -z "$N8N_POD" ]; then
  echo "  ✗ No n8n pod found"
  exit 1
fi
echo "  Pod: ${N8N_POD}"

# ── Copy workflows to pod ────────────────────────────────────────────────────
echo "  Copying workflows to pod..."
kubectl exec -n ${NAMESPACE} ${N8N_POD} -- rm -rf /tmp/workflows
kubectl exec -n ${NAMESPACE} ${N8N_POD} -- mkdir -p /tmp/workflows
for f in "$TMPDIR"/*.json; do
  kubectl cp "$f" "${NAMESPACE}/${N8N_POD}:/tmp/workflows/$(basename "$f")"
done
echo "  ✓ Copied to /tmp/workflows/"

# ── Import via n8n CLI ───────────────────────────────────────────────────────
echo "  Importing workflows via n8n CLI..."
kubectl exec -n ${NAMESPACE} ${N8N_POD} -- ls /tmp/workflows/ 2>&1 | sed 's/^/    /'
kubectl exec -n ${NAMESPACE} ${N8N_POD} -- \
  n8n import:workflow --separate --input=/tmp/workflows 2>&1 | \
  sed 's/^/    /'
echo "  ✓ Workflows imported"

# ── Activate webhook-bearing workflows ───────────────────────────────────────
echo "  Activating workflows..."
WEBHOOK_WFS="prompt-crud-v1 prompt-eval-v1 openai-compat-v1 mlflow-data-v1 \
  mlflow-experiments-v1 chat-v1 a2a-server-v1 trace-v1 sessions-v1 agents-v1"

for wf_id in $WEBHOOK_WFS; do
  kubectl exec -n ${NAMESPACE} ${N8N_POD} -- \
    n8n update:workflow --id="$wf_id" --active=true 2>/dev/null || true
done
echo "  ✓ Workflows activated"

# ── Restart n8n to register webhooks ─────────────────────────────────────────
echo "  Restarting n8n to register webhooks..."
kubectl rollout restart deploy/${N8N_SVC} -n ${NAMESPACE}
kubectl rollout status deploy/${N8N_SVC} -n ${NAMESPACE} --timeout=120s >/dev/null 2>&1
echo "  ✓ n8n restarted"

# ── Port-forward and verify ──────────────────────────────────────────────────
kubectl port-forward -n ${NAMESPACE} svc/${N8N_SVC} ${N8N_PORT}:${N8N_PORT} &>/dev/null &
PF_PID=$!
sleep 3

# Get API key from secret
N8N_KEY=$(kubectl get secret n8n-api-credentials -n ${NAMESPACE} \
  -o jsonpath='{.data.api-key}' 2>/dev/null | base64 -d || true)

if [ -n "$N8N_KEY" ]; then
  echo -n "  Waiting for API..."
  for i in $(seq 1 20); do
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
      "http://localhost:${N8N_PORT}/api/v1/workflows?limit=1" \
      -H "X-N8N-API-KEY: ${N8N_KEY}" 2>/dev/null || echo "000")
    if [ "$HTTP" = "200" ]; then
      echo " ready"
      break
    fi
    echo -n "."
    sleep 2
  done

  ACTIVE=$(curl -s "http://localhost:${N8N_PORT}/api/v1/workflows?limit=100" \
    -H "X-N8N-API-KEY: ${N8N_KEY}" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin); wfs=d.get('data',[]); \
    print(f'{sum(1 for w in wfs if w.get(\"active\"))} active / {len(wfs)} total')" 2>/dev/null || echo "?")
  echo "  ✓ Workflows: ${ACTIVE}"
else
  echo "  ⚠ No API key found — run n8n-setup.sh first for verification"
fi

# ── Cleanup ──────────────────────────────────────────────────────────────────
kubectl exec -n ${NAMESPACE} ${N8N_POD} -- rm -rf /tmp/workflows 2>/dev/null || true

echo ""
echo "Done. Workflows imported and activated."
echo "  Webhooks will be available at: http://n8n.mewtwo.127.0.0.1.nip.io/webhook/*"

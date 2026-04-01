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
K3D_LITELLM="http://genai-agentgateway-llm.genai.svc.cluster.local:4000"
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

  # ── Patch Ollama credential ──────────────────────────────────────────────
  echo "  Patching Ollama credential..."
  N8N_API_URL="http://localhost:${N8N_PORT}/api/v1"
  export N8N_KEY N8N_API_URL K3D_OLLAMA

  python3 << 'PYEOF'
import json, os, urllib.request, urllib.error, sys

API_URL = os.environ["N8N_API_URL"]
API_KEY = os.environ["N8N_KEY"]
OLLAMA_URL = os.environ["K3D_OLLAMA"]

def api(method, path, data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"{API_URL}{path}", data=body,
        headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
        method=method)
    return json.loads(urllib.request.urlopen(req).read())

# Create or find Ollama credential
cred_id = None
try:
    resp = api("POST", "/credentials", {
        "name": "Ollama Local",
        "type": "ollamaApi",
        "data": {"baseUrl": OLLAMA_URL}
    })
    cred_id = resp["id"]
    print(f"  Created Ollama credential: {cred_id}", file=sys.stderr)
except urllib.error.HTTPError as e:
    if e.code == 409:
        # Find existing via chat-v1 workflow
        try:
            wf = api("GET", "/workflows/chat-v1")
            for n in wf.get("nodes", []):
                if n.get("name") == "Ollama Chat Model":
                    cid = n.get("credentials", {}).get("ollamaApi", {}).get("id", "")
                    if cid:
                        cred_id = cid
                        break
        except Exception:
            pass
        if cred_id:
            print(f"  Found existing Ollama credential: {cred_id}", file=sys.stderr)
    if not cred_id:
        print(f"  ⚠ Ollama credential failed: {e}", file=sys.stderr)

if cred_id:
    # Patch chat-v1 workflow's Ollama Chat Model node
    for wf_id in ["chat-v1"]:
        try:
            wf = api("GET", f"/workflows/{wf_id}")
            patched = False
            for node in wf.get("nodes", []):
                if node.get("name") == "Ollama Chat Model":
                    node.setdefault("credentials", {}).setdefault("ollamaApi", {})["id"] = cred_id
                    patched = True
            if patched:
                api("PUT", f"/workflows/{wf_id}", {
                    "name": wf["name"], "nodes": wf["nodes"],
                    "connections": wf["connections"],
                    "settings": wf.get("settings", {}),
                    **({"staticData": wf["staticData"]} if "staticData" in wf else {})
                })
                print(f"  ✓ Patched {wf['name']} with Ollama credential", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Failed to patch {wf_id}: {e}", file=sys.stderr)
else:
    print("  ⚠ Could not resolve Ollama credential — chat agent needs manual fix", file=sys.stderr)
PYEOF

else
  echo "  ⚠ No API key found — run n8n-setup.sh first for verification"
fi

# ── Create __sessions MLflow experiment ──────────────────────────────────────
# Required for sessions-v1 workflow to store chat history. Idempotent.
MLFLOW_URL="http://mlflow.platform.127.0.0.1.nip.io"
echo -n "  Ensuring __sessions MLflow experiment..."
HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
  "${MLFLOW_URL}/api/2.0/mlflow/experiments/get-by-name?experiment_name=__sessions" 2>/dev/null || echo "000")
if [ "$HTTP" = "200" ]; then
  echo " already exists"
else
  RESULT=$(curl -s -X POST "${MLFLOW_URL}/api/2.0/mlflow/experiments/create" \
    -H "Content-Type: application/json" \
    -d '{"name":"__sessions"}' 2>/dev/null || echo "{}")
  if echo "$RESULT" | grep -q "experiment_id"; then
    echo " created (id: $(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('experiment_id','?'))" 2>/dev/null))"
  else
    echo " ⚠ could not create (MLflow may not be ready yet)"
  fi
fi

# ── Cleanup ──────────────────────────────────────────────────────────────────
N8N_POD_NEW=$(kubectl get pod -n ${NAMESPACE} -l app.kubernetes.io/instance=${N8N_SVC} \
  --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null | head -1)
kubectl exec -n ${NAMESPACE} "${N8N_POD_NEW:-$N8N_POD}" -- rm -rf /tmp/workflows 2>/dev/null || true

echo ""
echo "Done. Workflows imported and activated."
echo "  Webhooks will be available at: http://n8n.platform.127.0.0.1.nip.io/webhook/*"

#!/usr/bin/env bash
set -euo pipefail
# ── n8n Import All ──────────────────────────────────────────────────────────
# Import 10 main workflows, activate them, then patch credentials.
#
# Usage: bash scripts/n8n-import-all.sh
#
# Steps:
#   1. Import workflow JSONs via n8n CLI
#   2. Activate all 10 workflows
#   3. Restart n8n + healthcheck
#   4. Patch Ollama credential
#   5. Patch webhook auth credential (if WEBHOOK_API_KEY set)
# ────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
N8N_PORT="${N8N_PORT:-5678}"
N8N_API_URL="http://localhost:${N8N_PORT}/api/v1"

echo "── n8n Import All ──"
echo "   Project: ${PROJECT_DIR}"
echo

# ── Step 1: Import all workflows via CLI ────────────────────────────────────
echo "Step 1: Importing workflows via n8n CLI..."
docker compose -f "${PROJECT_DIR}/docker-compose.yml" run --rm --entrypoint /bin/sh n8n-import -c '
  export N8N_ENCRYPTION_KEY=$(cat /run/secrets/n8n_encryption_key)
  export DB_POSTGRESDB_PASSWORD=$(cat /run/secrets/n8n_postgres_password)
  n8n import:workflow --separate --input=/demo-data/workflows
'
echo "   ✓ Workflows imported"

# ── Step 2: Activate all workflows ──────────────────────────────────────────
echo "Step 2: Activating workflows..."
docker compose -f "${PROJECT_DIR}/docker-compose.yml" run --rm --entrypoint /bin/sh n8n-import -c '
  export N8N_ENCRYPTION_KEY=$(cat /run/secrets/n8n_encryption_key)
  export DB_POSTGRESDB_PASSWORD=$(cat /run/secrets/n8n_postgres_password)
  # Only activate webhook-bearing workflows — sub-workflows and tool workflows
  # have no trigger nodes and MUST NOT be activated (causes infinite retry loops)
  for wf_id in prompt-crud-v1 prompt-eval-v1 openai-compat-v1 mlflow-data-v1 \
    mlflow-experiments-v1 chat-v1 a2a-server-v1 trace-v1 sessions-v1 agents-v1; do
    n8n update:workflow --id="$wf_id" --active=true 2>/dev/null || true
  done
'
echo "   ✓ Workflows activated"

# ── Step 3: Restart n8n to register webhooks ────────────────────────────────
echo "Step 3: Restarting n8n..."
docker compose -f "${PROJECT_DIR}/docker-compose.yml" restart n8n
echo -n "   Waiting for n8n..."
HEALTHY=false
for i in $(seq 1 30); do
  if curl -sf --max-time 2 "http://localhost:${N8N_PORT}/healthz" >/dev/null 2>&1; then
    echo " ready"
    HEALTHY=true
    break
  fi
  echo -n "."
  sleep 2
done
if [ "$HEALTHY" != "true" ]; then
  echo " TIMEOUT"
  echo "   ✗ n8n not responding at localhost:${N8N_PORT}/healthz after 60s"
  exit 1
fi
echo "   ✓ n8n restarted"

# ── Step 4: Patch Ollama credential ─────────────────────────────────────────
# Steps 4-5 need the n8n REST API. Read API key and wait for readiness.
N8N_KEY=$(cat "${PROJECT_DIR}/secrets/n8n_api_key" 2>/dev/null || true)
export N8N_KEY N8N_API_URL PROJECT_DIR

if [ -z "$N8N_KEY" ]; then
  echo "   ⚠ No n8n API key (secrets/n8n_api_key) — skipping credential patching"
  exit 0
fi

echo -n "   Waiting for REST API..."
API_READY=false
for i in $(seq 1 15); do
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${N8N_API_URL}/workflows?limit=1" \
    -H "X-N8N-API-KEY: ${N8N_KEY}" 2>/dev/null || echo "000")
  if [ "$HTTP" = "200" ]; then
    echo " ready"
    API_READY=true
    break
  fi
  echo -n "."
  sleep 2
done
if [ "$API_READY" != "true" ]; then
  echo " TIMEOUT"
  echo "   ⚠ REST API not ready — skipping credential patching"
  exit 0
fi

echo "Step 4: Patching LLM credentials (LiteLLM OpenAI + Ollama fallback)..."
python3 << 'PYEOF'
import json
import os
import urllib.request

API_URL = os.environ.get("N8N_API_URL", "http://localhost:5678/api/v1")
API_KEY = os.environ.get("N8N_KEY", "")
LITELLM_BASE = os.environ.get("INFERENCE_BASE_URL", "http://genai-litellm.genai.svc.cluster.local:4000/v1")
LITELLM_KEY = os.environ.get("LITELLM_API_KEY", "sk-litellm-mewtwo-local")

def api_get(path):
    req = urllib.request.Request(
        f"{API_URL}{path}",
        headers={"X-N8N-API-KEY": API_KEY}
    )
    return json.loads(urllib.request.urlopen(req).read())

def api_post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=body,
        headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
        method="POST"
    )
    return json.loads(urllib.request.urlopen(req).read())

def api_put(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=body,
        headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
        method="PUT"
    )
    return json.loads(urllib.request.urlopen(req).read())

# ── Helper: find or create credential (idempotent — no duplicates) ──
def find_or_create_credential(name, cred_type, data):
    """Find existing credential by name+type, or create if missing."""
    try:
        creds = api_get("/credentials")
        for c in creds.get("data", []):
            if c.get("name") == name and c.get("type") == cred_type:
                print(f"   Found existing {name} credential: {c['id']}")
                return c["id"]
    except Exception:
        pass
    try:
        resp = api_post("/credentials", {"name": name, "type": cred_type, "data": data})
        print(f"   Created {name} credential: {resp['id']}")
        return resp["id"]
    except Exception as e:
        print(f"   ⚠ {name} credential failed: {e}")
        return None

# ── LiteLLM (OpenAI-compatible) credential ──
litellm_cred_id = find_or_create_credential(
    "LiteLLM", "openAiApi",
    {"apiKey": LITELLM_KEY, "url": LITELLM_BASE}
)

# ── Ollama credential (for backward compat / other workflows) ──
ollama_cred_id = find_or_create_credential(
    "Ollama Local", "ollamaApi",
    {"baseUrl": "http://host.docker.internal:11434"}
)

# ── Patch chat-v1 workflow: LiteLLM Chat Model node ──
if litellm_cred_id:
    agent_wf_ids = ["chat-v1"]
    for wf_id in agent_wf_ids:
        try:
            wf = api_get(f"/workflows/{wf_id}")
            patched = False
            for node in wf.get("nodes", []):
                if node.get("name") == "LiteLLM Chat Model":
                    node.setdefault("credentials", {})["openAiApi"] = {"id": litellm_cred_id}
                    patched = True
            if patched:
                update_body = {
                    "name": wf["name"],
                    "nodes": wf["nodes"],
                    "connections": wf["connections"],
                    "settings": wf.get("settings", {}),
                }
                if "staticData" in wf:
                    update_body["staticData"] = wf["staticData"]
                api_put(f"/workflows/{wf_id}", update_body)
                print(f"   ✓ Patched {wf['name']} with LiteLLM credential {litellm_cred_id}")
        except Exception as e:
            print(f"   ⚠ Failed to patch {wf_id}: {e}")
else:
    print("   ⚠ No LiteLLM credential — AI Agent node needs manual credential setup")
PYEOF

# ── Step 5: Webhook auth credential + node patching ──────────────────────────
echo "Step 5: Configuring webhook authentication..."
WEBHOOK_API_KEY="${WEBHOOK_API_KEY:-}"
export WEBHOOK_API_KEY

python3 << 'PYEOF'
import json
import os
import sys
import urllib.request
import urllib.error

API_URL = os.environ.get("N8N_API_URL", "http://localhost:5678/api/v1")
API_KEY = os.environ.get("N8N_KEY", "")
WEBHOOK_KEY = os.environ.get("WEBHOOK_API_KEY", "").strip()

def api_get(path):
    req = urllib.request.Request(
        f"{API_URL}{path}",
        headers={"X-N8N-API-KEY": API_KEY}
    )
    return json.loads(urllib.request.urlopen(req).read())

def api_post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=body,
        headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
        method="POST"
    )
    return json.loads(urllib.request.urlopen(req).read())

def api_put(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=body,
        headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
        method="PUT"
    )
    return json.loads(urllib.request.urlopen(req).read())

if not WEBHOOK_KEY:
    print("   ℹ WEBHOOK_API_KEY empty — open mode (no webhook auth)")
    sys.exit(0)

print(f"   WEBHOOK_API_KEY is set — enabling auth on webhook nodes")

# Find or create httpHeaderAuth credential (idempotent)
cred_id = None
try:
    creds = api_get("/credentials")
    for c in creds.get("data", []):
        if c.get("name") == "Webhook API Key" and c.get("type") == "httpHeaderAuth":
            cred_id = c["id"]
            print(f"   Found existing httpHeaderAuth credential: {cred_id}")
            break
except Exception:
    pass
if not cred_id:
    try:
        resp = api_post("/credentials", {
            "name": "Webhook API Key",
            "type": "httpHeaderAuth",
            "data": {"name": "X-API-Key", "value": WEBHOOK_KEY}
        })
        cred_id = resp["id"]
        print(f"   Created httpHeaderAuth credential: {cred_id}")
    except Exception as e:
        print(f"   ✗ Credential creation failed: {e}")
        sys.exit(1)

# Patch all webhook trigger nodes to require headerAuth
workflows = api_get("/workflows?limit=100")
patched_nodes = 0
patched_workflows = 0

for wf_summary in workflows.get("data", []):
    wf = api_get(f"/workflows/{wf_summary['id']}")
    needs_update = False

    for node in wf.get("nodes", []):
        if node.get("type") != "n8n-nodes-base.webhook":
            continue

        # Set authentication to headerAuth
        node["parameters"]["authentication"] = "headerAuth"

        # Add credential reference
        node.setdefault("credentials", {})["httpHeaderAuth"] = {"id": cred_id}

        needs_update = True
        patched_nodes += 1

    if needs_update:
        update_body = {
            "name": wf["name"],
            "nodes": wf["nodes"],
            "connections": wf["connections"],
            "settings": wf.get("settings", {}),
        }
        if "staticData" in wf:
            update_body["staticData"] = wf["staticData"]
        api_put(f"/workflows/{wf['id']}", update_body)
        patched_workflows += 1

print(f"   ✓ Patched {patched_nodes} webhook nodes across {patched_workflows} workflows")
PYEOF

echo "   ✓ Webhook auth configured"

echo
echo "── Import complete ──"
echo "   Run 'task smoke' to verify all endpoints."

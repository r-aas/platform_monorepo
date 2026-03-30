#!/usr/bin/env bash
# Setup Ollama credential in n8n and patch the AI Agent workflow.
# Usage: ./scripts/setup-agent.sh [--force]
#
# Requires: n8n running with API key at secrets/n8n_api_key
# Idempotent — skips if credential already exists (unless --force).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS_DIR="$REPO_DIR/secrets"
FORCE="${1:-}"
N8N_URL="${N8N_URL:-http://localhost:5678}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://host.docker.internal:11434}"
WORKFLOW_IDS="chat-v1"
CRED_NAME="Ollama Local"

# ── Pre-checks ────────────────────────────────────────────────────────────────

if [ ! -f "$SECRETS_DIR/n8n_api_key" ]; then
    echo "  ✗ No API key found. Run: task setup-n8n-api"
    exit 1
fi

API_KEY=$(cat "$SECRETS_DIR/n8n_api_key")

# Wait for n8n
echo -n "  Waiting for n8n..."
for i in $(seq 1 30); do
    if curl -sf "$N8N_URL/healthz" >/dev/null 2>&1; then
        echo " ready"
        break
    fi
    [ "$i" = "30" ] && { echo " TIMEOUT"; exit 1; }
    echo -n "."
    sleep 1
done

# ── Find or create Ollama credential ──────────────────────────────────────────

echo "  Checking for existing Ollama credential..."

CRED_ID=$(python3 - "$N8N_URL" "$API_KEY" "$OLLAMA_BASE_URL" "$CRED_NAME" "$FORCE" << 'PYEOF'
import urllib.request, urllib.error, json, sys

N8N_URL = sys.argv[1]
API_KEY = sys.argv[2]
OLLAMA_URL = sys.argv[3]
CRED_NAME = sys.argv[4]
FORCE = sys.argv[5]

headers = {
    "Content-Type": "application/json",
    "X-N8N-API-KEY": API_KEY
}

def api(method, path, data=None):
    url = f"{N8N_URL}/api/v1{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except:
            return e.code, {}

# Check for existing credential
code, resp = api("GET", "/credentials")
existing_id = None
if code == 200:
    creds = resp.get("data", resp) if isinstance(resp, dict) else resp
    if isinstance(creds, list):
        for c in creds:
            if c.get("name") == CRED_NAME and c.get("type") == "ollamaApi":
                existing_id = c["id"]
                break

if existing_id and FORCE != "--force":
    print(f"  ✓ Credential '{CRED_NAME}' already exists (id={existing_id})", file=sys.stderr)
    print(existing_id)
    sys.exit(0)

# Delete existing if --force
if existing_id and FORCE == "--force":
    api("DELETE", f"/credentials/{existing_id}")
    print(f"  → Deleted existing credential {existing_id}", file=sys.stderr)

# Create new credential
code, resp = api("POST", "/credentials", {
    "name": CRED_NAME,
    "type": "ollamaApi",
    "data": {
        "baseUrl": OLLAMA_URL
    }
})

if code in (200, 201):
    cred_data = resp.get("data", resp) if isinstance(resp, dict) else resp
    cred_id = cred_data.get("id", "")
    if cred_id:
        print(f"  ✓ Created credential '{CRED_NAME}' (id={cred_id})", file=sys.stderr)
        print(cred_id)
        sys.exit(0)

print(f"  ✗ Failed to create credential: {code} {resp}", file=sys.stderr)
sys.exit(1)
PYEOF
)

if [ -z "$CRED_ID" ]; then
    echo "  ✗ Could not get credential ID"
    exit 1
fi

echo "  Credential ID: $CRED_ID"

# ── Patch workflows to use the credential ─────────────────────────────────────

for WORKFLOW_ID in $WORKFLOW_IDS; do

echo "  Patching workflow $WORKFLOW_ID with credential..."

python3 - "$N8N_URL" "$API_KEY" "$WORKFLOW_ID" "$CRED_ID" "$CRED_NAME" << 'PYEOF'
import urllib.request, urllib.error, json, sys

N8N_URL = sys.argv[1]
API_KEY = sys.argv[2]
WF_ID = sys.argv[3]
CRED_ID = sys.argv[4]
CRED_NAME = sys.argv[5]

headers = {
    "Content-Type": "application/json",
    "X-N8N-API-KEY": API_KEY
}

def api(method, path, data=None):
    url = f"{N8N_URL}/api/v1{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except:
            return e.code, {}

# Get current workflow
code, wf = api("GET", f"/workflows/{WF_ID}")
if code != 200:
    print(f"  ✗ Could not fetch workflow {WF_ID}: {code}", file=sys.stderr)
    sys.exit(1)

# Patch the Ollama node credential
patched = False
for node in wf.get("nodes", []):
    if node.get("type", "").endswith("lmChatOllama"):
        node["credentials"] = {
            "ollamaApi": {
                "id": CRED_ID,
                "name": CRED_NAME
            }
        }
        patched = True
        print(f"  → Patched node '{node['name']}' with credential id={CRED_ID}", file=sys.stderr)

if not patched:
    print("  ⚠ No Ollama node found in workflow — skipping patch", file=sys.stderr)
    sys.exit(0)

# Strip fields the PUT API rejects (only name, nodes, connections, settings, staticData allowed)
update_body = {
    "name": wf.get("name"),
    "nodes": wf.get("nodes", []),
    "connections": wf.get("connections", {}),
    "settings": wf.get("settings", {}),
}
if "staticData" in wf:
    update_body["staticData"] = wf["staticData"]

code, resp = api("PUT", f"/workflows/{WF_ID}", update_body)
if code == 200:
    print(f"  ✓ Workflow {WF_ID} updated with Ollama credential", file=sys.stderr)
else:
    print(f"  ✗ Failed to update workflow: {code} {resp}", file=sys.stderr)
    sys.exit(1)

# Activate workflow via POST /activate endpoint
code, resp = api("POST", f"/workflows/{WF_ID}/activate", {})
if code == 200:
    print(f"  ✓ Workflow {WF_ID} activated", file=sys.stderr)
else:
    # Fallback: try PATCH with active flag
    code2, resp2 = api("PATCH", f"/workflows/{WF_ID}", {"active": True})
    if code2 == 200:
        print(f"  ✓ Workflow {WF_ID} activated (via PATCH)", file=sys.stderr)
    else:
        print(f"  ⚠ Activation returned {code}/{code2} — verify in n8n UI", file=sys.stderr)
PYEOF

done

echo ""
echo "Done. AI Agent workflows configured."
echo "  Credential: $CRED_NAME (id=$CRED_ID)"
echo "  Workflows:  $WORKFLOW_IDS"
echo "  Endpoints:  POST $N8N_URL/webhook/chat"

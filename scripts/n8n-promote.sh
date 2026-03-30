#!/usr/bin/env bash
# Promote n8n workflows from genai-mlops to a k8s n8n instance.
# Usage: ./scripts/n8n-promote.sh <namespace>
#
# Reads workflow JSONs from n8n-data/workflows/, patches URLs for k8s,
# resolves credentials, and upserts via n8n REST API.
#
# Idempotent — safe to run repeatedly. Matches workflows by name for upsert.
set -euo pipefail

NS="${1:?Usage: $0 <namespace> (dev|stage|prod)}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKFLOW_DIR="$REPO_DIR/n8n-data/workflows"

# ── URL routing (CI vs local) ────────────────────────────────────────────────
if [ -n "${CI:-}" ]; then
  N8N_BASE="http://host.docker.internal"
  HOST_HEADER="n8n.platform.127.0.0.1.nip.io"
else
  N8N_BASE="http://n8n.platform.127.0.0.1.nip.io"
  HOST_HEADER=""
fi

echo "═══ n8n workflow promotion → $NS ═══"
echo "  Target: $N8N_BASE"

# ── Get API key from k8s secret ──────────────────────────────────────────────
API_KEY=$(kubectl get secret n8n-secrets -n "$NS" -o jsonpath='{.data.api-key}' 2>/dev/null | base64 -d 2>/dev/null || true)
if [ -z "$API_KEY" ]; then
  echo "  ✗ No API key in n8n-secrets/$NS. Run: task n8n:setup"
  exit 1
fi

# ── Health check ─────────────────────────────────────────────────────────────
echo -n "  Health check..."
if [ -n "$HOST_HEADER" ]; then
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: $HOST_HEADER" "$N8N_BASE/healthz" 2>/dev/null || echo "000")
else
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$N8N_BASE/healthz" 2>/dev/null || echo "000")
fi
if [ "$HTTP" != "200" ]; then
  echo " FAILED (HTTP $HTTP)"
  exit 1
fi
echo " OK"

# ── Promote all workflows ────────────────────────────────────────────────────
python3 - "$N8N_BASE" "$API_KEY" "$WORKFLOW_DIR" "$NS" "${HOST_HEADER:-}" << 'PYEOF'
import urllib.request, urllib.error, json, sys, os, glob

N8N_BASE = sys.argv[1]
API_KEY = sys.argv[2]
WORKFLOW_DIR = sys.argv[3]
NS = sys.argv[4]
HOST_HEADER = sys.argv[5] if len(sys.argv) > 5 else ""

OLLAMA_BASE_URL = "http://host.docker.internal:11434"
CRED_NAME = "Ollama Local"

# URL replacements: docker-compose service names → k8s-accessible hosts
URL_REPLACEMENTS = {
    "http://mlflow:5050":      "http://host.docker.internal:5050",
    "http://mcp-gateway:8811": "http://host.docker.internal:8811",
}

# ── API helper ───────────────────────────────────────────────────────────────

def api(method, path, data=None):
    url = f"{N8N_BASE}/api/v1{path}"
    body = json.dumps(data).encode() if data else None
    headers = {
        "Content-Type": "application/json",
        "X-N8N-API-KEY": API_KEY,
    }
    if HOST_HEADER:
        headers["Host"] = HOST_HEADER
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}

# ── Resolve existing workflows (name → id map) ──────────────────────────────

code, resp = api("GET", "/workflows")
if code != 200:
    print(f"  ✗ Failed to list workflows: {code}")
    sys.exit(1)

wf_list = resp.get("data", resp) if isinstance(resp, dict) else resp
if isinstance(wf_list, list):
    existing = {w["name"]: w["id"] for w in wf_list}
else:
    existing = {}

# ── Resolve Ollama credential ────────────────────────────────────────────────

ollama_cred_id = None

code, resp = api("GET", "/credentials")
if code == 200:
    creds = resp.get("data", resp) if isinstance(resp, dict) else resp
    if isinstance(creds, list):
        for c in creds:
            if c.get("name") == CRED_NAME and c.get("type") == "ollamaApi":
                ollama_cred_id = c["id"]
                break

if not ollama_cred_id:
    code, resp = api("POST", "/credentials", {
        "name": CRED_NAME,
        "type": "ollamaApi",
        "data": {"baseUrl": OLLAMA_BASE_URL},
    })
    if code in (200, 201):
        cred_data = resp.get("data", resp) if isinstance(resp, dict) else resp
        ollama_cred_id = cred_data.get("id")
        print(f"  ✓ Created credential '{CRED_NAME}' (id={ollama_cred_id})")
    else:
        print(f"  ⚠ Could not create Ollama credential: {code} — chat workflow may fail")

if ollama_cred_id:
    print(f"  ✓ Ollama credential id={ollama_cred_id}")

# ── Process each workflow ────────────────────────────────────────────────────

files = sorted(glob.glob(os.path.join(WORKFLOW_DIR, "*.json")))
ok, fail = 0, 0

for fpath in files:
    fname = os.path.basename(fpath)
    with open(fpath) as f:
        wf = json.load(f)

    name = wf.get("name", fname.replace(".json", ""))
    print(f"\n  ── {fname} ({name}) ──")

    # 1. URL patching
    wf_text = json.dumps(wf)
    for old_url, new_url in URL_REPLACEMENTS.items():
        wf_text = wf_text.replace(old_url, new_url)
    wf = json.loads(wf_text)

    # 2. Credential patching (chat workflow → Ollama)
    if ollama_cred_id:
        for node in wf.get("nodes", []):
            if node.get("type", "").endswith("lmChatOllama"):
                node["credentials"] = {
                    "ollamaApi": {
                        "id": str(ollama_cred_id),
                        "name": CRED_NAME,
                    }
                }
                print(f"    → Patched Ollama credential on '{node['name']}'")

    # 3. Strip to API-allowed fields
    body = {
        "name": name,
        "nodes": wf.get("nodes", []),
        "connections": wf.get("connections", {}),
        "settings": wf.get("settings", {}),
    }
    if "staticData" in wf:
        body["staticData"] = wf["staticData"]

    # 4. Upsert: find by name → PUT or POST
    if name in existing:
        wf_id = existing[name]
        code, resp = api("PUT", f"/workflows/{wf_id}", body)
        action = "updated"
    else:
        code, resp = api("POST", "/workflows", body)
        action = "created"
        if code in (200, 201):
            resp_data = resp.get("data", resp) if isinstance(resp, dict) else resp
            wf_id = resp_data.get("id", "?")
            existing[name] = wf_id

    if code not in (200, 201):
        print(f"    ✗ {action.upper()} FAILED: {code} {json.dumps(resp)[:200]}")
        fail += 1
        continue

    print(f"    ✓ {action} (id={existing.get(name, '?')})")

    # 5. Activate
    wf_id = existing[name]
    code, resp = api("POST", f"/workflows/{wf_id}/activate", {})
    if code == 200:
        print(f"    ✓ activated")
    else:
        # Fallback: PATCH with active flag
        code2, _ = api("PATCH", f"/workflows/{wf_id}", {"active": True})
        if code2 == 200:
            print(f"    ✓ activated (via PATCH)")
        else:
            print(f"    ⚠ activation returned {code}/{code2} — check n8n UI")

    ok += 1

# ── Deactivate sub-workflows ─────────────────────────────────────────────────
# Sub-workflows (no trigger nodes) must not be active — they cause infinite
# retry loops with exponential backoff, exhausting DB connections.
code, resp = api("GET", "/workflows")
wf_all = resp.get("data", resp) if isinstance(resp, dict) else resp
TRIGGER_TYPES = {"n8n-nodes-base.webhook", "n8n-nodes-base.scheduleTrigger",
                 "n8n-nodes-base.formTrigger", "n8n-nodes-base.chatTrigger"}
deactivated = 0
if isinstance(wf_all, list):
    for w in wf_all:
        node_types = {n.get("type", "") for n in w.get("nodes", [])}
        if not node_types & TRIGGER_TYPES:
            if w.get("active", False):
                api("POST", f"/workflows/{w['id']}/deactivate", {})
                print(f"    ⚠ Deactivated sub-workflow: {w['name']} (id={w['id']})")
                deactivated += 1
print(f"\n  ✓ Sub-workflow check: {deactivated} deactivated")

# ── Summary ──────────────────────────────────────────────────────────────────
print(f"\n  ═══ Summary: {ok} succeeded, {fail} failed out of {len(files)} workflows ═══")
if fail > 0:
    sys.exit(1)
PYEOF

echo ""
echo "✓ Promotion to $NS complete"

#!/usr/bin/env bash
set -euo pipefail

# n8n post-deploy setup for k3d platform.
# Creates owner account, generates API key, stores in k8s Secret.
#
# Usage:
#   bash scripts/n8n-setup.sh [--force]
#
# Requires: n8n pod running in genai namespace

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FORCE="${1:-}"
NAMESPACE="genai"
N8N_SVC="genai-n8n"
N8N_PORT=5678
N8N_OWNER_EMAIL="admin@platform.local"
N8N_OWNER_PASSWORD="Admin-k3d-L0cal"
SECRET_NAME="n8n-api-credentials"

echo "── n8n Setup ──"

# ── Wait for n8n pod ─────────────────────────────────────────────────────────
echo -n "  Waiting for n8n pod..."
kubectl wait --for=condition=Ready pod -l app.kubernetes.io/instance=${N8N_SVC} \
  -n ${NAMESPACE} --timeout=600s >/dev/null 2>&1
echo " ready"

# ── Check if already configured ──────────────────────────────────────────────
if kubectl get secret ${SECRET_NAME} -n ${NAMESPACE} &>/dev/null && [ "$FORCE" != "--force" ]; then
  echo "  ✓ ${SECRET_NAME} already exists (use --force to reconfigure)"
  N8N_KEY=$(kubectl get secret ${SECRET_NAME} -n ${NAMESPACE} -o jsonpath='{.data.api-key}' | base64 -d)
  echo "  API key: ${N8N_KEY:0:8}..."
  exit 0
fi

# ── Port-forward ─────────────────────────────────────────────────────────────
echo "  Starting port-forward..."
kubectl port-forward -n ${NAMESPACE} svc/${N8N_SVC} ${N8N_PORT}:${N8N_PORT} &>/dev/null &
PF_PID=$!
trap "kill $PF_PID 2>/dev/null || true" EXIT
sleep 2

N8N_URL="http://localhost:${N8N_PORT}"

# Wait for n8n HTTP
echo -n "  Waiting for n8n HTTP..."
for i in $(seq 1 30); do
  if curl -sf "${N8N_URL}/healthz" >/dev/null 2>&1; then
    echo " ready"
    break
  fi
  [ "$i" = "30" ] && { echo " TIMEOUT"; exit 1; }
  echo -n "."
  sleep 1
done

# ── Create owner + API key ───────────────────────────────────────────────────
API_KEY=$(python3 - "$N8N_URL" "$N8N_OWNER_EMAIL" "$N8N_OWNER_PASSWORD" << 'PYEOF'
import urllib.request, urllib.error, json, time, sys, re

N8N_URL = sys.argv[1]
EMAIL = sys.argv[2]
PASSWORD = sys.argv[3]

def post(url, data, headers=None):
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, json.dumps(data).encode(), hdrs)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read()), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body), {}
        except json.JSONDecodeError:
            return e.code, {"raw": body}, {}

def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

# 1. Create owner
print("  Creating owner account...", file=sys.stderr)
code, resp, hdrs = post(f"{N8N_URL}/rest/owner/setup", {
    "email": EMAIL,
    "password": PASSWORD,
    "firstName": "Admin",
    "lastName": "Platform"
})

auth_cookie = None
if code == 200:
    sc = hdrs.get("Set-Cookie", hdrs.get("set-cookie", ""))
    m = re.search(r'n8n-auth=([^;]+)', sc)
    if m:
        auth_cookie = m.group(1)
    print(f"  ✓ Owner created ({EMAIL})", file=sys.stderr)
elif code == 400:
    msg = resp.get("message", str(resp))
    if "already setup" in msg.lower() or "already exists" in msg.lower():
        print("  ⚠ Owner exists, logging in...", file=sys.stderr)
    else:
        print(f"  ✗ Setup rejected: {msg}", file=sys.stderr)
        sys.exit(1)
else:
    print("  ⚠ Owner exists, logging in...", file=sys.stderr)

# 2. Login if needed
if not auth_cookie:
    req = urllib.request.Request(
        f"{N8N_URL}/rest/login",
        json.dumps({"emailOrLdapLoginId": EMAIL, "password": PASSWORD, "mfaToken": "", "mfaRecoveryCode": ""}).encode(),
        {"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        sc = resp.headers.get("Set-Cookie", "")
        m = re.search(r'n8n-auth=([^;]+)', sc)
        if m:
            auth_cookie = m.group(1)
            print(f"  ✓ Logged in as {EMAIL}", file=sys.stderr)
        else:
            print("  ✗ No auth cookie", file=sys.stderr)
            sys.exit(1)
    except urllib.error.HTTPError as e:
        print(f"  ✗ Login failed: {e.code}", file=sys.stderr)
        sys.exit(1)

# 3. Delete existing API keys
code, existing = get(f"{N8N_URL}/rest/api-keys", {"Cookie": f"n8n-auth={auth_cookie}"})
if code == 200:
    keys = existing.get("data", existing) if isinstance(existing, dict) else existing
    if isinstance(keys, list):
        for key in keys:
            kid = key.get("id", "")
            if kid:
                dreq = urllib.request.Request(f"{N8N_URL}/rest/api-keys/{kid}", method="DELETE",
                    headers={"Cookie": f"n8n-auth={auth_cookie}"})
                try:
                    urllib.request.urlopen(dreq)
                except urllib.error.HTTPError:
                    pass

# 4. Create new API key
expires_at = int((time.time() + 365 * 24 * 3600) * 1000)
req = urllib.request.Request(
    f"{N8N_URL}/rest/api-keys",
    json.dumps({"label": "platform-api", "scopes": ["workflow:list"], "expiresAt": expires_at}).encode(),
    {"Content-Type": "application/json", "Cookie": f"n8n-auth={auth_cookie}"}
)
try:
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    data = result.get("data", result)
    raw_key = data.get("rawApiKey", data.get("apiKey", ""))
    if not raw_key or raw_key.startswith("***"):
        print("  ✗ No raw API key in response", file=sys.stderr)
        sys.exit(1)
    print(f"  ✓ API key created", file=sys.stderr)
    print(raw_key)
except urllib.error.HTTPError as e:
    print(f"  ✗ API key creation failed: {e.code}", file=sys.stderr)
    sys.exit(1)
PYEOF
)

if [ -z "$API_KEY" ] || [ "$API_KEY" = "None" ]; then
  echo "  ✗ Empty API key"
  exit 1
fi

# ── Store in k8s Secret ──────────────────────────────────────────────────────
kubectl create secret generic ${SECRET_NAME} -n ${NAMESPACE} \
  --from-literal=api-key="${API_KEY}" \
  --from-literal=owner-email="${N8N_OWNER_EMAIL}" \
  --from-literal=owner-password="${N8N_OWNER_PASSWORD}" \
  --dry-run=client -o yaml | kubectl apply -f -
echo "  ✓ Secret ${SECRET_NAME} created in ${NAMESPACE}"

# ── Verify ───────────────────────────────────────────────────────────────────
VERIFY=$(curl -sf "${N8N_URL}/api/v1/workflows" -H "X-N8N-API-KEY: ${API_KEY}" 2>&1) || true
if echo "$VERIFY" | grep -q '"data"'; then
  COUNT=$(echo "$VERIFY" | python3 -c "import sys,json; print(len(json.loads(sys.stdin.read()).get('data',[])))" 2>/dev/null || echo "?")
  echo "  ✓ API key verified (${COUNT} workflows)"
else
  echo "  ⚠ API key saved but verification failed — n8n may need restart"
fi

echo ""
echo "Done."
echo "  Owner:  ${N8N_OWNER_EMAIL} / ${N8N_OWNER_PASSWORD}"
echo "  Secret: ${SECRET_NAME} in ${NAMESPACE}"

#!/usr/bin/env bash
# Verify n8n workflows are deployed and webhooks are reachable.
# Usage: ./scripts/n8n-verify.sh <namespace>
set -euo pipefail

NS="${1:?Usage: $0 <namespace> (dev|stage|prod)}"
EXPECTED_COUNT=9

# ── URL routing (CI vs local) ────────────────────────────────────────────────
if [ -n "${CI:-}" ]; then
  N8N_BASE="http://host.docker.internal"
  HOST_HEADER="n8n.platform.127.0.0.1.nip.io"
else
  N8N_BASE="http://n8n.platform.127.0.0.1.nip.io"
  HOST_HEADER=""
fi

# Helper: curl with optional Host header
n8n_curl() {
  if [ -n "$HOST_HEADER" ]; then
    curl -s -H "Host: $HOST_HEADER" "$@"
  else
    curl -s "$@"
  fi
}

API_KEY=$(kubectl get secret n8n-secrets -n "$NS" -o jsonpath='{.data.api-key}' 2>/dev/null | base64 -d 2>/dev/null || true)
if [ -z "$API_KEY" ]; then
  echo "  ✗ No API key — cannot verify"
  exit 1
fi

echo "═══ n8n verification → $NS ═══"

# ── Check workflow count ─────────────────────────────────────────────────────
COUNT=$(n8n_curl "$N8N_BASE/api/v1/workflows" \
  -H "X-N8N-API-KEY: $API_KEY" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',d) if isinstance(d,dict) else d))" 2>/dev/null || echo "0")

if [ "$COUNT" -ge "$EXPECTED_COUNT" ]; then
  echo "  ✓ Workflow count: $COUNT (expected ≥$EXPECTED_COUNT)"
else
  echo "  ✗ Workflow count: $COUNT (expected ≥$EXPECTED_COUNT)"
  exit 1
fi

# ── Check active count ───────────────────────────────────────────────────────
ACTIVE=$(n8n_curl "$N8N_BASE/api/v1/workflows?active=true" \
  -H "X-N8N-API-KEY: $API_KEY" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',d) if isinstance(d,dict) else d))" 2>/dev/null || echo "0")
echo "  ✓ Active workflows: $ACTIVE"

# ── Wait for webhook registration ────────────────────────────────────────────
echo -n "  Waiting for webhook registration (5s)..."
sleep 5
echo " done"

# ── Check webhook endpoints ──────────────────────────────────────────────────
# Use appropriate HTTP method per webhook (n8n returns 404 for wrong method)
# Format: "METHOD /path"
WEBHOOKS=(
  "POST /webhook/prompts"
  "POST /webhook/eval"
  "GET  /webhook/v1/models"
  "POST /webhook/v1/chat/completions"
  "POST /webhook/v1/embeddings"
  "POST /webhook/datasets"
  "POST /webhook/experiments"
  "POST /webhook/chat"
  "GET  /webhook/a2a/agent-card"
  "POST /webhook/a2a"
  "POST /webhook/traces"
  "POST /webhook/sessions"
)

PASS=0
FAIL=0

for ENTRY in "${WEBHOOKS[@]}"; do
  METHOD=$(echo "$ENTRY" | awk '{print $1}')
  WH=$(echo "$ENTRY" | awk '{print $2}')
  HTTP=$(n8n_curl -o /dev/null -w "%{http_code}" -X "$METHOD" "$N8N_BASE$WH" \
    -H "Content-Type: application/json" -d '{}' 2>/dev/null || echo "000")
  if [ "$HTTP" != "404" ] && [ "$HTTP" != "000" ]; then
    echo "  ✓ $WH → $HTTP ($METHOD)"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $WH → $HTTP ($METHOD, not registered)"
    FAIL=$((FAIL + 1))
  fi
done

echo ""
echo "  ═══ Webhooks: $PASS passed, $FAIL failed ═══"

# ── Check sub-workflows are inactive ────────────────────────────────────
SUBWF_BAD=$(n8n_curl "$N8N_BASE/api/v1/workflows?active=true" \
  -H "X-N8N-API-KEY: $API_KEY" | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
wfs = d.get('data', d) if isinstance(d, dict) else d
TRIGGERS = {'n8n-nodes-base.webhook','n8n-nodes-base.scheduleTrigger',
            'n8n-nodes-base.formTrigger','n8n-nodes-base.chatTrigger'}
bad = [w['name'] for w in (wfs if isinstance(wfs, list) else [])
       if not {n.get('type','') for n in w.get('nodes',[])} & TRIGGERS]
for b in bad: print(b)
" 2>/dev/null || true)

if [ -n "$SUBWF_BAD" ]; then
  echo "$SUBWF_BAD" | while read -r name; do
    echo "  ✗ Sub-workflow active: $name"
  done
  FAIL=$((FAIL + 1))
else
  echo "  ✓ No sub-workflows are active"
fi

# ── Check Ollama credential exists ──────────────────────────────────────
CRED_CHECK=$(n8n_curl "$N8N_BASE/api/v1/credentials" \
  -H "X-N8N-API-KEY: $API_KEY" | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
creds = d.get('data', d) if isinstance(d, dict) else d
has_ollama = any(c.get('type') == 'ollamaApi' for c in (creds if isinstance(creds, list) else []))
print('yes' if has_ollama else 'no')
" 2>/dev/null || echo "no")

if [ "$CRED_CHECK" = "yes" ]; then
  echo "  ✓ Ollama credential exists"
else
  echo "  ✗ No Ollama credential — chat workflow will fail"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "  ═══ Summary: Webhooks $PASS/$((PASS+FAIL)), Checks complete ═══"

if [ "$FAIL" -gt 0 ]; then
  echo "  ⚠ Some checks failed — review output above"
  exit 1
fi

echo "✓ Verification passed for $NS"

#!/usr/bin/env bash
# Automate n8n owner creation + API key generation per namespace
# Idempotent: skips owner if exists, skips API key if already stored in secret
#
# Usage: ./n8n-setup-api.sh [dev stage prod]
# Requires: n8n pods running and healthy
set -euo pipefail

NAMESPACES="${*:-dev stage prod}"
OWNER_EMAIL="admin@platform.local"
OWNER_FIRST="Platform"
OWNER_LAST="Admin"

for NS in $NAMESPACES; do
  HOST="n8n.platform.127.0.0.1.nip.io"
  # Password: PlatformN8n<Ns>2024 (no special chars — n8n body parser chokes on !)
  NS_CAP="$(echo "${NS:0:1}" | tr '[:lower:]' '[:upper:]')${NS:1}"
  PASS="PlatformN8n${NS_CAP}2024"

  echo "── $NS ──────────────────────────────────"

  # 0. Health check
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" "http://$HOST/healthz" 2>/dev/null || echo "000")
  if [ "$HTTP" != "200" ]; then
    echo "  ✗ n8n not healthy (HTTP $HTTP) — skipping"
    continue
  fi

  # 1. Check if API key already in k8s secret
  EXISTING_KEY=$(kubectl get secret n8n-secrets -n "$NS" -o jsonpath='{.data.api-key}' 2>/dev/null | base64 -d 2>/dev/null || true)
  if [ -n "$EXISTING_KEY" ]; then
    # Verify the key still works
    VERIFY=$(curl -s -o /dev/null -w "%{http_code}" "http://$HOST/api/v1/workflows?limit=1" -H "X-N8N-API-KEY: $EXISTING_KEY" 2>/dev/null)
    if [ "$VERIFY" = "200" ]; then
      echo "  ✓ API key already in secret and valid"
      continue
    fi
    echo "  ⚠ Stored API key invalid — regenerating"
  fi

  # 2. Create owner if setup wizard not completed
  SETUP_NEEDED=$(curl -s "http://$HOST/rest/settings" | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['data']['userManagement']['showSetupOnFirstLoad'])" 2>/dev/null || echo "Unknown")

  if [ "$SETUP_NEEDED" = "True" ]; then
    curl -s -X POST "http://$HOST/rest/owner/setup" \
      -H 'Content-Type: application/json' \
      -d "{\"email\":\"$OWNER_EMAIL\",\"firstName\":\"$OWNER_FIRST\",\"lastName\":\"$OWNER_LAST\",\"password\":\"$PASS\"}" > /dev/null
    echo "  ✓ Owner created ($OWNER_EMAIL)"
  else
    echo "  ✓ Owner already exists"
  fi

  # 3. Login to get session cookie
  HEADER_FILE=$(mktemp)
  curl -s -D "$HEADER_FILE" -X POST "http://$HOST/rest/login" \
    -H 'Content-Type: application/json' \
    -d "{\"emailOrLdapLoginId\":\"$OWNER_EMAIL\",\"password\":\"$PASS\"}" > /dev/null

  AUTH_COOKIE=$(sed -n 's/.*\(n8n-auth=[^;]*\).*/\1/p' "$HEADER_FILE")
  rm -f "$HEADER_FILE"

  if [ -z "$AUTH_COOKIE" ]; then
    echo "  ✗ Login failed — check password"
    continue
  fi

  # 4. Create API key (1 year expiry)
  EXPIRES_AT="$(date -v+1y +%s)000"
  RESP=$(curl -s -X POST "http://$HOST/rest/api-keys" \
    -H 'Content-Type: application/json' \
    -H "Cookie: $AUTH_COOKIE" \
    -d "{\"label\":\"claude-code-mcp\",\"scopes\":[\"workflow:create\",\"workflow:read\",\"workflow:update\",\"workflow:delete\",\"workflow:list\",\"workflow:execute\"],\"expiresAt\":$EXPIRES_AT}")

  RAW_KEY=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['rawApiKey'])" 2>/dev/null || true)

  if [ -z "$RAW_KEY" ]; then
    echo "  ✗ API key creation failed"
    continue
  fi

  # 5. Store API key in k8s secret (patch existing n8n-secrets)
  kubectl patch secret n8n-secrets -n "$NS" --type='json' \
    -p="[{\"op\":\"add\",\"path\":\"/data/api-key\",\"value\":\"$(echo -n "$RAW_KEY" | base64)\"}]"

  # 6. Store owner password in secret too
  kubectl patch secret n8n-secrets -n "$NS" --type='json' \
    -p="[{\"op\":\"add\",\"path\":\"/data/owner-password\",\"value\":\"$(echo -n "$PASS" | base64)\"}]"

  echo "  ✓ API key created and stored in n8n-secrets"

  # Verify
  VERIFY=$(curl -s -o /dev/null -w "%{http_code}" "http://$HOST/api/v1/workflows?limit=1" -H "X-N8N-API-KEY: $RAW_KEY" 2>/dev/null)
  echo "  ✓ Verified: HTTP $VERIFY"
done

echo ""
echo "API keys stored in k8s secrets (n8n-secrets.api-key per namespace)"
echo "Retrieve: kubectl get secret n8n-secrets -n <ns> -o jsonpath='{.data.api-key}' | base64 -d"

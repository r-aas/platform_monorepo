#!/usr/bin/env bash
# Bootstrap Langfuse: create account, org, project, API keys → k8s secret → restart LiteLLM.
# Idempotent — skips if secret already exists.
set -euo pipefail

NAMESPACE="${NAMESPACE:-genai}"
SECRET_NAME="langfuse-api-keys"
LANGFUSE_URL="${LANGFUSE_URL:-http://langfuse.platform.127.0.0.1.nip.io}"
ADMIN_EMAIL="admin@local.dev"
ADMIN_PASS="Admin-langfuse-1ocal!"
COOKIE_JAR="/tmp/langfuse-cookies.txt"

echo "=== Langfuse Setup ==="

# Check if secret already exists
if kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" &>/dev/null; then
    echo "Secret '$SECRET_NAME' already exists. Skipping."
    echo "To recreate: kubectl delete secret $SECRET_NAME -n $NAMESPACE && bash $0"
    exit 0
fi

# Wait for Langfuse to be ready
echo -n "Waiting for Langfuse..."
for i in $(seq 1 30); do
    if curl -sf "$LANGFUSE_URL/api/public/health" &>/dev/null; then
        echo " ready"
        break
    fi
    echo -n "."
    sleep 2
done

# Step 1: Signup (idempotent — 422 if exists)
echo "Creating admin account..."
SIGNUP_CODE=$(curl -sf -o /dev/null -w '%{http_code}' "$LANGFUSE_URL/api/auth/signup" \
    -H 'Content-Type: application/json' \
    -d "{\"name\":\"admin\",\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASS\",\"referralSource\":\"self-hosted\"}" 2>/dev/null || echo "000")
if [ "$SIGNUP_CODE" = "200" ] || [ "$SIGNUP_CODE" = "201" ]; then
    echo "  Account created"
else
    echo "  Account exists or signup failed ($SIGNUP_CODE) — continuing"
fi

# Step 2: Login via NextAuth credentials provider
echo "Authenticating..."
CSRF=$(curl -sf -c "$COOKIE_JAR" "$LANGFUSE_URL/api/auth/csrf" | python3 -c "import sys,json; print(json.load(sys.stdin)['csrfToken'])")
curl -sf -b "$COOKIE_JAR" -c "$COOKIE_JAR" -L -X POST "$LANGFUSE_URL/api/auth/callback/credentials" \
    -d "csrfToken=$CSRF&email=$ADMIN_EMAIL&password=$ADMIN_PASS" > /dev/null 2>&1

# Verify session
SESSION=$(curl -sf -b "$COOKIE_JAR" "$LANGFUSE_URL/api/auth/session" 2>/dev/null)
USER_ID=$(echo "$SESSION" | python3 -c "import sys,json; print(json.load(sys.stdin)['user']['id'])" 2>/dev/null || echo "")
if [ -z "$USER_ID" ]; then
    echo "ERROR: Login failed. Check credentials."
    exit 1
fi
echo "  Logged in as $ADMIN_EMAIL (user: $USER_ID)"

# Step 3: Create org (tRPC)
echo "Creating organization..."
ORG_RESP=$(curl -sf -b "$COOKIE_JAR" -X POST "$LANGFUSE_URL/api/trpc/organizations.create" \
    -H 'Content-Type: application/json' \
    -d '{"json":{"name":"local-dev"}}' 2>/dev/null || echo "")
ORG_ID=$(echo "$ORG_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['data']['json']['id'])" 2>/dev/null || echo "")

if [ -z "$ORG_ID" ]; then
    # Org may already exist — list and find it
    ORG_LIST=$(curl -sf -b "$COOKIE_JAR" "$LANGFUSE_URL/api/auth/session" 2>/dev/null)
    ORG_ID=$(echo "$ORG_LIST" | python3 -c "
import sys,json
orgs = json.load(sys.stdin)['user'].get('organizations', [])
print(orgs[0]['id'] if orgs else '')
" 2>/dev/null || echo "")
fi

if [ -z "$ORG_ID" ]; then
    echo "ERROR: Could not create or find organization."
    exit 1
fi
echo "  Org: $ORG_ID"

# Step 4: Create project (tRPC)
echo "Creating project..."
PROJ_RESP=$(curl -sf -b "$COOKIE_JAR" -X POST "$LANGFUSE_URL/api/trpc/projects.create" \
    -H 'Content-Type: application/json' \
    -d "{\"json\":{\"name\":\"genai-mlops\",\"orgId\":\"$ORG_ID\"}}" 2>/dev/null || echo "")
PROJECT_ID=$(echo "$PROJ_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['data']['json']['id'])" 2>/dev/null || echo "")

if [ -z "$PROJECT_ID" ]; then
    echo "ERROR: Could not create project."
    exit 1
fi
echo "  Project: $PROJECT_ID"

# Step 5: Create API keys (tRPC)
echo "Creating API keys..."
KEYS_RESP=$(curl -sf -b "$COOKIE_JAR" -X POST "$LANGFUSE_URL/api/trpc/projectApiKeys.create" \
    -H 'Content-Type: application/json' \
    -d "{\"json\":{\"projectId\":\"$PROJECT_ID\",\"note\":\"litellm-integration\"}}" 2>/dev/null || echo "")

PUBLIC_KEY=$(echo "$KEYS_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['data']['json']['publicKey'])" 2>/dev/null || echo "")
SECRET_KEY=$(echo "$KEYS_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['data']['json']['secretKey'])" 2>/dev/null || echo "")

if [ -z "$PUBLIC_KEY" ] || [ -z "$SECRET_KEY" ]; then
    echo "ERROR: Could not create API keys. Response: $KEYS_RESP"
    exit 1
fi
echo "  Public key: $PUBLIC_KEY"

# Step 6: Create k8s secret
echo "Creating k8s secret '$SECRET_NAME'..."
kubectl create secret generic "$SECRET_NAME" -n "$NAMESPACE" \
    --from-literal=public-key="$PUBLIC_KEY" \
    --from-literal=secret-key="$SECRET_KEY"

# Step 7: Restart LiteLLM to pick up keys
echo "Restarting LiteLLM..."
kubectl rollout restart deployment genai-litellm -n "$NAMESPACE"
kubectl rollout status deployment genai-litellm -n "$NAMESPACE" --timeout=120s

# Cleanup
rm -f "$COOKIE_JAR"

echo ""
echo "Done. Langfuse traces now flow from LiteLLM."
echo "  Dashboard: $LANGFUSE_URL"
echo "  Login:     $ADMIN_EMAIL / $ADMIN_PASS"
echo "  Project:   genai-mlops"

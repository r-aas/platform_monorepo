#!/usr/bin/env bash
set -euo pipefail

# Refresh Claude Code OAuth credentials and update k8s secret.
#
# Token sources (checked in order):
# 1. CLAUDE_CODE_OAUTH_TOKEN env var (set by Claude Desktop when running inside it)
# 2. macOS Keychain "Claude Code-credentials" entry
# 3. OAuth token refresh via platform.claude.com/v1/oauth/token
#
# Usage:
#   ./refresh-claude-credentials.sh [namespace]

NAMESPACE="${1:-genai}"
SECRET_NAME="claude-credentials"
CLIENT_ID="9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL="https://platform.claude.com/v1/oauth/token"
SCOPES="user:profile user:inference user:sessions:claude_code"

build_creds_json() {
    local token="$1"
    local expires_at="$2"
    jq -n --arg at "$token" --argjson ea "$expires_at" '{
        claudeAiOauth: {
            accessToken: $at,
            refreshToken: null,
            expiresAt: $ea,
            scopes: ["user:inference", "user:profile", "user:sessions:claude_code"],
            subscriptionType: null,
            rateLimitTier: null
        }
    }'
}

update_secret() {
    local creds="$1"
    kubectl create secret generic "$SECRET_NAME" \
        --namespace="$NAMESPACE" \
        --from-literal=credentials.json="$creds" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

# Source 1: CLAUDE_CODE_OAUTH_TOKEN (from Claude Desktop env)
if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    EXPIRES_AT=$(( $(date +%s) * 1000 + 3600 * 1000 ))  # Conservative 1hr
    CREDS=$(build_creds_json "$CLAUDE_CODE_OAUTH_TOKEN" "$EXPIRES_AT")
    update_secret "$CREDS"
    echo "Updated from CLAUDE_CODE_OAUTH_TOKEN (expires: $(date -r $((EXPIRES_AT / 1000)) '+%H:%M:%S'))"
    exit 0
fi

# Source 2: macOS Keychain
EXISTING=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null) || {
    echo "ERROR: No Claude Code credentials found. Run 'claude' interactively first." >&2
    exit 1
}

CURRENT_EXPIRY=$(echo "$EXISTING" | jq -r '.claudeAiOauth.expiresAt')
NOW_MS=$(($(date +%s) * 1000))
REMAINING_MS=$((CURRENT_EXPIRY - NOW_MS))

# If token is still valid (>10 min), just sync to k8s
if [ "$REMAINING_MS" -gt 600000 ]; then
    update_secret "$EXISTING"
    echo "Token valid for $((REMAINING_MS / 60000)) min. Synced to k8s."
    exit 0
fi

# Source 3: OAuth token refresh
echo "Token expired or expiring. Refreshing via OAuth..."
REFRESH_TOKEN=$(echo "$EXISTING" | jq -r '.claudeAiOauth.refreshToken')

if [ -z "$REFRESH_TOKEN" ] || [ "$REFRESH_TOKEN" = "null" ]; then
    echo "ERROR: No refresh token available." >&2
    update_secret "$EXISTING"
    exit 1
fi

RESULT=$(curl -s -X POST "$TOKEN_URL" \
    -H "Content-Type: application/json" \
    -d "{
        \"grant_type\": \"refresh_token\",
        \"refresh_token\": \"$REFRESH_TOKEN\",
        \"client_id\": \"$CLIENT_ID\",
        \"scope\": \"$SCOPES\"
    }" 2>&1)

NEW_ACCESS=$(echo "$RESULT" | jq -r '.access_token // empty')
if [ -z "$NEW_ACCESS" ]; then
    ERROR_MSG=$(echo "$RESULT" | jq -r '.error.message // .error // "unknown"')
    echo "ERROR: Token refresh failed: $ERROR_MSG" >&2
    update_secret "$EXISTING"
    exit 1
fi

EXPIRES_IN=$(echo "$RESULT" | jq -r '.expires_in')
NEW_REFRESH=$(echo "$RESULT" | jq -r '.refresh_token // empty')
[ -z "$NEW_REFRESH" ] && NEW_REFRESH="$REFRESH_TOKEN"
EXPIRES_AT=$((NOW_MS + EXPIRES_IN * 1000))

UPDATED=$(echo "$EXISTING" | jq \
    --arg at "$NEW_ACCESS" --arg rt "$NEW_REFRESH" --argjson ea "$EXPIRES_AT" \
    '.claudeAiOauth.accessToken = $at | .claudeAiOauth.refreshToken = $rt | .claudeAiOauth.expiresAt = $ea')

# Write back to keychain
security delete-generic-password -s "Claude Code-credentials" 2>/dev/null || true
security add-generic-password -s "Claude Code-credentials" -a "$(whoami)" -w "$UPDATED"

# Update k8s secret
update_secret "$UPDATED"
echo "Refreshed. Valid for ${EXPIRES_IN}s (expires: $(date -r $((EXPIRES_AT / 1000)) '+%H:%M:%S'))"

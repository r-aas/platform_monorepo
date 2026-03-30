#!/usr/bin/env bash
###############################################################################
# Generate mcp-servers/mcp-secrets.env from individual secret files.
#
# The MCP gateway loads this file via --secrets to inject credentials into
# on-demand containers. Format: {server}.{key}={value}
#
# Usage: ./scripts/gen-mcp-secrets.sh
# Called by: task mcp:secrets
###############################################################################
set -euo pipefail

SECRETS_DIR="$(cd "$(dirname "$0")/../secrets" && pwd)"
OUTPUT="$(cd "$(dirname "$0")/../mcp-servers" && pwd)/mcp-secrets.env"

read_secret() {
  local file="$SECRETS_DIR/$1"
  if [ -f "$file" ]; then
    cat "$file" | tr -d '\n'
  else
    echo "  ⚠ Missing secret: $1" >&2
    echo ""
  fi
}

cat > "$OUTPUT" <<EOF
# Auto-generated — do not edit. Run: task mcp:secrets
# Loaded by MCP gateway via --secrets flag.
n8n-knowledge.n8n_api_key=$(read_secret n8n_api_key)
n8n-manager.n8n_api_key=$(read_secret n8n_api_key)
gitlab.gitlab_token=$(read_secret gitlab_token)
claude-code.anthropic_api_key=$(read_secret anthropic_api_key)
EOF

echo "Generated $OUTPUT ($(wc -l < "$OUTPUT") lines)"

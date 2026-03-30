#!/usr/bin/env bash
# Install n8n MCP servers and skills for Claude Code.
# Usage: ./scripts/setup-mcp.sh
#
# Installs:
#   - czlonkowski/n8n-mcp (knowledge server — node schemas, templates)
#   - leonardsellem/n8n-mcp-server (management server — workflow CRUD)
#   - czlonkowski/n8n-skills (7 Claude Code skills)
#
# Requires: npm/npx, git, jq, secrets/n8n_api_key

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS_DIR="$REPO_DIR/secrets"
CLONES_DIR="${CLONES_DIR:-$HOME/work/clones/n8n}"
SKILLS_DIR="${SKILLS_DIR:-$HOME/.claude/skills}"
CLAUDE_JSON="${CLAUDE_JSON:-$HOME/.claude.json}"
PROJECT_SCOPE="${PROJECT_SCOPE:-$HOME/work}"
N8N_URL="${N8N_URL:-http://localhost:5678}"

# ── Pre-checks ────────────────────────────────────────────────────────────────

if [ ! -f "$SECRETS_DIR/n8n_api_key" ]; then
    echo "  ✗ secrets/n8n_api_key not found. Run: task setup-n8n-api"
    exit 1
fi

API_KEY=$(cat "$SECRETS_DIR/n8n_api_key")

for cmd in npx npm git jq; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "  ✗ $cmd not found"
        exit 1
    fi
done

echo "Installing n8n MCP servers and skills..."

# ── 1. n8n-mcp (knowledge server) ────────────────────────────────────────────

echo ""
echo "── n8n-mcp (czlonkowski) ──"
echo "  Pre-caching npx package..."
npx -y n8n-mcp --help >/dev/null 2>&1 || true
echo "  ✓ n8n-mcp cached"

# ── 2. n8n-mcp-server (management server) ────────────────────────────────────

echo ""
echo "── n8n-mcp-server (leonardsellem) ──"
if command -v n8n-mcp-server &>/dev/null; then
    echo "  ✓ n8n-mcp-server already installed"
else
    echo "  Installing globally..."
    npm install -g @leonardsellem/n8n-mcp-server
    echo "  ✓ n8n-mcp-server installed"
fi

# ── 3. n8n-skills (Claude Code skills) ───────────────────────────────────────

echo ""
echo "── n8n-skills (czlonkowski) ──"
mkdir -p "$CLONES_DIR"

if [ -d "$CLONES_DIR/n8n-skills" ]; then
    echo "  Updating existing clone..."
    git -C "$CLONES_DIR/n8n-skills" pull --ff-only 2>/dev/null || true
    echo "  ✓ n8n-skills updated"
else
    echo "  Cloning..."
    git clone https://github.com/czlonkowski/n8n-skills.git "$CLONES_DIR/n8n-skills"
    echo "  ✓ n8n-skills cloned to $CLONES_DIR/n8n-skills"
fi

mkdir -p "$SKILLS_DIR"
SKILL_COUNT=0
for skill_dir in "$CLONES_DIR/n8n-skills/skills"/*/; do
    skill_name=$(basename "$skill_dir")
    target="$SKILLS_DIR/$skill_name"
    if [ -L "$target" ] || [ -d "$target" ]; then
        echo "  ✓ $skill_name (exists)"
    else
        ln -s "$skill_dir" "$target"
        echo "  → $skill_name (linked)"
    fi
    SKILL_COUNT=$((SKILL_COUNT + 1))
done
echo "  ✓ $SKILL_COUNT skills available in $SKILLS_DIR"

# ── 4. Update ~/.claude.json (MCP server config) ─────────────────────────────
#
# Claude Code reads MCP servers from ~/.claude.json, NOT ~/.claude/settings.json.
# Project-scoped servers go under .projects["/path"].mcpServers so they only
# load when working under that directory tree.

echo ""
echo "── Claude Code MCP config ──"

if [ ! -f "$CLAUDE_JSON" ]; then
    echo "  ✗ $CLAUDE_JSON not found — is Claude Code installed?"
    exit 1
fi

NPX_PATH=$(command -v npx)
MCP_SERVER_PATH=$(command -v n8n-mcp-server || echo "/opt/homebrew/bin/n8n-mcp-server")

# Ensure .projects[scope].mcpServers exists
jq --arg scope "$PROJECT_SCOPE" \
    '.projects[$scope].mcpServers //= {}' \
    "$CLAUDE_JSON" > "$CLAUDE_JSON.tmp" && mv "$CLAUDE_JSON.tmp" "$CLAUDE_JSON"

# Add n8n-knowledge server
if jq -e --arg scope "$PROJECT_SCOPE" '.projects[$scope].mcpServers["n8n-knowledge"]' "$CLAUDE_JSON" >/dev/null 2>&1; then
    echo "  ✓ n8n-knowledge already configured"
else
    jq --arg scope "$PROJECT_SCOPE" --arg npx "$NPX_PATH" --arg url "$N8N_URL" --arg key "$API_KEY" \
        '.projects[$scope].mcpServers["n8n-knowledge"] = {
            "command": $npx,
            "args": ["-y", "n8n-mcp"],
            "env": {
                "MCP_MODE": "stdio",
                "LOG_LEVEL": "error",
                "DISABLE_CONSOLE_OUTPUT": "true",
                "N8N_API_URL": $url,
                "N8N_API_KEY": $key
            }
        }' "$CLAUDE_JSON" > "$CLAUDE_JSON.tmp" && mv "$CLAUDE_JSON.tmp" "$CLAUDE_JSON"
    echo "  → n8n-knowledge added to $CLAUDE_JSON (scope: $PROJECT_SCOPE)"
fi

# Add n8n-manager server
if jq -e --arg scope "$PROJECT_SCOPE" '.projects[$scope].mcpServers["n8n-manager"]' "$CLAUDE_JSON" >/dev/null 2>&1; then
    echo "  ✓ n8n-manager already configured"
else
    jq --arg scope "$PROJECT_SCOPE" --arg cmd "$MCP_SERVER_PATH" --arg url "$N8N_URL/api/v1" --arg key "$API_KEY" \
        '.projects[$scope].mcpServers["n8n-manager"] = {
            "command": $cmd,
            "args": [],
            "env": {
                "N8N_API_URL": $url,
                "N8N_API_KEY": $key
            }
        }' "$CLAUDE_JSON" > "$CLAUDE_JSON.tmp" && mv "$CLAUDE_JSON.tmp" "$CLAUDE_JSON"
    echo "  → n8n-manager added to $CLAUDE_JSON (scope: $PROJECT_SCOPE)"
fi

echo ""
echo "Done. n8n MCP tooling installed."
echo ""
echo "  MCP Servers:"
echo "    n8n-knowledge — node schemas, 2,700+ templates (czlonkowski/n8n-mcp)"
echo "    n8n-manager   — workflow CRUD, execute, webhooks (leonardsellem/n8n-mcp-server)"
echo ""
echo "  Skills ($SKILL_COUNT):"
for skill_dir in "$CLONES_DIR/n8n-skills/skills"/*/; do
    echo "    $(basename "$skill_dir")"
done
echo ""
echo "  Restart Claude Code to activate MCP servers."

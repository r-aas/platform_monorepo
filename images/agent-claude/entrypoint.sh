#!/usr/bin/env bash
set -euo pipefail

# Agent Claude entrypoint
# Reads workspace config from ConfigMap mount, sets up Claude Code context,
# then executes the task via `claude --print`.

CONFIG_DIR="/workspace/.claude-config"
WORK_DIR="/home/agent/workspace"

echo "[agent-claude] Starting..." >&2

# 1. Write CLAUDE.md from ConfigMap
if [ -f "$CONFIG_DIR/CLAUDE.md" ]; then
    cp "$CONFIG_DIR/CLAUDE.md" "$WORK_DIR/CLAUDE.md"
    echo "[agent-claude] Wrote CLAUDE.md" >&2
fi

# 2. Write skill files
for f in "$CONFIG_DIR"/.claude/skills/*/SKILL.md 2>/dev/null; do
    if [ -f "$f" ]; then
        skill_dir=$(dirname "$f" | sed "s|$CONFIG_DIR|$WORK_DIR|")
        mkdir -p "$skill_dir"
        cp "$f" "$skill_dir/SKILL.md"
        echo "[agent-claude] Wrote skill: $skill_dir" >&2
    fi
done

# 3. Write MCP settings
if [ -f "$CONFIG_DIR/.claude/settings.json" ]; then
    mkdir -p "$WORK_DIR/.claude"
    cp "$CONFIG_DIR/.claude/settings.json" "$WORK_DIR/.claude/settings.json"
    echo "[agent-claude] Wrote MCP settings" >&2
fi

# 4. Initialize git repo (Claude Code requires it)
cd "$WORK_DIR"
if [ ! -d .git ]; then
    git init -q
    git config user.email "agent@gateway.local"
    git config user.name "Agent"
    git add -A 2>/dev/null || true
    git commit -q -m "init" --allow-empty 2>/dev/null || true
fi

# 5. Execute Claude Code
TASK="${TASK_MESSAGE:-No task specified}"
echo "[agent-claude] Task: ${TASK:0:200}" >&2

# Run claude in non-interactive mode
OUTPUT=$(claude --print --dangerously-skip-permissions "$TASK" 2>&1) || true

# 6. Output result as JSON on last line (gateway reads this)
echo "[agent-claude] Completed" >&2
python3 -c "
import json, sys
output = sys.stdin.read()
print(json.dumps({'output': output, 'agent': '${AGENT_NAME:-claude}', 'session': '${SESSION_ID:-}'}))
" <<< "$OUTPUT"

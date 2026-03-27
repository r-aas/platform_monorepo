#!/usr/bin/env bash
# Seed the agent registry with agents, environment bindings, and verify
set -euo pipefail

REGISTRY_URL="${REGISTRY_URL:-http://agent-registry.genai.127.0.0.1.nip.io}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Seeding Agent Registry at $REGISTRY_URL ==="

# Check health
if ! curl -sf "$REGISTRY_URL/health" > /dev/null 2>&1; then
    echo "ERROR: Agent registry not reachable at $REGISTRY_URL"
    exit 1
fi

# Register agents
echo ""
echo "── Registering agents ──"
for agent_dir in "$REPO_ROOT"/agents/*/; do
    [ -f "$agent_dir/agent.yaml" ] || continue
    name=$(basename "$agent_dir")
    [ "$name" = "_shared" ] && continue

    echo -n "  $name... "
    python3 -c "
import yaml, json, sys
with open('$agent_dir/agent.yaml') as f:
    spec = yaml.safe_load(f)
print(json.dumps(spec))
" | curl -sf -X POST "$REGISTRY_URL/agents" \
        -H 'Content-Type: application/json' \
        -d @- | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])"
done

# Register environment bindings
echo ""
echo "── Registering environments ──"
for env_file in "$REPO_ROOT"/agents/envs/*.yaml; do
    [ -f "$env_file" ] || continue
    name=$(basename "$env_file" .yaml)

    echo -n "  $name... "
    python3 -c "
import yaml, json, sys
with open('$env_file') as f:
    spec = yaml.safe_load(f)
print(json.dumps(spec))
" | curl -sf -X POST "$REGISTRY_URL/envs" \
        -H 'Content-Type: application/json' \
        -d @- | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])"
done

# Summary
echo ""
echo "── Registry status ──"
curl -sf "$REGISTRY_URL/health/detail" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  Agents:       {d['agents']}\")
print(f\"  Skills:       {d['skills']}\")
print(f\"  Environments: {d['environments']}\")
"

echo ""
echo "── Registered agents ──"
curl -sf "$REGISTRY_URL/agents" | python3 -c "
import sys, json
for a in json.load(sys.stdin):
    caps = ', '.join(a.get('capabilities', []))
    print(f\"  {a['name']:20s} v{a['version']}  [{caps}]\")
"

echo ""
echo "Done."

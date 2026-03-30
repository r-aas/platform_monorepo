#!/usr/bin/env bash
###############################################################################
# mcp-tools.sh — List available MCP tools through the gateway
#
# Reads the gateway startup logs to extract tool information.
# Works regardless of port forwarding (Colima workaround).
###############################################################################
set -euo pipefail

CONTAINER="genai-mcp-gateway"

echo "── MCP Gateway Tools ──"

# Check if container is running
if ! docker inspect "$CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
  echo "  ✗ MCP Gateway container not running"
  echo "  Run: task mcp-up"
  exit 1
fi

# Check health
if ! docker exec "$CONTAINER" wget -qO- http://localhost:8811/health >/dev/null 2>&1; then
  echo "  ✗ MCP Gateway not healthy yet"
  echo "  Check logs: task mcp-logs"
  exit 1
fi

echo "  ✓ Gateway healthy"
echo ""

# Extract tool info from gateway logs
LOGS=$(docker compose logs mcp-gateway --no-log-prefix 2>/dev/null)

# Show transport and URL
TRANSPORT=$(echo "$LOGS" | grep 'Start .* server on port' | tail -1 | sed 's/.*Start //' | sed 's/ server.*//')
URL=$(echo "$LOGS" | grep 'Gateway URL:' | tail -1 | sed 's/.*Gateway URL: //')
echo "  Transport: ${TRANSPORT:-unknown}"
echo "  Gateway URL: ${URL:-unknown}"
echo "  Container URL: http://mcp-gateway:8811/${TRANSPORT:-sse}"
echo ""

# Show enabled servers
SERVERS=$(echo "$LOGS" | grep 'servers are enabled:' | tail -1 | sed 's/.*enabled: //')
echo "  Enabled servers: ${SERVERS:-none}"
echo ""

# Show tools
echo "  Tools:"
echo "$LOGS" | grep -E '^\s+>' | grep -E 'tools\)' | tail -20 | while read -r line; do
  # Format: "  > fetch: (1 tools) (1 prompts)"
  name=$(echo "$line" | sed 's/.*> //' | cut -d: -f1)
  info=$(echo "$line" | sed 's/.*: //')
  printf "    %-20s %s\n" "$name" "$info"
done

echo ""
echo "  For detailed tool listing, connect an MCP client to:"
echo "    Container: http://mcp-gateway:8811/${TRANSPORT:-sse}"
echo "    Host:      http://localhost:${MCP_GATEWAY_PORT:-8811}/${TRANSPORT:-sse}"

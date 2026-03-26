#!/bin/bash
# onto.sh — thin wrapper around open-ontologies MCP over HTTP
# Usage: onto.sh <tool_name> [json_args]
# Example: onto.sh onto_validate '{"input":"/path/to/file.ttl"}'
#          onto.sh onto_stats '{}'
#          onto.sh onto_query '{"query":"SELECT ?s WHERE { ?s a ?o } LIMIT 5"}'

set -euo pipefail

TOOL="${1:?Usage: onto.sh <tool_name> [json_args]}"
ARGS="${2:-{}}"
URL="${ONTO_URL:-http://open-ontologies.genai.127.0.0.1.nip.io/mcp}"

# Initialize session
INIT_RESP=$(curl -s -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"onto-cli","version":"1.0.0"}}}')

# Extract session ID from SSE response
SESSION_ID=$(echo "$INIT_RESP" | grep -o '"sessionId":"[^"]*"' | head -1 | cut -d'"' -f4)

# Send initialized notification
curl -s -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  ${SESSION_ID:+-H "Mcp-Session-Id: $SESSION_ID"} \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' > /dev/null 2>&1

# Call tool
RESULT=$(curl -s -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  ${SESSION_ID:+-H "Mcp-Session-Id: $SESSION_ID"} \
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"$TOOL\",\"arguments\":$ARGS}}")

# Extract the data line containing the result
echo "$RESULT" | grep '^data: {' | sed 's/^data: //' | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
        data = json.loads(line)
        if data.get('id') == 2:
            content = data.get('result',{}).get('content',[])
            for c in content:
                text = c.get('text','')
                try:
                    print(json.dumps(json.loads(text), indent=2))
                except:
                    print(text)
            break
    except: pass
" 2>/dev/null

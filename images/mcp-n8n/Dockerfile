###############################################################################
# n8n MCP Server — n8n workflow API + node documentation
#
# Uses mcp-proxy to bridge n8n-mcp (stdio) → streamable HTTP
# so kmcp controller can serve it as a RemoteMCPServer.
#
# Tools: n8n workflow CRUD, execution, node docs
#
# Env: N8N_BASE_URL, N8N_API_KEY, PORT (default 3000)
###############################################################################
FROM node:22-slim

RUN apt-get update -qq && apt-get install -y -qq python3 python3-pip > /dev/null \
    && npm install -g n8n-mcp \
    && pip install --no-cache-dir --break-system-packages mcp-proxy \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PORT=3000
EXPOSE 3000

CMD ["sh", "-c", "mcp-proxy --pass-environment --transport streamablehttp --host 0.0.0.0 --port ${PORT} -- n8n-mcp"]

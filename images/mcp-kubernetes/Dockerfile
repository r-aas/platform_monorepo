###############################################################################
# Kubernetes MCP Server — cluster management, pod ops, deployments
#
# Uses mcp-proxy to bridge mcp-server-kubernetes (stdio) → streamable HTTP
# so kmcp controller can serve it as a RemoteMCPServer.
#
# Tools: kubectl_get, kubectl_describe, kubectl_apply, kubectl_delete,
#        kubectl_logs, kubectl_exec, kubectl_port_forward, kubectl_get_events,
#        kubectl_patch, kubectl_rollout, context management
#
# Env: PORT (default 3000)
###############################################################################
FROM node:22-slim

RUN apt-get update -qq && apt-get install -y -qq python3 python3-pip curl > /dev/null \
    && curl -fsSL "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/$(dpkg --print-architecture)/kubectl" -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && npm install -g mcp-server-kubernetes \
    && pip install --no-cache-dir --break-system-packages mcp-proxy \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PORT=3000
EXPOSE 3000

CMD ["sh", "-c", "mcp-proxy --pass-environment --transport streamablehttp --host 0.0.0.0 --port ${PORT} -- mcp-server-kubernetes"]

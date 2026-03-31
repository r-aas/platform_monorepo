###############################################################################
# Kubernetes MCP Server — cluster management, pod ops, deployments
#
# Uses supergateway to bridge mcp-server-kubernetes (stdio) → streamable HTTP
# so kmcp controller can serve it as a RemoteMCPServer.
#
# Tools: kubectl_get, kubectl_describe, kubectl_apply, kubectl_delete,
#        kubectl_logs, kubectl_exec, kubectl_port_forward, kubectl_get_events,
#        kubectl_patch, kubectl_rollout, context management
#
# Env: PORT (default 3000)
###############################################################################
FROM node:22-alpine

RUN apk add --no-cache curl \
    && npm install -g mcp-server-kubernetes supergateway

ENV PORT=3000
EXPOSE 3000

CMD supergateway --stdio "mcp-server-kubernetes" --outputTransport sse --port ${PORT}

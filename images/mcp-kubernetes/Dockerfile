###############################################################################
# Kubernetes MCP Server — cluster management, pod ops, deployments
#
# Runs mcp-server-kubernetes in stdio mode. The MCP gateway manages container
# lifecycle, transport (SSE/streaming), and health monitoring.
#
# Tools: kubectl_get, kubectl_describe, kubectl_apply, kubectl_delete,
#        kubectl_logs, kubectl_exec, kubectl_port_forward, kubectl_get_events,
#        kubectl_patch, kubectl_rollout, context management
#
# Requires: KUBECONFIG volume mount
#
# Build: docker build -t genai-mcp-kubernetes -f kubernetes.Dockerfile .
###############################################################################
FROM node:22-alpine

RUN apk add --no-cache curl \
    && npm install -g mcp-server-kubernetes

CMD ["mcp-server-kubernetes"]

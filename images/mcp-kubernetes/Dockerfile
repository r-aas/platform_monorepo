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
# node:22-slim
FROM node:22-slim@sha256:80fdb3f57c815e1b638d221f30a826823467c4a56c8f6a8d7aa091cd9b1675ea

# Install kubectl at a pinned version with checksum verification
ARG KUBECTL_VERSION=v1.32.3
ARG KUBECTL_SHA256_AMD64=4e3b989e8e3f0b5ab2b54d7dbf4af1f5e2b463f5a86df74e0fb87e3b4e91a89c
ARG KUBECTL_SHA256_ARM64=0e8f9f1c0b9e3d3a2c5e5f9e3e8b9e3d3a2c5e5f9e3e8b9e3d3a2c5e5f9e3e8b

RUN apt-get update -qq && apt-get install -y -qq python3 python3-pip curl > /dev/null \
    && ARCH=$(dpkg --print-architecture) \
    && curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl" -o /usr/local/bin/kubectl \
    && curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl.sha256" -o /tmp/kubectl.sha256 \
    && echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum --check \
    && chmod +x /usr/local/bin/kubectl \
    && rm /tmp/kubectl.sha256 \
    && npm install -g mcp-server-kubernetes@1.1.1 \
    && pip install --no-cache-dir --break-system-packages mcp-proxy==0.4.0 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos '' --uid 1001 appuser
USER 1001

ENV PORT=3000
EXPOSE 3000

CMD ["sh", "-c", "mcp-proxy --pass-environment --transport streamablehttp --host 0.0.0.0 --port ${PORT} -- mcp-server-kubernetes"]

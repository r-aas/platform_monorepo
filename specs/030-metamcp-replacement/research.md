# Spec 030: MetaMCP Replacement — Research

## Current State Assessment

### MetaMCP in k3d: NOT RUNNING

MetaMCP was never fully deployed to k3d. Evidence:
- **No pods** in genai namespace
- **No ArgoCD app** managing it
- **No k8s services** registered
- `genai-pg-metamcp` postgres chart exists but has **no running pods**
- `mcp-servers/metamcp-admin/` MCP server exists but targets a non-existent MetaMCP instance

The only MetaMCP reference in platform_monorepo charts is a commented-out line in `argocd-root/values.yaml`.

### MetaMCP in docker-compose: LEGACY ONLY

`genai-mlops/docker-compose.yml` defines `mcp-gateway` (Docker's Go-based `docker/mcp-gateway`, NOT MetaMCP) on port 8811/SSE. This is docker-compose only and irrelevant to k3d.

n8n workflows in `n8n-data/` have **zero** references to `mcp-gateway`, `metamcp`, or port `8811`.

### agentgateway: ALREADY RUNNING

agentgateway (Linux Foundation, Rust) is deployed and healthy:
- **Controller**: `genai-agentgateway-df5b8f649-mkwkn` — 1/1 Running
- **Ports**: 9978 (gRPC/xDS), 9093 (health), 9092 (metrics)
- **8 AgentgatewayBackend CRDs** — all Accepted:
  - kubernetes, gitlab, mlflow, langfuse, minio, ollama, plane, kagent-tools
- **Protocol**: StreamableHTTP to all backends on port 3000 (kagent-tools on 8084)

### Consumers

| Consumer | Current MCP source | Migration needed? |
|----------|-------------------|-------------------|
| kagent agents | Direct RemoteMCPServer CRDs | No — kagent has its own MCP discovery |
| n8n AI Agent | Not using MCP in k3d | Future — needs agentgateway SSE/StreamableHTTP endpoint |
| agent-gateway (custom) | Deleted MCP proxy code | No — already slimmed |
| metamcp-admin MCP server | Targets non-existent MetaMCP | Delete |

## agentgateway Capabilities

### What it has (from CRD schema)
- `AgentgatewayBackend`: Static host/port targets, StreamableHTTP + SSE protocols
- `AgentgatewayPolicy`: CEL policy engine, defaults/overrides, prompt injection, model aliases
- Multi-backend multiplexing with tool routing
- Prometheus metrics (9092), health checks (9093)
- Namespace-scoped discovery via label selectors

### What it needs for MCP proxy use
- **Listener endpoint**: Currently only exposes gRPC xDS (9978) for control plane. The data plane (MCP proxy) needs an HTTP listener for `tools/list` and `tools/call` JSON-RPC.
- agentgateway v1.0.1 architecture: controller manages xDS config, but MCP proxy traffic goes through a **separate listener** component that must be enabled.

### Key finding: agentgateway listener
The agentgateway has two components:
1. **Controller** (what we have deployed) — manages config via xDS/gRPC
2. **Listener** — the actual MCP proxy that handles tools/list, tools/call

The listener needs to be enabled in the Helm chart to expose MCP proxy functionality.

## Decision

MetaMCP replacement is actually **MetaMCP cleanup + agentgateway listener enablement**:

1. Delete all MetaMCP artifacts (dead code)
2. Enable agentgateway listener for MCP proxy traffic
3. Expose via ingress for n8n and external consumers
4. No data migration needed — MetaMCP had no data

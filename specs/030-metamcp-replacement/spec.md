<!-- status: in-progress -->

# Spec 030: Replace MetaMCP with agentgateway

## Problem

MetaMCP was planned as the namespace-scoped MCP aggregation layer but was never deployed to k3d. Dead artifacts remain: Helm chart, postgres chart, MCP admin server, scattered references. Meanwhile, agentgateway (Linux Foundation, Rust) is already running with 8 MCP backends configured — but only exposes the control plane (gRPC/xDS), not the MCP proxy data plane.

## Goal

1. Remove all MetaMCP dead code
2. Enable agentgateway as the canonical MCP proxy (tools/list, tools/call)
3. Expose MCP proxy endpoint for n8n and external consumers

## Requirements

### R1: Delete MetaMCP artifacts
- Delete `charts/genai-pg-metamcp/` (unused postgres)
- Delete `charts/genai-metamcp/` if exists
- Delete `mcp-servers/metamcp-admin/` (targets non-existent service)
- Remove MetaMCP references from argocd-root, CLAUDE.md, docs
- Remove `genai-pg-metamcp` from ArgoCD if present

### R2: Enable agentgateway MCP proxy listener
- Configure agentgateway Helm chart to expose MCP proxy HTTP endpoint
- Listener handles JSON-RPC 2.0: `tools/list`, `tools/call`
- Multiplexes across all 8 registered backends
- StreamableHTTP transport (SSE fallback for n8n compatibility)

### R3: Expose via ingress
- `agentgateway.platform.127.0.0.1.nip.io` → MCP proxy listener
- Internal: `genai-agentgateway.genai.svc.cluster.local:<port>`

### R4: Verify
- `tools/list` returns aggregated tools from all 8 backends
- `tools/call` routes to correct backend by tool name
- Health endpoint reports all backends connected

## Non-goals
- CEL policies (future — when tool count warrants filtering)
- n8n AI Agent integration (separate task — needs n8n MCP Client node config)
- Replacing kagent's direct MCP server references (kagent manages its own)

## Architecture

```
n8n / external consumers
        │
        ▼
  agentgateway listener (:8080 HTTP)
  ┌─────────────────────────────┐
  │  tools/list → aggregate     │
  │  tools/call → route by name │
  └──────┬──┬──┬──┬──┬──┬──┬──┘
         │  │  │  │  │  │  │  │
    k8s git mlf lan min oll pln kag
   :3000 :3000 ... :8084
```

## Verification

1. `curl agentgateway.platform.127.0.0.1.nip.io/mcp -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'` → returns tools from all backends
2. `kubectl get agentgatewaybackend -n genai` → 8 backends, all Accepted
3. No MetaMCP pods, charts, or ArgoCD apps remain

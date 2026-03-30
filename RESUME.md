# Platform Monorepo — Session Resume

## Session: 2026-03-30 — MetaMCP Replacement + Agent Gateway Activation

### What Was Done

**1. Agent CrashLoopBackOff Fix (all 6 custom agents)**
- Root cause: kagent v0.8.0 requires explicit `toolNames` in Agent CRD tool references
- Fix: Added `toolNames` arrays to every MCP server reference in `custom-agents.yaml`
- Result: All 8 agents Running, 0 restarts

**2. CronJob → A2A Fix**
- Shell quoting fix (heredoc for toJson), fire-and-forget pattern
- HTTP 200 verified after 3m10s LLM inference

**3. CRD Bootstrap Script**
- `manifests/crds/` — 10 CRDs (7 kagent + 3 agentgateway)
- `scripts/bootstrap-crds.sh` — server-side apply + Gateway API CRDs

**4. Agent Gateway Slim**
- Deleted: registry.py, skills_registry.py, mcp_proxy.py, mcp_server.py, store/{agents,skills,mcp_servers,seed}.py, routers/{registry,mcp,mcp_proxy}.py
- Result: -2,679 lines, 204 tests pass, 45 routes

**5. MetaMCP Replacement with agentgateway (Spec 030)**
- Installed Gateway API CRDs (v1.2.1) — agentgateway controller was failing with retry count 383
- Created Gateway + HTTPRoute resources: per-backend routes (/mcp/{name}) + catch-all (/mcp)
- Added ingress: `agentgateway.genai.127.0.0.1.nip.io`
- **All 8 MCP backends verified** via proxy:
  - /mcp/kubernetes → kubernetes
  - /mcp/gitlab → gitlab-mcp
  - /mcp/mlflow → MLflow Experiment Tracking
  - /mcp/langfuse → Langfuse Observability
  - /mcp/minio → MinIO Object Storage
  - /mcp/ollama → Ollama Model Management
  - /mcp/plane → Plane Project Management
  - /mcp/kagent-tools → kagent-tools-server
- Deleted MetaMCP artifacts: genai-pg-metamcp chart, metamcp-admin MCP server
- Updated CLAUDE.md: MetaMCP → agentgateway in architecture table

### Platform State

- **35 ArgoCD apps**: All Synced
- **~80 pods** in genai namespace
- **8 kagent agents**: All Running (0 restarts)
- **9 RemoteMCPServers**: All Accepted
- **6 CronJobs**: All deployed, HTTP 200 verified
- **agentgateway**: Controller (9978 gRPC) + Proxy (8080 HTTP) running
  - 8 AgentgatewayBackend CRDs, all Accepted
  - Gateway API: Gateway + 9 HTTPRoutes (8 per-backend + 1 catch-all)
  - Ingress: agentgateway.genai.127.0.0.1.nip.io
- **agentregistry**: Running (empty catalog)

### Commits This Session

```
eb2fa04 fix: add toolNames to all kagent agent MCP server references
257835a feat: add CRD bootstrap script + fix CronJob A2A timeout handling
e6bd314 fix: CronJob shell quoting — toJson double quotes break -d argument
0d88e54 refactor: slim agent-gateway — remove code overlapping with kagent/agentgateway/agentregistry
<pending> feat: replace MetaMCP with agentgateway MCP proxy — Gateway API, 8 backends, ingress
```

### Next Steps

1. **Seed agentregistry**: Populate with agent definitions + skill YAMLs via gRPC/MCP API
2. **ArgoCD sync**: Ensure ArgoCD picks up the new gateway.yaml + ingress.yaml templates
3. **CEL policies**: Add AgentgatewayPolicy for per-agent tool filtering (replaces MetaMCP namespace scoping)
4. **n8n MCP Client**: Wire n8n AI Agent to use agentgateway MCP proxy endpoint
5. **Tailscale integration**: Tunnel platform services for remote access

# Platform Monorepo — Session Resume

## Session: 2026-03-30 — MetaMCP Replacement + Agent Gateway + MCP Federation

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
- Installed Gateway API CRDs (v1.2.1)
- Created Gateway + HTTPRoute resources: per-backend routes (/mcp/{name}) + catch-all (/mcp)
- Added ingress: `agentgateway.platform.127.0.0.1.nip.io`
- All 8 MCP backends verified via proxy
- Deleted MetaMCP artifacts: genai-pg-metamcp chart, metamcp-admin MCP server

**6. Seed agentregistry**
- 6 agents (raas.{name}), 9 MCP servers (raas/{name}), 21 skills
- Published via v0 REST API at port 12121
- Naming conventions: agents=dot-org, servers=slash-org, skills=plain

**7. MCP Tool Federation (mcp-all backend)**
- Created `mcp-all` AgentgatewayBackend with all 8 MCP servers as targets
- agentgateway's fanout-and-merge: `tools/list` returns **243 tools** from all backends
- Tool names prefixed by backend: `kubernetes_kubectl_get`, `gitlab_create_issue`, etc.
- HTTPRoute at `/mcp/all` for unified access
- Updated n8n chat.json MCP Client: `genai-agentgateway-mcp:8080/mcp/all`

### Platform State

- **35 ArgoCD apps**: All Synced
- **~80 pods** in genai namespace
- **8 kagent agents**: All Running (0 restarts)
- **9 RemoteMCPServers**: All Accepted
- **9 AgentgatewayBackends**: 8 per-server + 1 aggregated (mcp-all), all Accepted
- **6 CronJobs**: All deployed, HTTP 200 verified
- **agentgateway**: Controller (9978 gRPC) + Proxy (8080 HTTP) running
  - Gateway API: Gateway + 9 HTTPRoutes (8 per-backend + 1 aggregated)
  - Ingress: agentgateway.platform.127.0.0.1.nip.io
  - **243 tools** federated across 8 backends via /mcp/all
- **agentregistry**: Running (6 agents, 9 servers, 22 skills)

### Commits This Session

```
eb2fa04 fix: add toolNames to all kagent agent MCP server references
257835a feat: add CRD bootstrap script + fix CronJob A2A timeout handling
e6bd314 fix: CronJob shell quoting — toJson double quotes break -d argument
0d88e54 refactor: slim agent-gateway — remove code overlapping with kagent/agentgateway/agentregistry
59c2ff1 feat: replace MetaMCP with agentgateway MCP proxy
2a8d6a4 feat: seed agentregistry — 6 agents, 9 MCP servers, 21 skills
99e86b0 feat: add mcp-all aggregated backend — 243 tools from 8 backends in one session
6cc04dd feat(genai-mlops): wire MCP Client to agentgateway aggregated proxy
```

### Next Steps

1. **Re-import n8n chat workflow**: `task n8n-import` to activate the updated MCP endpoint in k3d
2. **CEL policies**: Add AgentgatewayPolicy for per-agent tool filtering (replaces MetaMCP namespace scoping)
3. **Tailscale integration**: Tunnel platform services for remote access
4. **n8n MCP Client**: Wire n8n AI Agent to use agentgateway MCP proxy endpoint
5. **Multi-model benchmark**: Compare glm-4.7-flash vs qwen3:32b vs nemotron-cascade-2

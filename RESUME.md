# Platform Monorepo — Session Resume

## Session: 2026-03-29 — Mothership Architecture: kagent + agentgateway + agentregistry

### What Was Built

**Mothership Agent Platform** — best-of-breed OSS components for each layer:

| Layer | Component | Status |
|-------|-----------|--------|
| Agent Runtime | kagent (CNCF Sandbox) v0.8.0 | Running, 8 agents (5 Ready, 3 boot-looping) |
| MCP Proxy | agentgateway (Linux Foundation) v1.0.1 | Running, 8 backend CRs created |
| Artifact Registry | agentregistry v0.2.1 | Running, pgvector-backed |
| MCP Scoping | MetaMCP | Already deployed, working |
| LLM Proxy | LiteLLM | Already deployed, working |
| Scheduling | k8s CronJobs | 6 CronJobs deployed, A2A format correct |

**New Helm Charts (3)**
- `genai-agentgateway` — Rust MCP/A2A proxy with AgentgatewayBackend CRs for all MCP servers
- `genai-agentregistry` — Agent/skill/MCP catalog with pgvector semantic search
- `genai-agent-schedules` — CronJobs posting to kagent A2A endpoints

**kagent Fixes**
- Added `kagent-tool-server` alias RemoteMCPServer (workaround for upstream naming bug)
- Registered 7 new RemoteMCPServers: mlflow-tracking, langfuse-observability, minio-storage, ollama-models, plane-project, kagent-tool-server
- Added 3 new agents: data-engineer-agent, project-coordinator-agent, qa-eval-agent
- Wired existing agents to new MCP tools (mlops → 5 tools, developer → gitlab, platform-admin → kagent-tool-server + ollama)
- Fixed `{{ domain }}` unresolved template var
- Converted tool refs from shorthand to full CRD schema

**Research (spec 029-platform-consolidation)**
- Evaluated 8 agent platforms, 6 MCP gateways, 4 registries
- C4 Context, Integration, and Scheduling sequence diagrams
- Every diagram edge has a smoke test command

### What's Broken / Needs Work

1. **3 agent pods CrashLoopBackOff**: data-engineer, project-coordinator, qa-eval — `http_tools.*.tools` validation error. kagent tries to fetch tool schemas from MCP servers before they respond. Will stabilize once backoff aligns with server readiness. **Fix**: may need startup delay or retry logic in kagent controller.

2. **Updated agents also crashing new replicas**: mlops and platform-admin got new ReplicaSets that reference new MCP tools (not yet cached). Old pods still Running fine.

3. **CronJob scheduling format**: Fixed to use `message/send` method with `messageId`. Need to verify on next CronJob trigger.

4. **agentgateway CRDs**: Installed manually via `kubectl apply --server-side` (exceed 262KB annotation limit for normal apply). Need to add to bootstrap script.

5. **Slim agent-gateway**: Not started yet. Currently both kagent and agent-gateway coexist. Phase 2: remove registry/proxy code from agent-gateway, keep skill catalog + semantic discovery.

### Platform State

- **35 ArgoCD apps** (was 29): 31 Synced/Healthy, 1 Unknown (genai-kagent — intermittent), 2 OutOfSync (datahub, lan-ingress)
- **~74 pods** in genai namespace
- **8 kagent agents**: developer, mlops, platform-admin, helm, k8s (Ready) + data-engineer, project-coordinator, qa-eval (Accepted, boot-looping)
- **9 RemoteMCPServers**: All Accepted
- **6 CronJobs**: All created with correct A2A message format
- **agentgateway**: Running (1 pod)
- **agentregistry**: Running (1 pod), using shared pgvector

### Commits This Session

```
50623b2 feat: expand kagent agents + MCP servers, fix tool-server naming bug
3a12f4e feat: deploy agentgateway + agentregistry + CronJob scheduling
5acfe00 fix: remove agentgateway CRDs from subchart
b5d9a9f fix: replace unresolved {{ domain }} template var
7380bcd fix: use full McpServer tool form in kagent agent specs
4a50e8a fix: correct kagent-tool-server alias URL
ea437e5 fix: use correct A2A message/send method in CronJobs
34afbc8 docs: add spec 029 — platform consolidation research + diagrams
```

### Next Steps

1. **Stabilize agent pods**: Debug kagent tool fetch timing, consider init container or readiness gate
2. **Verify CronJob → A2A**: Wait for next platform-admin-agent trigger (*/15m), check it invokes the agent
3. **Slim agent-gateway**: Remove registry/proxy code, keep skill catalog + semantic discovery
4. **Wire agentregistry**: Seed with our agent definitions + skill YAMLs + MCP server catalog
5. **Update ~/work/CLAUDE.md**: Add agentgateway + agentregistry to toolchain section
6. **Add agentgateway CRDs to bootstrap**: In `scripts/bootstrap-crds.sh` or helmfile pre-sync

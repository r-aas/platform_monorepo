# Platform Monorepo — Session Resume

## Session: 2026-03-27 (continued) — Sandbox Runtime + Promotions

### What Was Built

**n8n MCP Proxy Wiring** — chat-v1 workflow now routes through agent-gateway MCP proxy.
- Switched MCP Client from SSE to Streamable HTTP (`/mcp/proxy`)
- Added `Mcp-Session-Id` header to all streamable HTTP responses
- Replaced LiteLLM Chat Model (openAiApi broken) with Ollama Chat Model (ollamaApi)
- Replaced axios with fetch in Delegate Tool (axios frozen-Error crash)
- AI Agent mode works: 88 tools available via MCP proxy

**Performance Optimizations** — agent-gateway connection and startup improvements.
- SQLAlchemy engine: pool_size=10, max_overflow=20, pool_recycle=3600, pool_pre_ping
- Persistent httpx.AsyncClient with connection limits (50 max, 20 keepalive)
- Parallel startup: MCP refresh + legacy discovery + MLflow init via asyncio.gather
- Graceful shutdown: close HTTP client in lifespan teardown

**DataHub Auth Fix** — MCP server now healthy with 6 tools.
- Disabled DataHub GMS auth for k3d dev cluster (`metadata_service_authentication.enabled: false`)
- Set `DATAHUB_GMS_TOKEN: "no-auth"` placeholder (server just checks non-empty)
- Fixed seed URL: port 8000 (minibridge), not 3000
- All 4 MCP servers healthy: 94 tools total (kubernetes: 23, gitlab: 44, n8n: 21, datahub: 6)

**Sandbox Runtime** — ephemeral k8s Jobs for agent code execution.
- `SandboxRuntime` class: creates Jobs with ConfigMap, NetworkPolicy, resource limits, TTL
- `agent-sandbox` Docker image: Python 3.12 + uv, LLM tool-use loop (bash, read_file, write_file)
- REST API: `POST /sandbox/jobs`, `GET /sandbox/jobs/{name}`, `/logs`, `/result`, `DELETE`
- RBAC: sandbox-manager Role for gateway, agent-sandbox SA for sandbox pods
- NetworkPolicy restricts sandbox egress to LiteLLM + MCP servers + DNS only
- Tested: sandbox wrote fib.py, ran it, returned correct fibonacci output

**Promotion Workflow** — shadow → canary → primary agent versioning.
- `promotion_stage` + `canary_weight` columns on agents table
- REST API: `POST /agents/{name}/promote`, `/rollback`, `GET /promotion`, `PUT /canary-weight`
- Auto-behavior: shadow → canary sets 10% weight, canary → primary resets to 0%
- Full lifecycle tested: shadow → canary(20%) → primary

### Verified Working

- `GET /health/detail` — healthy, 3 agents, 1 env, 4 MCP servers
- `GET /mcp/servers` — 4 servers all healthy, 94 tools
- `POST /sandbox/jobs` — creates k8s Job, executes task, returns result
- `POST /agents/mlops/promote` — full promotion lifecycle works
- `POST /mcp/proxy` (tools/list) — 94 tools (was 88, +6 datahub)
- `POST /v1/chat/completions` with `agent:mlops` — end-to-end works
- n8n chat webhook `/webhook/chat` — AI Agent mode with MCP tools
- DataHub frontend accessible (auth disabled for k3d)

### Known Issues

1. ~~**datahub MCP unhealthy**~~ — FIXED. Disabled auth, set token, fixed port.
2. **openAiApi credential type broken in n8n** — LangChain sub-nodes can't use openAiApi. Workaround: ollamaApi directly to Ollama (bypasses LiteLLM proxy). Acceptable for local dev.
3. **qwen2.5:14b unreliable with 94 tools** — LLM hallucinate tool calls or respond in Chinese with many tools. May need tool filtering or more capable model.

### Commits Pushed

- `3900a4b` feat: agent promotion workflow — shadow → canary → primary
- `3a4c5b2` feat: sandbox runtime — ephemeral k8s Jobs for agent code execution
- `c84d294` fix: datahub MCP server port 8000 in seed config
- `07b17fa` fix: disable DataHub auth for k3d, set MCP token
- `ef13da3` perf: agent-gateway connection pooling + persistent HTTP client
- `c3d5f5f` fix: add kubectl to mcp-kubernetes image
- `815e84e` fix: retry with fresh session on 400/401 from MCP backends

### Next

1. **Import n8n workflows to k3d** — `task n8n-import` with updated chat.json
2. **Sandbox improvements** — pre-warmed pod pool, workspace PVC, artifact collection
3. **Canary traffic routing** — integrate canary_weight into chat endpoint routing logic
4. **DataHub ingestion** — ingest k8s resources, GitLab repos, MLflow experiments
5. **Agent eval framework** — automated shadow vs primary comparison scoring

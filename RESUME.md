# Platform Monorepo — Session Resume

## Session: 2026-03-20 — Agent Gateway Service (Spec 001)

### Built

- **Agent Gateway service** — `services/agent-gateway/` — FastAPI service implementing spec 001
- **Core models** — MCPServerRef, SkillDefinition, AgentDefinition, AgentRunConfig, LlmConfig, TaskDefinition
- **Agent YAML loader** — `agentspec/loader.py` — loads agent YAMLs with `$component_ref` resolution
- **MLflow sync** — `agentspec/sync.py` — syncs agent definitions to MLflow prompt registry (`agent:{name}`)
- **Agent registry** — `registry.py` — reads agents back from MLflow prompts
- **Skills registry** — `skills_registry.py` — CRUD for skills via MLflow model registry (`skill:{name}`)
- **Composer** — `composer.py` — merges agent + skills → AgentRunConfig (prompts, MCP servers, tools)
- **Chat router** — `routers/chat.py` — OpenAI-compatible `/v1/chat/completions` with `agent:` routing + LiteLLM fallback
- **Agents router** — `routers/agents.py` — list, get, search, Agent Spec export
- **Skills router** — `routers/skills.py` — CRUD + search (skills + tasks)
- **MCP router** — `routers/mcp.py` — search MCP tools across MetaMCP namespaces
- **n8n runtime** — `runtimes/n8n.py` — translates AgentRunConfig → n8n webhook POST, SSE translation
- **Agent YAMLs** — `agents/mlops.yaml`, `agents/agent-ops.yaml`, `agents/_shared/` (llm, mcp configs)
- **Skill YAMLs** — 6 skills: kubernetes-ops, mlflow-tracking, agent-management, skill-management, benchmark-runner, n8n-workflow-ops
- **Eval datasets** — `skills/eval/` with test cases for kubernetes-ops and mlflow-tracking

### Spec Artifacts

All in `specs/001-agent-gateway/`:
- spec.md, plan.md, tasks.md, data-model.md, research.md
- contracts/: agent-api.md, skills-api.md

### Design Decisions

- **No toolboxes/tools abstraction** — flat `mcp_servers: [{url, tool_filter}]` everywhere. MCPToolBox format only on Agent Spec export.
- **Two-level MCP servers** — agents have their own `mcp_servers` + skills bring additional ones. Deduplicated by URL at composition time.
- **Multi-namespace** — agents can reference MCP servers from multiple MetaMCP namespaces
- **Hybrid keyword search** — weighted scoring (name=3x, desc=2x, general=1x) on all search endpoints. Embedding similarity TODO.

### Test Status

25 tests passing, 0 lint errors:
- test_agentspec_loader.py (6) — YAML loading, $component_ref, validation
- test_sync.py (3) — MLflow prompt create/update
- test_registry.py (3) — agent get/list/not-found
- test_chat.py (3) — agent route, not found, LiteLLM fallback
- test_skills_registry.py (4) — create, conflict, get, list
- test_skills_api.py (6) — CRUD + search endpoints

### What's NOT Done (from tasks.md)

| Phase | What | Status |
|-------|------|--------|
| 6 | Workflow GitOps (export/import) | Not started |
| 8 | Benchmark runner | Not started |
| 11 | Python + Claude Code runtimes | Not started |
| 13 | Helm chart, platform integration, e2e | Not started |
| — | Wire skill resolution in chat router | TODO in code |
| — | Embedding-based search (Ollama /v1/embeddings) | TODO in code |
| — | Force flag in delete_skill | TODO in code |
| — | Gateway MCP server (T045) | Not started |

### Branch

`001-agent-gateway` — all changes uncommitted

### Next Steps

- [local] `cd services/agent-gateway && uv run pytest` — verify
- [local] Commit current state
- [local] Wire skill resolution into chat router (currently passes `skills=[]`)
- [local] Add embedding similarity to search endpoints
- [local] Phase 6: Workflow GitOps
- [local] Phase 13: Helm chart + deploy to k3d

# Factory Ledger

<!-- Machine-readable state. Updated by factory worker + R. -->

## Current Phase
B — Skill Library Expansion (A complete for MVP)

## Phase Map

| Phase | Name | Goal | Status |
|-------|------|------|--------|
| A | Foundation | Agent gateway MVP — agents, skills, chat, search | ✅ Done (25 tests) |
| B | Complete + Expand | Finish gateway gaps, expand skill library | 🔄 Active |
| C | MCP Mesh | Gateway MCP server, tool discovery, auto-registration | Queued |
| D | Intelligence | Embeddings search, benchmark runner, prompt optimization | Queued |
| E | Orchestration | Workflow GitOps, agent chains, multi-agent | Queued |
| F | Self-Optimization | Factory monitors quality, proposes improvements | Queued |

## Active Backlog

### Priority 1 — Gateway Gaps (from spec 001 tasks.md)

- [x] B.01 Wire skill resolution in chat router (ee28b4c)
      Domain: D2/gateway-core | Files: routers/chat.py, composer.py
- [ ] B.02 Add embedding similarity to search endpoints (Ollama /v1/embeddings)
      Domain: D4/embeddings | Files: routers/agents.py, skills.py, mcp.py
- [x] B.03 Force flag in delete_skill — check agent references before delete (1186e08)
      Domain: D2/skill-library | Files: skills_registry.py
- [ ] B.04 Workflow export with validation gate (Phase 6: T038-T042)
      Domain: D5/workflow-gitops | Files: workflows/export.py, import_.py
- [ ] B.05 Benchmark runner (Phase 8: T047-T052)
      Domain: D4/eval-framework | Files: benchmark/runner.py, results.py
- [ ] B.06 Gateway MCP server — expose REST API as MCP tools (T045)
      Domain: D3/gateway-mcp | Files: mcp_server.py
- [ ] B.07 Python runtime (T056)
      Domain: D2/runtimes | Files: runtimes/python.py
- [ ] B.08 Claude Code runtime (T057)
      Domain: D2/runtimes | Files: runtimes/claude_code.py
- [x] B.09 Helm chart for agent-gateway (T062) — deployed to k3d genai namespace
      Domain: D1/helm | Files: charts/genai-agent-gateway/

### Priority 2 — Skill Library Expansion

- [ ] B.10 Skill: data-ingestion — S3/GCS read, transform, load to postgres/vector store
      Domain: D2/skill-library | Produces: skills/data-ingestion.yaml
- [ ] B.11 Skill: vector-store-ops — pgvector/qdrant index management, similarity search
      Domain: D2/skill-library | Produces: skills/vector-store-ops.yaml
- [ ] B.12 Skill: prompt-engineering — optimize system prompts via A/B eval
      Domain: D2/skill-library | Produces: skills/prompt-engineering.yaml
- [ ] B.13 Skill: code-generation — generate/modify code with test verification
      Domain: D2/skill-library | Produces: skills/code-generation.yaml
- [ ] B.14 Skill: documentation — generate docs from code, specs, conversations
      Domain: D2/skill-library | Produces: skills/documentation.yaml
- [ ] B.15 Skill: security-audit — scan code/infra for vulnerabilities
      Domain: D2/skill-library | Produces: skills/security-audit.yaml

### Priority 3 — New Agents

- [ ] B.16 Agent: data-engineer — skills [data-ingestion, vector-store-ops, kubernetes-ops]
      Domain: D2/agent-definitions | Produces: agents/data-engineer.yaml
- [ ] B.17 Agent: platform-admin — skills [kubernetes-ops, n8n-workflow-ops, gitlab-pipeline-ops]
      Domain: D2/agent-definitions | Produces: agents/platform-admin.yaml
- [ ] B.18 Agent: developer — skills [code-generation, documentation, security-audit]
      Domain: D2/agent-definitions | Produces: agents/developer.yaml

### Phase C — MCP Mesh (after B)

- [ ] C.01 Gateway MCP server registration in MetaMCP
- [ ] C.02 Auto-discovery: scan MetaMCP namespaces, index all tools
- [ ] C.03 MCP tool recommendation engine — given a task, suggest tools
- [ ] C.04 Namespace: data — register data pipeline MCP servers

### Phase D — Intelligence (after B)

- [ ] D.01 Embedding service — utility for computing + caching embeddings
- [ ] D.02 Skill search with semantic similarity
- [ ] D.03 Agent search with semantic similarity
- [ ] D.04 MCP tool search with semantic similarity
- [ ] D.05 Benchmark runner end-to-end
- [ ] D.06 Eval dataset expansion — 10+ cases per skill task
- [ ] D.07 Auto-prompt optimization — run evals, tweak prompt_fragment, re-eval

### Phase E — Orchestration (parallel with D)

- [ ] E.01 Workflow export/import with credential portability
- [ ] E.02 Agent-to-agent delegation protocol
- [ ] E.03 Multi-agent pipeline definition format
- [ ] E.04 Claude Code as orchestrator — invoke gateway agents from CC

### Phase F — Self-Optimization (ongoing after D)

- [ ] F.01 Factory health dashboard — what's built, what's passing, what's stale
- [ ] F.02 Skill regression detection — benchmark scores drop → alert
- [ ] F.03 Gap analysis — identify missing skills from usage patterns
- [ ] F.04 Auto-skill-evolution — improve skills based on eval results

## Completed

- [x] A.01 Agent gateway project scaffold (Phase 1)
- [x] A.02 Core models — MCPServerRef, AgentDefinition, SkillDefinition, AgentRunConfig (Phase 2)
- [x] A.03 Agent YAML loader with $component_ref (Phase 3)
- [x] A.04 MLflow sync — agents to prompt registry (Phase 3)
- [x] A.05 Agent registry — read from MLflow (Phase 4)
- [x] A.06 Chat router — OpenAI-compatible with agent: routing + LiteLLM fallback (Phase 4)
- [x] A.07 n8n runtime (Phase 4)
- [x] A.08 Skills registry CRUD via MLflow model registry (Phase 5)
- [x] A.09 Skills API — full CRUD + search (Phase 5)
- [x] A.10 Agents API — list, get, search, Agent Spec export (Phase 9 + 12)
- [x] A.11 MCP search — keyword search over MetaMCP tools (Phase 9)
- [x] A.12 Agent YAMLs — mlops, agent-ops (Phase 7)
- [x] A.13 Skill YAMLs — 6 skills defined (Phase 7)
- [x] A.14 Eval datasets — kubernetes-ops, mlflow-tracking (Phase 8 partial)

## Blocked

<!-- Items that can't proceed and why -->
- B.07 Python runtime — needs pyagentspec package evaluation (is it worth the dependency?)
- B.08 Claude Code runtime — needs claude CLI headless mode testing on this machine

## R's Directives

<!-- R writes here to steer the factory. Worker obeys these. -->
- Focus on B.01-B.06 before expanding to new skills/agents
- All work on branch `001-agent-gateway` until committed
- TDD always — test first, verify fail, implement, verify pass
- Don't touch agents/ or skills/ YAMLs without clear need
- Commit after each completed item with descriptive message
- Update RESUME.md after each session
- If something takes >15 min, mark blocked and move on

## Evolution Log

<!-- Factory self-improvement notes -->
<!-- Format: date | what changed | why -->
- 2026-03-20 | B.01, B.03 completed by factory-worker | First run. Worker did code+tests+commits correctly but skipped self-improvement loop (didn't update ledger, lessons, or RESUME). Fixed by R.
- 2026-03-20 | Guardrails updated: added git staging rules | Factory committed __pycache__ on first run. Added explicit staging rules and pre-commit check to guardrails.
- 2026-03-21 | B.09 done: Helm chart + k3d deploy + MLflow port fix + async threading for sync MLflow client + MLflow 3.x API fix (get_prompt_version) | Agent gateway live at agent-gateway.genai.127.0.0.1.nip.io. 2 agents, 6 skills synced.
- 2026-03-21 | Eval pipeline built: /skill-optimize command + scripts/skill-optimize.py harness + pilot evals for fastapi-templates | Autoresearch methodology from Karpathy adapted for Claude Code skills.
- 2026-03-21 | Factory worker scheduled (15min interval, session-scoped via CronCreate) | Next: validate loop with first autonomous run.

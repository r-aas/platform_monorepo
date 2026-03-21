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
- [x] B.02 Add embedding similarity to search endpoints (Ollama /v1/embeddings) (3b7aa3e)
      Domain: D4/embeddings | Files: routers/agents.py, skills.py, mcp.py
- [x] B.03 Force flag in delete_skill — check agent references before delete (1186e08)
      Domain: D2/skill-library | Files: skills_registry.py
- [x] B.04 Workflow export with validation gate (Phase 6: T038-T042) (0577bf8)
      Domain: D5/workflow-gitops | Files: workflows/export.py, import_.py
- [x] B.05 Benchmark runner (Phase 8: T047-T052) (8ff828b)
      Domain: D4/eval-framework | Files: benchmark/runner.py, results.py
- [x] B.06 Gateway MCP server — expose REST API as MCP tools (T045) (c42dffa)
      Domain: D3/gateway-mcp | Files: mcp_server.py
- [ ] B.07 Python runtime (T056)
      Domain: D2/runtimes | Files: runtimes/python.py
- [ ] B.08 Claude Code runtime (T057)
      Domain: D2/runtimes | Files: runtimes/claude_code.py
- [x] B.09 Helm chart for agent-gateway (T062) — deployed to k3d genai namespace
      Domain: D1/helm | Files: charts/genai-agent-gateway/

### Priority 2 — Skill Library Expansion

- [x] B.10 Skill: data-ingestion — S3/GCS read, transform, load to postgres/vector store (7ad2104)
      Domain: D2/skill-library | Produces: skills/data-ingestion.yaml
- [x] B.11 Skill: vector-store-ops — pgvector/qdrant index management, similarity search (7ad2104)
      Domain: D2/skill-library | Produces: skills/vector-store-ops.yaml
- [x] B.12 Skill: prompt-engineering — optimize system prompts via A/B eval (116bc25)
      Domain: D2/skill-library | Produces: skills/prompt-engineering.yaml
- [x] B.13 Skill: code-generation — generate/modify code with test verification (116bc25)
      Domain: D2/skill-library | Produces: skills/code-generation.yaml
- [x] B.14 Skill: documentation — generate docs from code, specs, conversations (d18634f)
      Domain: D2/skill-library | Produces: skills/documentation.yaml
- [x] B.15 Skill: security-audit — scan code/infra for vulnerabilities (d18634f)
      Domain: D2/skill-library | Produces: skills/security-audit.yaml

### Priority 3 — New Agents

- [x] B.16 Agent: data-engineer — skills [data-ingestion, vector-store-ops, kubernetes-ops] (feedd5a)
      Domain: D2/agent-definitions | Produces: agents/data-engineer.yaml
- [x] B.17 Agent: platform-admin — skills [kubernetes-ops, n8n-workflow-ops, gitlab-pipeline-ops] (feedd5a)
      Domain: D2/agent-definitions | Produces: agents/platform-admin.yaml
- [x] B.18 Agent: developer — skills [code-generation, documentation, security-audit] (5efbb98)
      Domain: D2/agent-definitions | Produces: agents/developer.yaml

### Phase C — MCP Mesh (after B)

- [x] C.01 Gateway MCP server registration in MetaMCP (ab57411)
- [x] C.02 Auto-discovery: scan MetaMCP namespaces, index all tools (6eae872)
- [x] C.03 MCP tool recommendation engine — given a task, suggest tools (04ea373)
- [x] C.04 Namespace: data — register data pipeline MCP servers (9127598)

### Phase D — Intelligence (after B)

- [x] D.01 Embedding service — LRU cache (EmbeddingCache + module singleton) (365d12d)
- [x] D.02 Skill search with semantic similarity — endpoint tests added (49003c7)
- [x] D.03 Agent search with semantic similarity — endpoint tests added (49003c7)
- [x] D.04 MCP tool search with semantic similarity (f769ce5)
- [x] D.05 Benchmark runner end-to-end (4612e17)
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
- 2026-03-21 | B.02 complete: hybrid embedding search wired into agents/skills/mcp search endpoints. Graceful fallback when Ollama unreachable. Fixed B.09-introduced test_registry regression (get_prompt vs get_prompt_version mocks). 39 tests passing. | Post-commit pytest must be run from services/agent-gateway/, not monorepo root.
- 2026-03-21 | B.04 complete: workflow export/import with portable credential refs. Pure transformation functions + thin async n8n API wrappers. Taskfile tasks wired. 21 new tests (60 total). | Health: P1 backlog shrinking (4/6 done), B.05 and B.06 remain as high-value items.
- 2026-03-21 | B.05 complete: benchmark runner with pure evaluate_case(), MLflow logging, POST /skills/{name}/tasks/{task}/benchmark endpoint, eval datasets for kubernetes-ops. 17 new tests (77 total). | Health: P1 near complete (6/7 non-blocked done).
- 2026-03-21 | B.06 complete: gateway MCP server at /gateway-mcp. JSON-RPC 2.0 over HTTP, 6 tools (list/get agents+skills, create/delete skill), initialize handshake. 12 new tests (89 total). All P1 non-blocked items done. | Health: P1 complete (B.07/B.08 blocked). Next: P2 skill library expansion.
- 2026-03-21 | B.10+B.11 complete: data-ingestion and vector-store-ops skill YAMLs. TDD with 16 schema validation tests (105 total). Path traversal gotcha: test was 5 parents deep but needed 4. | Health: P2 active (2/6 done). B.12-B.15 remain.
- 2026-03-21 | B.12+B.13 complete: prompt-engineering (MLflow A/B eval) and code-generation (TDD+GitLab) skill YAMLs. 16 new schema validation tests (121 total). Both follow established 8-test-per-skill pattern. | Health: P2 active (4/6 done). B.14-B.15 remain.
- 2026-03-21 | B.14+B.15 complete: documentation (code→docs, API spec extraction, conversation summaries) and security-audit (OWASP scan, k8s RBAC audit, SARIF reports) skill YAMLs. 16 new schema validation tests (137 total). P2 fully done. | Health: P2 complete. Next: P3 agents (B.16-B.18) compose from 6 skills.
- 2026-03-21 | B.16+B.17+B.18 complete: data-engineer, platform-admin, developer agent YAMLs. New test_agent_yamls.py with 24 schema validation tests (161 total). Phase B fully done (P1+P2+P3). | Health: All non-blocked B items complete. Next: Phase C (MCP Mesh) starting with C.01.
- 2026-03-21 | C.01 complete: metamcp_client.py with tRPC auth+create+update+namespace-assign. Config extended with 6 MetaMCP settings. main.py lifespan wires non-fatal registration on startup. 5 tests via pytest-httpx (166 total). | Health: Phase C active (1/4 done). C.02 next (auto-discovery).
- 2026-03-21 | C.02 complete: mcp_discovery.py with DiscoveredTool/ToolIndex, discover_namespaces() via tRPC + static fallback, fetch_tools_for_namespace() via MCP proxy, index_all_tools() non-fatal. main.py lifespan wires index on startup. mcp.py router uses cached index with live-fetch fallback. 9 new tests (175 total). | Health: Phase C active (2/4 done). C.03 (recommendation engine) next.
- 2026-03-21 | C.03 complete: mcp_recommender.py with pure score_tools() + async recommend_tools(). GET /mcp/recommend endpoint with top_n/min_score params. match_hints per tool explain relevance. 13 new tests (188 total). | Health: Phase C active (3/4 done). C.04 next.
- 2026-03-21 | C.04 complete: namespace_registry.py with load_namespace_config() + register_namespace_servers(). namespaces/data.yaml with postgres-mcp, files-mcp, airflow-mcp. Generic pattern replaces hardcoded gateway registration. 10 new tests (198 total). Phase C fully done. | Health: All Phase C items complete. Next: Phase D (Intelligence) — D.01 embedding service.
- 2026-03-21 | D.01 complete: EmbeddingCache class (OrderedDict LRU, maxsize=512) + module singleton. get_embedding() checks cache before HTTP — repeated calls skip Ollama. clear_embedding_cache()/embedding_cache_size() helpers. 8 new tests (206 total). Cache isolation bug found: tests sharing same text key must call clear_embedding_cache() first. | Health: Phase D active (3/7 done — D.02+D.03 already implemented via B.02, now have test coverage). D.04 next.
- 2026-03-21 | D.02+D.03 complete (tests): 4 tests for /skills/search, 4 tests for /agents/search (new test_agents_api.py). Implementation already existed from B.02. Tests confirm hybrid scoring (keyword + embedding), fallback to keyword-only when Ollama unavailable. 8 new tests (214 total). | Health: D.04 (MCP tool search tests) is the natural next item.
- 2026-03-21 | D.04 complete: test_mcp_search.py — 4 tests for GET /mcp/search (keyword match, no-match empty, hybrid embedding, keyword-only fallback). Implementation from C.02/B.02 confirmed correct. 218 tests total. | Health: D.05 next.
- 2026-03-21 | D.05 complete: 4 end-to-end tests for run_benchmark_task() in test_benchmark.py (all-cases processing, stub-mode fail, missing dataset error, real dataset on disk). Fixed path traversal bug (parents[3] not parents[4]). 222 tests total. | Health: D.04+D.05 done. D.06 (eval dataset expansion) and D.07 (auto-prompt optimization) remain.

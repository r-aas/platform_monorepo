# Tasks: Agent Gateway

**Input**: Design documents from `/specs/001-agent-gateway/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: TDD — tests written first, verified to fail, then implementation.

**Organization**: Tasks grouped by user story. P1 stories first, then P2, then P3.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup

**Purpose**: Project scaffolding and dependency configuration

- [x] T001 Create `services/agent-gateway/` directory structure per plan.md
- [x] T002 Initialize Python project with `uv init` in `services/agent-gateway/`, configure `pyproject.toml` with FastAPI, Pydantic, pydantic-settings, mlflow, httpx, uvicorn, PyYAML dependencies
- [x] T003 [P] Create `services/agent-gateway/Dockerfile` (multi-stage, uv-based)
- [x] T004 [P] Create `services/agent-gateway/src/agent_gateway/__init__.py` and `py.typed`
- [x] T005 [P] Create `services/agent-gateway/tests/conftest.py` with httpx AsyncClient fixture for FastAPI test client
- [x] T006 Create `services/agent-gateway/src/agent_gateway/config.py` — Pydantic Settings class with MLFLOW_TRACKING_URI, N8N_BASE_URL, N8N_API_KEY, LITELLM_BASE_URL, GATEWAY_PORT defaults

**Checkpoint**: `uv sync` succeeds, `uv run pytest` runs (0 tests)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core models and abstractions that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T007 Create Pydantic models in `services/agent-gateway/src/agent_gateway/models.py` — MCPServerRef (url, tool_filter), SkillRef, AgentDefinition (name, description, system_prompt, mcp_servers, skills, llm_config, runtime, workflow, inputs, agentspec_version), SkillDefinition (name, description, version, tags, mcp_servers, prompt_fragment, tasks), TaskDefinition (name, description, inputs, evaluation), AgentRunConfig (system_prompt, prompt_fragments, mcp_servers, allowed_tools, message, agent_params, agent_name, session_id, llm_config, runtime)
- [x] T008 Create runtime protocol in `services/agent-gateway/src/agent_gateway/runtimes/base.py` — Runtime ABC with `async def invoke(config: AgentRunConfig) -> AsyncIterator[str]` and `async def invoke_sync(config: AgentRunConfig) -> str`
- [x] T009 Create `services/agent-gateway/src/agent_gateway/main.py` — FastAPI app with lifespan, include routers, health endpoint returning `{"status": "healthy", "mlflow": "connected|disconnected", "agents_loaded": N}`
- [x] T010 [P] Create `services/agent-gateway/src/agent_gateway/routers/__init__.py`
- [x] T011 [P] Create `services/agent-gateway/src/agent_gateway/runtimes/__init__.py`
- [x] T012 [P] Create `services/agent-gateway/src/agent_gateway/agentspec/__init__.py`
- [x] T013 [P] Create `services/agent-gateway/src/agent_gateway/benchmark/__init__.py`
- [x] T014 [P] Create `services/agent-gateway/src/agent_gateway/workflows/__init__.py`

**Checkpoint**: FastAPI app starts, health endpoint returns JSON, models importable

---

## Phase 3: User Story 2 — Define Agent as YAML + Sync to MLflow (P1) 🎯 MVP

**Goal**: Agent Spec YAML files in `agents/` are the source of truth. `task agents:sync` writes them to MLflow.

**Independent Test**: Create an agent YAML, run sync, verify agent appears in MLflow with correct tags.

**Why first**: US1 (invoke) depends on agents existing in MLflow. Sync must work before invocation.

### Tests for US2

- [x] T015 [P] [US2] Write test for YAML loader in `services/agent-gateway/tests/test_agentspec_loader.py` — load valid YAML, resolve $component_ref, validate against schema, reject invalid YAML
- [x] T016 [P] [US2] Write test for MLflow sync in `services/agent-gateway/tests/test_sync.py` — sync agent definition to MLflow prompt registry, verify prompt name `agent:{name}`, verify tags (runtime, workflow, llm_model, mcp_servers_json, agentspec_version), verify system_prompt stored as template

### Implementation for US2

- [x] T017 [US2] Implement YAML loader in `services/agent-gateway/src/agent_gateway/agentspec/loader.py` — load YAML file, resolve `$component_ref` references from `agents/_shared/`, validate required fields, return AgentDefinition
- [x] T018 [US2] Implement MLflow sync in `services/agent-gateway/src/agent_gateway/agentspec/sync.py` — `sync_agent(agent: AgentDefinition)` creates/updates MLflow prompt `agent:{name}` with system_prompt as template and config as version tags; `sync_all(agents_dir: Path)` syncs entire directory
- [x] T019 [US2] Create `agents/_shared/llm-ollama.yaml` (OllamaConfig pointing at LiteLLM) and `agents/_shared/mcp-genai.yaml` (LiteLLM MCP gateway URL — originally MetaMCP, migrated to LiteLLM)
- [x] T020 [US2] Create `agents/mlops.yaml` — example agent with skills reference, $component_ref for llm_config, mcp_servers, {{domain}} placeholder
- [x] T021 [US2] Add `task agents:sync` to `services/agent-gateway/Taskfile.yml` — calls sync_all CLI entrypoint

**Checkpoint**: `task agents:sync` writes mlops agent to MLflow, `mlflow.MlflowClient().get_prompt("agent:mlops")` returns correct data

---

## Phase 4: User Story 1 — Invoke via OpenAI-Compatible API (P1)

**Goal**: `POST /v1/chat/completions` with `model=agent:mlops` routes to n8n and streams back.

**Independent Test**: curl the gateway with `model=agent:mlops`, get a streaming OpenAI-compatible response.

### Tests for US1

- [x] T022 [P] [US1] Write test for agent registry in `services/agent-gateway/tests/test_registry.py` — lookup agent by name from MLflow, return AgentDefinition, 404 for missing agent
- [x] T023 [P] [US1] Write test for chat router in `services/agent-gateway/tests/test_chat.py` — POST /v1/chat/completions with model=agent:{name} returns SSE stream; model=nonexistent returns 404; model without agent: prefix proxies to LiteLLM
- [x] T024 [P] [US1] Write test for n8n runtime in `services/agent-gateway/tests/test_n8n_runtime.py` — translates AgentRunConfig to webhook POST body {chatInput, sessionId}, streams n8n SSE response back as OpenAI SSE chunks

### Implementation for US1

- [x] T025 [US1] Implement agent registry in `services/agent-gateway/src/agent_gateway/registry.py` — `async get_agent(name: str) -> AgentDefinition` reads from MLflow prompt `agent:{name}`, parses tags back to AgentDefinition; `async list_agents() -> list[AgentDefinition]` searches all `agent:*` prompts
- [x] T026 [US1] Implement agent composer in `services/agent-gateway/src/agent_gateway/composer.py` — `async compose(agent: AgentDefinition, skills: list[SkillDefinition], message: str, params: dict) -> AgentRunConfig` builds effective prompt (system_prompt + skill fragments), merges mcp_servers (agent + skills, deduplicated by URL), merges allowed_tools from skill tool_filters, resolves {{placeholders}}
- [x] T027 [US1] Implement n8n runtime in `services/agent-gateway/src/agent_gateway/runtimes/n8n.py` — POST to `{N8N_BASE_URL}/webhook/{workflow}` with `{chatInput, sessionId}`, translate n8n SSE to OpenAI SSE chunk format, implement Runtime ABC
- [x] T028 [US1] Implement chat router in `services/agent-gateway/src/agent_gateway/routers/chat.py` — `POST /v1/chat/completions`: if model starts with `agent:`, lookup agent, compose AgentRunConfig, dispatch to runtime, stream response; else proxy to LiteLLM (FR-006 backward compat)
- [x] T029 [US1] Implement LiteLLM proxy fallback in chat router — non-agent model values forwarded to LITELLM_BASE_URL unchanged
- [x] T030 [US1] Add trace logging — log AgentRunConfig to MLflow traces on each invocation (FR-009, FR-010b)

**Checkpoint**: `curl -X POST http://localhost:8000/v1/chat/completions -d '{"model":"agent:mlops","messages":[{"role":"user","content":"hello"}],"stream":true}'` returns streaming response via n8n

---

## Phase 5: User Story 3 — Skills Registry CRUD (P1)

**Goal**: CRUD API for skills at `/skills`. Skills stored in MLflow model registry. Agents reference skills by name.

**Independent Test**: POST a skill, GET it back, assign to agent, invoke agent, verify skill's MCP servers and prompt fragment are active.

### Tests for US3

- [x] T031 [P] [US3] Write test for skills registry in `services/agent-gateway/tests/test_skills_registry.py` — create skill in MLflow model registry, read back, update (new version), delete, list, conflict on duplicate name
- [x] T032 [P] [US3] Write test for skills API in `services/agent-gateway/tests/test_skills_api.py` — POST /skills, GET /skills, GET /skills/{name}, PUT /skills/{name}, DELETE /skills/{name}, DELETE with force, GET /skills/{name}/tasks

### Implementation for US3

- [x] T033 [US3] Implement skills registry in `services/agent-gateway/src/agent_gateway/skills_registry.py` — CRUD operations against MLflow model registry: create_skill (register model + version with tags), get_skill, list_skills, update_skill (new model version), delete_skill (with force flag checking agent references)
- [x] T034 [US3] Implement skills router in `services/agent-gateway/src/agent_gateway/routers/skills.py` — POST /skills (201), GET /skills (200), GET /skills/{name} (200), PUT /skills/{name} (200), DELETE /skills/{name} (200/409), GET /skills/{name}/tasks (200) per contracts/skills-api.md
- [x] T035 [US3] Create seed skill YAMLs in `skills/` — `kubernetes-ops.yaml`, `mlflow-tracking.yaml` with mcp_servers, prompt_fragment, tasks, evaluation refs
- [x] T036 [US3] Add skill seeding to sync process in `services/agent-gateway/src/agent_gateway/agentspec/sync.py` — `seed_skills(skills_dir: Path)` loads skill YAMLs and creates in registry if not exists
- [x] T037 [US3] Wire composer to resolve skills — update `compose()` in `composer.py` to load skills from registry by name, merge their mcp_servers and prompt_fragments into AgentRunConfig

**Checkpoint**: Full CRUD lifecycle via curl; agent invocation includes skill prompt fragments and MCP servers

---

## Phase 6: User Story 8 — Workflow GitOps (P1)

**Goal**: `task workflows:export` validates and exports n8n dev workflows to repo. `task workflows:import` imports to prod.

**Independent Test**: Edit workflow in n8n dev, export (passes validation), break it, export again (rejected).

### Tests for US8

- [x] T038 [P] [US8] Write test for workflow export in `services/agent-gateway/tests/test_workflows.py` — strip volatile fields, sort nodes by name, replace credential IDs with portable refs, validate schema, test invocation check
- [x] T039 [P] [US8] Write test for workflow import in `services/agent-gateway/tests/test_workflows.py` — resolve portable credential refs to target IDs, import via n8n API

### Implementation for US8

- [x] T040 [US8] Implement workflow export in `services/agent-gateway/src/agent_gateway/workflows/export.py` — fetch workflows from n8n dev project, strip volatile fields (id, active, updatedAt, createdAt, versionId, meta.executionCount), sort nodes by name, replace credential IDs with `{$portable: true, type, name}`, validate (schema check, webhook reachability, test invocation), write to `workflows/` directory
- [x] T041 [US8] Implement workflow import in `services/agent-gateway/src/agent_gateway/workflows/import_.py` — read `workflows/*.json`, resolve portable credential refs by type+name lookup in target n8n, create/update workflows via n8n API, activate webhook-bearing workflows
- [x] T042 [US8] Add `task workflows:export` and `task workflows:import` to `services/agent-gateway/Taskfile.yml`

**Checkpoint**: Export from n8n dev → JSON in repo → import to n8n prod, credentials resolved

---

## Phase 7: User Story 4 — Agent-Ops Meta-Agent (P1)

**Goal**: Chat with `model=agent:agent-ops` to manage agents, skills, workflows, and benchmarks.

**Independent Test**: Send `model=agent:agent-ops` with "list all agents", get conversational response with agent list.

### Implementation for US4

- [x] T043 [US4] Create agent-ops management skill YAMLs in `skills/` — `agent-management.yaml` (tasks: create/update/delete/list agents, mcp_servers pointing at gateway's own MCP server), `skill-management.yaml` (tasks: create/update/delete/list skills), `benchmark-runner.yaml` (tasks: run-benchmark, list-results), `n8n-workflow-ops.yaml` (tasks: list/create/validate/inspect workflows, mcp_servers pointing at LiteLLM MCP gateway)
- [x] T044 [US4] Create `agents/agent-ops.yaml` — meta-agent with skills [agent-management, skill-management, benchmark-runner, n8n-workflow-ops], system prompt for conversational management
- [x] T045 [US4] Implement gateway MCP server stub in `services/agent-gateway/src/agent_gateway/mcp_server.py` — exposes gateway REST API as MCP tools (list_agents, get_agent, create_skill, etc.) for agent-ops to call. Registered in LiteLLM as `agent_gateway` MCP server.
- [x] T046 [US4] Sync agent-ops agent and seed its skills — verify `model=agent:agent-ops` is invocable

**Checkpoint**: `curl ... model=agent:agent-ops "list all agents"` returns conversational response

---

## Phase 8: User Story 5 — Benchmark Agent Tasks (P2)

**Goal**: Run evaluation datasets against agent tasks, record results in MLflow experiments.

**Independent Test**: Define eval dataset, run benchmark, verify results in MLflow with per-case metrics.

### Tests for US5

- [x] T047 [P] [US5] Write test for benchmark runner in `services/agent-gateway/tests/test_benchmark.py` — load eval dataset JSON, invoke agent per case, evaluate output (contains expected strings, correct tools used, latency), record to MLflow experiment

### Implementation for US5

- [x] T048 [US5] Create eval dataset format and examples in `skills/eval/kubernetes-ops/deploy-model.json` and `skills/eval/kubernetes-ops/check-status.json` per plan.md R13
- [x] T049 [US5] Implement benchmark runner in `services/agent-gateway/src/agent_gateway/benchmark/runner.py` — load dataset JSON, invoke agent via gateway for each case, collect results
- [x] T050 [US5] Implement benchmark results recorder in `services/agent-gateway/src/agent_gateway/benchmark/results.py` — create MLflow experiment `eval:{agent}:{skill}:{task}`, log run with params (agent, skill, task, llm_model, skill_version) and metrics (pass_rate, avg_latency, total_cases), attach per-case artifact JSON
- [x] T051 [US5] Add benchmark API endpoint `POST /skills/{name}/tasks/{task}/benchmark` in skills router — accepts agent name, triggers benchmark run, returns 202 with benchmark_id and MLflow experiment/run info
- [x] T052 [US5] Add `task agents:benchmark` to Taskfile — CLI interface for running benchmarks

**Checkpoint**: Benchmark run produces MLflow experiment with per-case pass/fail, latency, tool calls

---

## Phase 9: User Story 6 — Agent Discovery API (P2)

**Goal**: `GET /agents` lists all agents with skills. `GET /agents/{name}` returns detail.

**Independent Test**: Sync agents, query discovery endpoints, verify metadata matches YAML definitions.

### Tests for US6

- [x] T053 [P] [US6] Write test for agents API in `services/agent-gateway/tests/test_agents_api.py` — GET /agents returns list with name, description, runtime, skills; GET /agents/{name} returns detail with resolved skills, tasks, tool counts, input parameters; GET /agents/nonexistent returns 404

### Implementation for US6

- [x] T054 [US6] Implement agents router in `services/agent-gateway/src/agent_gateway/routers/agents.py` — GET /agents (list), GET /agents/{name} (detail with resolved skills), per contracts/agent-api.md

**Checkpoint**: `curl /agents` returns agent list matching synced definitions

---

## Phase 10: User Story 9 — Agent-Workflow Binding (P2)

**Goal**: Sync validates that referenced workflows exist in `workflows/` directory.

**Independent Test**: Reference a missing workflow in agent YAML, sync fails with clear error.

### Implementation for US9

- [x] T055 [US9] Add workflow existence validation to sync process in `services/agent-gateway/src/agent_gateway/agentspec/sync.py` — when agent has `metadata.workflow`, verify `workflows/{workflow}.json` exists, fail with actionable error if missing

**Checkpoint**: Sync rejects agent referencing nonexistent workflow

---

## Phase 11: User Story 7 — Swap Runtime (P2)

**Goal**: Change `metadata.runtime` in YAML, re-sync, same API works with different backend.

**Independent Test**: Change agent runtime from n8n to python, re-sync, invoke, verify different execution path.

### Implementation for US7

- [x] T056 [P] [US7] Implement Python runtime in `services/agent-gateway/src/agent_gateway/runtimes/python.py` — uses pyagentspec Agent class, connects to MCP servers from AgentRunConfig, calls LLM via LiteLLM, implements Runtime ABC
- [x] T057 [P] [US7] Implement Claude Code runtime in `services/agent-gateway/src/agent_gateway/runtimes/claude_code.py` — provisions sandbox directory, generates mcp.json from AgentRunConfig.mcp_servers, invokes `claude -p` with --system-prompt, --mcp-config, --allowedTools, --output-format stream-json, streams output as OpenAI SSE, cleans up sandbox
- [x] T058 [US7] Add runtime registry to `services/agent-gateway/src/agent_gateway/runtimes/__init__.py` — `get_runtime(name: str) -> Runtime` maps "n8n"→N8nRuntime, "python"→PythonRuntime, "claude-code"→ClaudeCodeRuntime

**Checkpoint**: Same agent invocable on n8n and python runtimes, same response format

---

## Phase 12: User Story 10 — Agent Spec Export (P3)

**Goal**: `GET /agents/{name}/spec` returns valid Agent Spec JSON with MCP servers translated to MCPToolBox format.

**Independent Test**: Request spec, validate against pyagentspec AgentSpecSerializer schema.

### Tests for US10

- [x] T059 [US10] Write test for Agent Spec export in `services/agent-gateway/tests/test_agentspec_export.py` — verify output has component_type=Agent, agentspec_version=26.2.0, mcp_servers translated to toolboxes with MCPToolBox+StreamableHTTPTransport, sensitive fields replaced with $SENSITIVE

### Implementation for US10

- [x] T060 [US10] Implement Agent Spec export in `services/agent-gateway/src/agent_gateway/agentspec/export.py` — `export_agent_spec(agent: AgentDefinition, skills: list[SkillDefinition]) -> dict` translates to Agent Spec JSON: mcp_servers → toolboxes (MCPToolBox with StreamableHTTPTransport), llm_config → OllamaConfig, api_key → $SENSITIVE
- [x] T061 [US10] Add `GET /agents/{name}/spec` endpoint to agents router — calls export, returns Agent Spec JSON per contracts/agent-api.md

**Checkpoint**: `curl /agents/mlops/spec | python -c "import json,sys; d=json.load(sys.stdin); assert d['component_type']=='Agent'"` passes

---

## Phase 13: Polish & Deployment

**Purpose**: Helm chart, Taskfile integration, final wiring

- [x] T062 [P] Create Helm chart in `charts/genai-agent-gateway/` — Chart.yaml, values.yaml (image, replicas, env vars for MLflow/n8n/LiteLLM), templates/ (deployment, service, ingress with nip.io)
- [x] T063 [P] Create root-level `services/agent-gateway/Taskfile.yml` with all tasks: setup, dev, stop, test, lint, sync, benchmark, workflows:export, workflows:import
- [x] T064 Add agent-gateway include to platform Taskfile.yml if needed
- [x] T065 End-to-end smoke test — sync agents, invoke via gateway, verify response, check MLflow traces
- [x] T066 Update `specs/001-agent-gateway/spec.md` status to `in-progress`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Phase 1
- **US2 Sync (Phase 3)**: Depends on Phase 2 — agents must exist in MLflow before anything else
- **US1 Invoke (Phase 4)**: Depends on Phase 3 (needs agents in MLflow)
- **US3 Skills (Phase 5)**: Depends on Phase 4 (composer wired into invocation path)
- **US8 Workflows (Phase 6)**: Depends on Phase 2 only (independent of agent invocation)
- **US4 Agent-Ops (Phase 7)**: Depends on Phase 5 (needs skills CRUD) + Phase 6 (needs workflow ops)
- **US5 Benchmark (Phase 8)**: Depends on Phase 5 (needs skills with tasks)
- **US6 Discovery (Phase 9)**: Depends on Phase 3 (needs registry)
- **US9 Binding (Phase 10)**: Depends on Phase 3 + Phase 6 (needs sync + workflows)
- **US7 Runtimes (Phase 11)**: Depends on Phase 4 (needs runtime ABC wired)
- **US10 Export (Phase 12)**: Depends on Phase 5 (needs skills resolved)
- **Polish (Phase 13)**: Depends on all above

### Parallel Opportunities

After Phase 5 (Skills) completes:
- Phase 6 (Workflows), Phase 8 (Benchmark), Phase 9 (Discovery) can run in parallel
- Phase 11 (Runtimes) and Phase 12 (Export) can run in parallel

### Critical Path

Phase 1 → Phase 2 → Phase 3 (US2) → Phase 4 (US1) → Phase 5 (US3) → Phase 7 (US4) → Phase 13

---

## Implementation Strategy

### MVP First (Phases 1-5)

1. Setup + Foundational → project boots
2. US2 (Sync) → agents exist in MLflow
3. US1 (Invoke) → agents invocable via OpenAI API
4. US3 (Skills) → agents composed from reusable skills
5. **STOP and VALIDATE**: invoke agent with skills, verify prompt composition + MCP servers

### Incremental Delivery

- MVP (Phases 1-5): Agents defined, synced, invocable with skills → **core value delivered**
- +Workflows (Phase 6): GitOps pipeline for n8n workflows
- +Agent-Ops (Phase 7): Conversational management
- +Benchmark (Phase 8): Per-task evaluation
- +Discovery (Phase 9): Agent listing API
- +Runtimes (Phase 11): Python + Claude Code backends
- +Export (Phase 12): Agent Spec JSON federation

---

## Notes

- [P] tasks = different files, no dependencies
- TDD: write test, verify it fails, then implement
- Commit after each phase checkpoint
- All MCP server references are flat URLs with optional tool_filter — no MCPToolBox wrapping in our model
- Agent Spec MCPToolBox format only produced on export (Phase 12)

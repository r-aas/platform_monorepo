<!-- status: shipped -->
<!-- pr: !1 -->
# Feature Specification: Agent Gateway

**Feature Branch**: `001-agent-gateway`
**Created**: 2026-03-20
**Status**: Draft
**Input**: Provider-agnostic agent gateway unifying Oracle Agent Spec, MLflow prompt registry, MetaMCP tools, and pluggable runtimes (n8n, Python)

## Overview

A gateway service that decouples agent definitions from their execution runtimes. Agents are defined using Oracle Agent Spec YAML (version-controlled in the repo), synced to MLflow's prompt registry for runtime lookup, and executed via pluggable backends (n8n workflows, Python/pyagentspec, future runtimes). The gateway exposes an OpenAI-compatible chat API so any client that speaks OpenAI can invoke agents without knowing the underlying runtime.

An agent is composed of two things: **identity** (system prompt — who the agent is) and **skills** (what the agent can do). Skills are reusable groups of tasks, tools, and prompt fragments managed via a skills registry with full CRUD. Each task within a skill can be tested and benchmarked independently. A meta-agent ("agent-ops") is itself an agent in the system, equipped with agent/skill management skills — you chat with it to manage everything else.

### Current State

| Component | Role Today | Gap |
|-----------|-----------|-----|
| MLflow prompt registry | Stores `{agent}.SYSTEM` + `{agent}.{TASK}` prompts, config as tags | No standard format — tags are ad-hoc, not portable |
| n8n `chat-v1` workflow | Agent execution (tool loop, session, tracing) | Tightly coupled — can't swap runtimes |
| MetaMCP gateway | Aggregates 88 MCP tools across 5 servers | Not referenced from agent definitions |
| OpenAI-compat gateway | Routes by model name, handles prompt lookup | Model-centric, not agent-centric |
| A2A server | Google Agent-to-Agent protocol endpoint | Standalone, not connected to agent definitions |
| Oracle Agent Spec | Not used yet | Industry standard for portable agent definitions |

### Target State

An agent is: **system prompt + skills[]**. The system prompt defines identity — who the agent is, how it reasons, what tone it uses. Skills define capabilities — each skill is a named group of tasks with associated MCP servers (direct URLs, not wrapped in abstractions), prompt fragments (specialized instructions beyond the system prompt), and evaluation datasets (for independent benchmarking per task).

Agent definitions live as Agent Spec YAML files in the repo. A skills registry (CRUD API backed by MLflow) stores reusable skill definitions that any agent can reference. A sync process writes agent definitions to MLflow. The gateway reads from MLflow at runtime, resolves skills to MCP server configs and prompt fragments, and routes to the appropriate backend. A meta-agent ("agent-ops") provides a conversational interface for managing agents and skills — it's just another agent in the system, equipped with management skills.

Clients use the OpenAI chat/completions API with `model=agent:{name}` to invoke any agent.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Invoke an Agent via OpenAI-Compatible API (Priority: P1)

A developer sends a POST request to `/v1/chat/completions` with `model=agent:mlops` and a message. The gateway looks up the `mlops` agent definition from MLflow, resolves its skills to MCP server configs and prompt fragments, determines its runtime (n8n), and forwards the request to the n8n chat webhook. The response streams back in OpenAI-compatible format with `system_fingerprint` identifying the agent and version.

**Why this priority**: This is the core value — any OpenAI-compatible client (Claude Code, Cursor, custom apps) can invoke agents without knowing the backend.

**Independent Test**: Send a curl request to the gateway with `model=agent:mlops` and verify the response comes back with correct agent routing and tool access.

**Acceptance Scenarios**:

1. **Given** an agent `mlops` defined in Agent Spec YAML with runtime=n8n, **When** a client sends `POST /v1/chat/completions` with `model=agent:mlops`, **Then** the gateway routes to n8n's chat webhook and returns a valid OpenAI-compatible response.
2. **Given** an agent `mlops` with a skill that references a MetaMCP genai namespace MCP server, **When** the agent processes a message requiring tool use, **Then** the agent can invoke tools from the skill's MCP server.
3. **Given** a request with `model=agent:nonexistent`, **When** the gateway receives it, **Then** it returns HTTP 404 with a clear error message listing available agents.

---

### User Story 2 — Define an Agent as Agent Spec YAML (Priority: P1)

A platform engineer creates a YAML file in `agents/mlops.yaml` following Oracle Agent Spec format. The file declares the agent's system prompt (with `{{placeholders}}`), LLM config pointing to Ollama, skills by reference, and metadata specifying `runtime: n8n`. Running `task agents:sync` resolves skill references, assembles the full agent definition, and writes it to MLflow's prompt registry.

**Why this priority**: Without agent definitions, nothing else works. The YAML format is the source of truth.

**Independent Test**: Create an agent YAML with skills, run sync, verify the agent appears in MLflow with resolved MCP servers and prompt fragments from its skills.

**Acceptance Scenarios**:

1. **Given** a valid Agent Spec YAML file in `agents/`, **When** `task agents:sync` runs, **Then** the agent's system prompt is stored as `{name}.SYSTEM` in MLflow with all config tags.
2. **Given** an Agent Spec YAML with `{{domain}}` placeholder in the system prompt, **When** synced to MLflow, **Then** the placeholder is preserved and the input schema is recorded.
3. **Given** an agent YAML referencing skills `["kubernetes-ops", "mlflow-tracking"]`, **When** synced, **Then** each skill's MCP server URLs and prompt fragment are resolved and stored as tags.

---

### User Story 3 — Manage Skills via CRUD Registry (Priority: P1)

A platform engineer registers a new skill "kubernetes-ops" via `POST /skills` with a name, description, task list, MCP server references, and prompt fragment. The skill is stored in MLflow and becomes available for any agent to reference. They can list all skills (`GET /skills`), update a skill's tasks or tools (`PUT /skills/{name}`), and remove deprecated skills (`DELETE /skills/{name}`).

**Why this priority**: Skills are the unit of capability — without a registry, agents can't be composed from reusable parts.

**Independent Test**: Create a skill via API, assign it to an agent, invoke the agent, verify it has access to the skill's MCP servers and follows the skill's prompt fragment.

**Acceptance Scenarios**:

1. **Given** a valid skill definition, **When** `POST /skills` is called, **Then** the skill is stored in the registry and returned with its ID.
2. **Given** an existing skill "kubernetes-ops", **When** `GET /skills/kubernetes-ops` is called, **Then** the response includes the skill's tasks, MCP server references, prompt fragment, and evaluation metadata.
3. **Given** a skill referenced by two agents, **When** the skill is updated via `PUT /skills/{name}`, **Then** both agents pick up the updated skill on next invocation (no re-sync required for runtime changes).
4. **Given** a skill referenced by an active agent, **When** `DELETE /skills/{name}` is called, **Then** the system warns that the skill is in use and requires confirmation (or a `force` flag).
5. **Given** a skill with tasks defined, **When** `GET /skills/{name}/tasks` is called, **Then** the response lists each task with its description, expected inputs/outputs, and evaluation dataset reference.

---

### User Story 4 — Chat with Agent-Ops to Manage Agents and Skills (Priority: P1)

A developer sends `model=agent:agent-ops` and says "Create a new agent called data-eng with the kubernetes-ops and data-pipeline skills." The agent-ops agent — which is itself an agent in the system equipped with agent-management and skill-management skills — interprets the request, calls the appropriate CRUD APIs, creates the agent definition, and confirms the result conversationally. The developer can also ask "What skills does mlops have?" or "Add the monitoring skill to data-eng" and the agent-ops agent handles it.

**Why this priority**: A conversational interface for agent management is the primary way users will interact with the system. It makes agent management accessible without memorizing API contracts.

**Independent Test**: Chat with agent-ops to create an agent, verify the agent exists in MLflow and can be invoked.

**Acceptance Scenarios**:

1. **Given** a user chatting with `agent:agent-ops`, **When** they ask to create a new agent with specific skills, **Then** agent-ops calls the agent CRUD API and reports the result.
2. **Given** a user asking "list all agents", **When** agent-ops processes the request, **Then** it calls `GET /agents` and presents the results conversationally.
3. **Given** a user asking to add a skill to an existing agent, **When** agent-ops processes the request, **Then** it updates the agent definition and confirms the change.
4. **Given** a user asking "What skills are available?", **When** agent-ops processes the request, **Then** it calls `GET /skills` and presents skills with their task summaries.
5. **Given** a user asking to benchmark an agent's task, **When** agent-ops processes the request, **Then** it triggers the evaluation pipeline and reports results.

---

### User Story 5 — Benchmark Agent Tasks Independently (Priority: P2)

A platform engineer wants to evaluate how well the `mlops` agent performs the "deploy-model" task from its "kubernetes-ops" skill. They run `task agents:benchmark agent=mlops skill=kubernetes-ops task=deploy-model` which executes the evaluation dataset against the agent and records results in MLflow. Each task within each skill can be benchmarked independently, producing per-task metrics (accuracy, task completion, latency).

**Why this priority**: Independent task benchmarking is how you optimize agents — you need to know which tasks work well and which need improvement. But agents can be used without benchmarks.

**Independent Test**: Define an evaluation dataset for a task, run the benchmark, verify results appear in MLflow with per-task metrics.

**Acceptance Scenarios**:

1. **Given** a skill with a task that has an evaluation dataset, **When** `task agents:benchmark` runs for that task, **Then** results are recorded in MLflow under experiment `eval:agent:{name}:skill:{skill}:task:{task}`.
2. **Given** two different LLM configs for the same agent, **When** both are benchmarked on the same task, **Then** results are comparable side-by-side in MLflow.
3. **Given** a benchmark run, **When** results are recorded, **Then** each test case includes: input, expected output, actual output, pass/fail, latency, and any tool calls made.

---

### User Story 6 — List Available Agents (Priority: P2)

A developer queries `GET /agents` to discover all available agents. The response includes each agent's name, description, equipped skills, supported input parameters, and runtime backend. This enables clients to dynamically discover capabilities.

**Why this priority**: Discovery is essential for multi-agent systems and developer experience, but agents can be used without it.

**Independent Test**: Query the agents endpoint and verify all synced agents appear with their metadata and skill lists.

**Acceptance Scenarios**:

1. **Given** three agents synced to MLflow, **When** `GET /agents` is called, **Then** all three appear with name, description, runtime, and equipped skills.
2. **Given** an agent with input parameters (`{{domain}}`), **When** its detail is requested via `GET /agents/{name}`, **Then** the response includes the input schema with parameter names and types.
3. **Given** an agent with skills, **When** its detail is requested, **Then** the response includes each skill's tasks with descriptions.

---

### User Story 7 — Swap Runtime Without Changing Client Code (Priority: P2)

An engineer changes an agent's runtime from `n8n` to `python` by updating the `metadata.runtime` field in the YAML and re-syncing. All existing clients continue to work — same API, same model name, same skills — but execution now happens via a local Python agent using pyagentspec.

**Why this priority**: This is the core abstraction value — runtime portability. But it requires at least two working runtimes to be meaningful.

**Independent Test**: Switch an agent's runtime, re-sync, send the same request, verify the response still works but execution path changed.

**Acceptance Scenarios**:

1. **Given** an agent running on n8n, **When** its runtime is changed to `python` and re-synced, **Then** subsequent requests route to the Python runtime.
2. **Given** an agent on the Python runtime with the same skills, **When** it needs to call a tool, **Then** it connects to MetaMCP and invokes the tool identically to the n8n path.

---

### User Story 8 — Workflow GitOps: Dev-to-Repo-to-Prod Sync (Priority: P1)

A workflow developer iterates on an agent's n8n workflow in the **dev project** in n8n (the only project where workflows are editable). When satisfied, they run `task workflows:export` which validates the workflow (schema check, webhook reachable, test invocation passes), then exports the workflow JSON to the GitLab repo. Only workflows that pass validation are committed — broken or untested workflows never reach the repo. On deploy, `task workflows:import` syncs the versioned workflow JSONs from the repo into n8n's production/stage projects as read-only imports. Workflows in non-dev projects are never edited directly — the repo is the source of truth, dev n8n is the scratchpad.

**Why this priority**: Without workflow sync, agent definitions and their execution logic drift apart. The validation gate ensures only working workflows reach production. The dev-only editing constraint prevents unauthorized changes to production agent behavior.

**Independent Test**: Edit a workflow in n8n dev, run export, verify it validates before committing. Break the workflow, run export again, verify it rejects the export with a clear error.

**Acceptance Scenarios**:

1. **Given** a workflow edited in the n8n dev project, **When** `task workflows:export` runs, **Then** the workflow is validated (schema, webhook reachability, test invocation) before being written to the repo's `workflows/` directory.
2. **Given** a workflow that fails validation (unreachable webhook, test invocation error), **When** `task workflows:export` runs, **Then** the export is rejected with a clear error identifying what failed, and no changes are committed to the repo.
3. **Given** a versioned workflow JSON in the repo, **When** `task workflows:import` runs, **Then** the workflow is imported into n8n's production project, overwriting any existing version.
4. **Given** a workflow in n8n's production project, **When** a user attempts to edit it directly, **Then** the system prevents the edit or warns that changes will be overwritten on next sync.
5. **Given** a workflow JSON in the repo that references credentials or environment-specific values, **When** imported to a different n8n instance, **Then** credential references are resolved to the target environment's credentials (not hardcoded IDs).

---

### User Story 9 — Agent-Workflow Binding (Priority: P2)

An agent's YAML definition references a specific n8n workflow by name (e.g., `workflow: chat-v1`). The sync process validates that the referenced workflow exists in the repo's `workflows/` directory. At runtime, the gateway routes to the correct n8n workflow webhook based on this binding. This connects the declarative agent definition to its concrete execution logic.

**Why this priority**: Without explicit binding, the relationship between agents and workflows is implicit and fragile.

**Independent Test**: Define an agent referencing a workflow, sync both, invoke the agent, verify it routes to the correct workflow.

**Acceptance Scenarios**:

1. **Given** an agent YAML with `workflow: chat-v1`, **When** `task agents:sync` runs, **Then** the sync validates that `workflows/chat-v1.json` exists and records the binding.
2. **Given** an agent referencing a workflow that doesn't exist in the repo, **When** sync runs, **Then** it fails with a clear error identifying the missing workflow.

---

### User Story 10 — Agent Spec Export for Federation (Priority: P3)

An external system queries `GET /agents/{name}/spec` and receives the full Agent Spec JSON for that agent, compatible with any Agent Spec runtime (WayFlow, LangGraph adapter, etc.). This enables federation — other runtimes can consume and execute the same agent definitions.

**Why this priority**: Federation and interop are future value — not needed for the core gateway to work.

**Independent Test**: Request an agent's spec and validate it against the Agent Spec JSON Schema.

**Acceptance Scenarios**:

1. **Given** a synced agent, **When** `GET /agents/{name}/spec` is called, **Then** the response is valid Agent Spec JSON (component_type=Agent, agentspec_version=26.2.0) with skills resolved to MCP server configs (exported as MCPToolBox format).
2. **Given** an agent with sensitive fields (API keys), **When** its spec is exported, **Then** sensitive fields are omitted per Agent Spec `SensitiveField` convention.

---

### Edge Cases

- What happens when MLflow is unreachable? Gateway returns 503 with retry guidance; cached agent definitions are used if available.
- What happens when the specified runtime (n8n) is down? Gateway returns 502 identifying the failed backend.
- What happens when a skill referenced by an agent doesn't exist in the registry? Sync fails with a clear error identifying the missing skill.
- What happens when a skill's MCP server URL is unreachable? The agent executes without that skill's tools and includes a warning in the response metadata.
- What happens when an Agent Spec YAML has invalid syntax? `task agents:sync` fails with a clear validation error pointing to the issue.
- What happens when two agents have the same name? Sync rejects with a conflict error.
- What happens when two skills have the same name? Registry rejects with a conflict error.
- What happens when a skill is deleted while agents reference it? Deletion requires `force=true`; agents referencing the skill are flagged with a warning on next invocation.
- What happens when a workflow is exported from dev but has unsaved changes? Export captures the last-saved state; warns if n8n reports unsaved modifications.
- What happens when a workflow fails validation during export? Export reports exactly which check failed (schema, reachability, test invocation) and skips that workflow. Other valid workflows in the batch proceed normally.
- What happens when a workflow import conflicts with an active execution? Import waits for active executions to complete (or times out after 30s) before replacing.
- What happens when credential IDs in a workflow JSON don't match the target n8n instance? Import resolves credentials by type and name, not by ID; fails with a clear error if no matching credential is found.
- What happens when agent-ops tries to manage itself? It can read its own definition but cannot delete itself.
- What happens when a benchmark evaluation dataset is empty? Benchmark returns an error indicating no test cases found.
- What happens when a Claude Code sandbox runs out of disk space? The session fails gracefully with an error; sandbox is cleaned up.
- What happens when a Claude Code session exceeds its budget? Claude CLI's `--max-budget-usd` stops the session; partial results are returned.
- What happens when the Anthropic API key is missing for a claude-code runtime agent? Gateway returns 503 with a message indicating the Claude Code runtime is not configured.

## Requirements *(mandatory)*

### Functional Requirements

**Agent Core**
- **FR-001**: System MUST accept Agent Spec YAML files (v26.2.0) as the source of truth for agent definitions, stored in `agents/` directory.
- **FR-002**: An agent definition MUST consist of a system prompt (identity), optional MCP server references (always-available servers), and a list of skill references (capabilities). Skills may require additional MCP servers beyond the agent's own.
- **FR-003**: System MUST sync agent definitions from YAML to MLflow prompt registry, resolving skill references to their constituent MCP servers and prompt fragments.
- **FR-004**: System MUST expose an OpenAI-compatible `/v1/chat/completions` endpoint that routes requests with `model=agent:{name}` to the appropriate runtime backend.
- **FR-005**: System MUST support pluggable runtime backends: n8n (via webhook), Python (via pyagentspec or direct MCP SDK), and Claude Code (via CLI headless mode). The runtime abstraction MUST allow adding new backends without changing the gateway core.
- **FR-005a**: The Claude Code runtime MUST provision an isolated sandbox workspace per agent invocation — each session gets its own directory with scoped file access, tool permissions, and optional repo clone. Sandboxes MUST be cleaned up after session completion unless explicitly persisted for multi-turn sessions.
- **FR-006**: System MUST preserve the existing `model={prompt_name}` routing for backward compatibility — only `model=agent:{name}` triggers the new agent path.
- **FR-007**: System MUST support Agent Spec placeholder syntax (`{{variable}}`) in system prompts, resolving them from request parameters at invocation time.
- **FR-008**: System MUST map Agent Spec LlmConfig (OllamaConfig) to the existing LiteLLM/Ollama inference path without duplicating endpoint configuration.
- **FR-009**: System MUST log agent invocations to the existing trace system (MLflow `__traces` experiment) with agent name, runtime, skill, task, and tool calls.
- **FR-010**: System MUST support streaming responses (SSE) for all runtime backends.
- **FR-010a**: Every agent invocation MUST be resolved into a runtime-agnostic run config (system prompt, prompt fragments, MCP server URLs, allowed tools, message) before dispatching to any runtime. The same run config MUST be translatable to any supported runtime without modification — runtime is purely an execution detail.
- **FR-010b**: The full run config for every invocation MUST be logged to the trace system, enabling exact reproduction of any past agent run on any runtime.
- **FR-011**: Sync process MUST validate Agent Spec YAML against the v26.2.0 schema before writing to MLflow, rejecting invalid definitions with actionable errors.
- **FR-012**: System MUST handle Agent Spec `$component_ref` for shared components (e.g., a single LlmConfig reused across agents).

**Skills Registry**
- **FR-013**: System MUST provide a skills registry with full CRUD: `POST /skills` (create), `GET /skills` (list), `GET /skills/{name}` (read), `PUT /skills/{name}` (update), `DELETE /skills/{name}` (delete).
- **FR-014**: A skill MUST be a named, versioned group of: tasks (named units of work with descriptions and expected inputs/outputs), MCP server references (MetaMCP namespace endpoint URLs with optional tool filters), a system prompt fragment (specialized instructions appended to the agent's system prompt), and evaluation metadata (dataset references for benchmarking).
- **FR-015**: Skills MUST be stored in MLflow and resolved at runtime — agents reference skills by name, and the gateway assembles the full MCP server set and prompt by composing the agent's system prompt with its skills' prompt fragments.
- **FR-016**: When an agent is invoked, the gateway MUST compose the effective system prompt as: agent's base system prompt + each skill's prompt fragment (in skill order).
- **FR-017**: When an agent is invoked, the gateway MUST merge the agent's own MCP servers with all skill MCP servers into the agent's available MCP connections (deduplicated by URL).
- **FR-018**: Skill definitions MUST support versioning — updating a skill creates a new version, and agents can pin to a specific version or use latest.

**Agent-Ops Meta-Agent**
- **FR-019**: The system MUST include a built-in agent named `agent-ops` that is equipped with skills for managing agents and skills.
- **FR-020**: The `agent-ops` agent MUST be able to create, read, update, and delete agents and skills via conversational commands (natural language → API calls).
- **FR-021**: The `agent-ops` agent MUST be able to trigger benchmark evaluations and report results conversationally.
- **FR-022**: The `agent-ops` agent MUST be invocable via the same `model=agent:agent-ops` interface as any other agent.
- **FR-023a**: The `agent-ops` agent MUST be equipped with an n8n workflow management skill that uses the n8n MCP server tools (workflow CRUD, validation, execution, node docs) to manage workflows conversationally.

**Task Benchmarking**
- **FR-023**: Each task within a skill MUST support an optional evaluation dataset (input/expected-output pairs stored as JSON in the repo).
- **FR-024**: System MUST provide `task agents:benchmark` that runs an agent against a specific task's evaluation dataset and records results in MLflow under a dedicated experiment.
- **FR-025**: Benchmark results MUST include per-test-case: input, expected output, actual output, pass/fail, latency, and tool calls made.
- **FR-026**: Benchmark results MUST be comparable across different LLM configs, agent versions, and skill versions for the same task.

**Agent Discovery**
- **FR-027**: System MUST expose `GET /agents` for agent discovery and `GET /agents/{name}` for agent detail, including equipped skills, tasks per skill, input schemas, and runtime info.
- **FR-027a**: System MUST expose `GET /agents/search?q={query}` for hybrid RAG search over agent definitions — combining keyword matching (name, description, skill names) with semantic similarity over system prompts and skill descriptions. Returns ranked results.
- **FR-027b**: System MUST expose `GET /skills/search?q={query}` for hybrid RAG search over the skills registry — combining keyword matching (name, tags, task names) with semantic similarity over descriptions and prompt fragments.
- **FR-027c**: System MUST expose `GET /mcp/search?q={query}` for hybrid RAG search over the MCP server registry (MetaMCP) — combining keyword matching (server names, tool names) with semantic similarity over tool descriptions. Enables agents and users to discover available tools by capability.
- **FR-027d**: System MUST expose `GET /skills/tasks/search?q={query}` for hybrid RAG search over all tasks across all skills — enabling discovery of agent capabilities by what they can do, not just what they're called.
- **FR-028**: System MUST expose `GET /agents/{name}/spec` returning valid Agent Spec JSON for federation with other runtimes. MCP server references are translated to Agent Spec MCPToolBox format on export.

**Workflow GitOps**
- **FR-029**: Workflow export (`task workflows:export`) MUST validate each workflow before committing: schema validity, webhook/trigger node reachability, and a test invocation that returns a non-error response. Only workflows that pass all checks are written to `workflows/` and committed.
- **FR-030**: System MUST import versioned workflow JSONs from the repo into n8n via `task workflows:import`, resolving credentials by type/name for the target environment.
- **FR-031**: Only the dev project in n8n MUST allow workflow editing. Workflows in other projects are import-only — the repo is the single source of truth.
- **FR-032**: Agent definitions MUST reference n8n workflows by name, and the sync process MUST validate that referenced workflows exist in the repo.
- **FR-033**: Workflow export MUST produce deterministic, diffable JSON — sorted keys, stable node ordering, no volatile fields (lastUpdated timestamps, execution counts).
- **FR-034**: Workflow export MUST strip environment-specific values (credential IDs, webhook UUIDs) from exported JSONs, replacing them with portable references resolvable at import time.

### Key Entities

- **Agent**: A system prompt (identity) + optional mcp_servers[] (always-available) + skills[] (capabilities, each bringing their own MCP servers) + LLM config + runtime metadata. Defined as Agent Spec YAML, synced to MLflow.
- **Skill**: A named, versioned group of tasks + MCP server references + prompt fragment + evaluation metadata. Stored in the skills registry (MLflow). Reusable across agents. Everything an agent needs beyond its system prompt.
- **Task**: A named unit of work within a skill, with a description, expected inputs/outputs, and an optional evaluation dataset for independent benchmarking.
- **Runtime Backend**: A pluggable execution engine (n8n, Python) that receives agent invocations and executes the tool loop. Selected by `metadata.runtime` in the agent definition.
- **MCP Server**: A MetaMCP namespace endpoint URL. Each skill references one or more MCP servers with optional tool filters. On Agent Spec export, these are translated to MCPToolBox format.
- **Agent Registry**: MLflow prompt registry storing synced agent definitions with resolved skill metadata.
- **Skills Registry**: MLflow-backed CRUD store for skill definitions.
- **Agent-Ops**: A built-in meta-agent equipped with agent-management and skill-management skills. Conversational interface for managing the system.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Any OpenAI-compatible client can invoke an agent by setting `model=agent:{name}` and receive a valid streaming response within the same latency envelope as direct n8n calls (< 2s to first token for non-tool-use responses).
- **SC-002**: Switching an agent's runtime from n8n to Python requires changing one field in the YAML and re-syncing — zero client-side changes.
- **SC-003**: Agent definitions created in this system can be exported as valid Agent Spec JSON and consumed by any Agent Spec-compatible runtime (pyagentspec validation passes).
- **SC-004**: All existing OpenAI-compatible API clients (model-based routing, prompt lookup, canary routing) continue to work unchanged after the gateway is deployed.
- **SC-005**: A new agent can be defined, synced, and invoked end-to-end in under 5 minutes using only a YAML file, skill references, and `task agents:sync`.
- **SC-006**: Agent tool invocations through the gateway are traceable end-to-end — from client request through agent execution to individual MCP tool calls — in the existing trace system.
- **SC-007**: A new skill can be created via the CRUD API and immediately referenced by any agent without restarting the gateway.
- **SC-008**: Individual tasks within skills can be benchmarked independently, with results comparable across agent versions in MLflow.
- **SC-009**: A developer can manage agents and skills entirely through conversation with `agent:agent-ops` — no direct API calls required for common operations (create agent, add skill, list agents, run benchmark).

## Assumptions

- Oracle Agent Spec v26.2.0 is stable enough to build against. The spec uses a YEAR.QUARTER.PATCH versioning scheme with a 1-year deprecation cycle.
- MetaMCP namespaces map cleanly to MCP server URLs — one namespace = one endpoint. Skills reference these URLs directly.
- The existing n8n `chat-v1` webhook interface is sufficient for the n8n runtime backend without modification. The gateway translates between OpenAI format and n8n's webhook format.
- pyagentspec or a compatible Python library is available for Agent Spec deserialization. If not, a minimal deserializer can be built from the JSON Schema.
- LiteLLM remains the inference proxy — the gateway does not make direct LLM calls.
- MLflow's prompt registry and model registry are sufficient for storing both agent and skill metadata without requiring a separate database.

## Scope Boundaries

**In scope:**
- Agent Gateway FastAPI service (new Helm chart)
- Agent Spec YAML format and sync to MLflow
- Skills registry with full CRUD API
- Skill = tasks + MCP servers + prompt fragment + evaluation data
- Agent-ops meta-agent for conversational management
- Per-task benchmarking with MLflow experiments
- OpenAI-compatible routing for `model=agent:{name}`
- n8n, Python, and Claude Code runtime backends
- Agent discovery API
- Agent Spec JSON export
- Workflow GitOps (validated export/import)

**Out of scope:**
- Replacing the existing OpenAI-compat n8n workflow (it continues to handle model-based routing)
- Multi-agent orchestration (Swarm, ManagerWorkers) — future spec
- Agent Spec Flow component support (n8n workflows are the flow engine)
- Authentication/authorization on the gateway (same trust model as existing webhooks)
- A2A protocol integration (exists separately, can be connected later)
- Skill marketplace or cross-organization skill sharing

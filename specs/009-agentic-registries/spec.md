<!-- status: deferred -->
<!-- type: umbrella -->
<!-- note: agent registry delivered by specs 017-019. Remaining: skills API, MCP API, gateway, meta-agents. -->
# Spec 009: AgenticOps Registries

## Implementation Specs

This is the umbrella vision document. Implementation is split into four specs with clear dependencies:

| Spec | Name | Key FRs | Status | Depends On |
|------|------|---------|--------|------------|
| [009a](../009a-structured-agent-tags/spec.md) | Structured Agent Tags | FR-001, FR-002, FR-006, FR-007, NFR-001 | draft | — |
| [009b](../009b-registry-apis/spec.md) | Registry APIs | FR-003, FR-004, FR-005 | draft | 009a |
| [009c](../009c-api-gateway/spec.md) | API Gateway | FR-008 | draft | 009a, 009b |
| [009d](../009d-meta-agents-eval-triad/spec.md) | Meta-Agents & Eval Triad | FR-009, FR-010 | draft | 009a, 009b |

**Implementation order**: 009a → 009b → 009c + 009d (parallel)

---

## Problem

Agent identity is fragmented across three places:
1. **MLflow** — prompt template + `agent.config` JSON blob (model, temperature, mcp_tools as a flat string)
2. **catalog.yaml** — MCP server definitions (static YAML, not queryable from inside the stack)
3. **chat.json Code node** — routing logic that glues them together

No component in the stack can answer: "What agents exist?", "What can agent X do?", or "What MCP servers are available?" These are hardcoded conventions, not queryable registries.

Skills (task prompts like `coder.review`, `writer.email`) are bound 1:1 to agents via naming convention (`{agent}.{skill}`). A "code review" skill can't be assigned to a different agent without duplicating the prompt. No API lists skills, assigns them across agents, or describes their capabilities.

MCP tool access is a comma-separated string in `agent.config` mixing server names and tool names. No distinction between "this agent can use the mlflow server" vs "this agent can use the `get_runs` tool."

## Goals

1. **Agent Registry** — MLflow-backed, agents as system prompts with structured tags
2. **Skills Registry** — skills as shared MLflow prompts, equippable by any agent via tags
3. **MCP Registry** — queryable catalog of MCP servers and their tools
4. **Unified query API** — webhook endpoints to list/inspect all three
5. **Meta-agents** — evaluation, dataset curation, and task specification agents in the registry
6. **Evaluation datasets** — per-skill benchmark datasets with structured storage conventions

## Non-Goals

- Dynamic MCP server registration at runtime (catalog.yaml + `--watch` is sufficient)
- Agent orchestration / multi-agent coordination (future spec)
- Automated evaluation pipelines (specifier → curator → evaluator chaining is a future spec)
- UI for registry management (API-first)
- Per-tool ACLs within MCP servers (server-level access is sufficient)
- Forced common interface across registries (each has its natural shape)

## Architectural Principles

### AP-001: Registries Are Distinct

The three registries do NOT share a common interface or abstraction. Each has its own natural shape dictated by its backing store and domain:

| Registry | Backing Store | Identity Pattern | Nature |
|----------|--------------|------------------|--------|
| Agent | MLflow Registered Models + Tags | `{name}.SYSTEM` | Config-heavy: provider, model, temperature, MCP bindings, skill bindings |
| Skill | MLflow Prompts (shared registry) | `{DOMAIN}.{SKILL}` | Prompt-heavy: template + lightweight metadata tags |
| MCP | `catalog.yaml` + gateway runtime | server name from YAML key | Infrastructure: static definitions + live tool inventory |

Forcing these into a common `Port` interface would be an unnecessary abstraction. The API gateway (FR-008) provides a unified entry point without homogenizing the backends.

### AP-002: Skills Are Prompts

Skills are not a separate data store. They are prompts in the existing MLflow prompts registry, distinguished by `use_case: skill`. The skills query API (FR-005) is a **view layer** — it filters and enriches prompt data, not a separate registry with its own storage.

This means:
- Skill CRUD uses the existing `/webhook/prompts` endpoint
- Skill queries (list, equip, unequip) use `/webhook/skills`
- No data duplication between "prompts" and "skills"

### AP-003: Domain ≠ Ownership

Skills use `{DOMAIN}.{SKILL}` naming (e.g., `coder.review`, `writer.email`). The domain prefix is an **organizational category**, not exclusive ownership. Any agent can equip any skill regardless of domain.

- `coder.review` belongs to the `coder` domain but can be equipped by `devops`
- `mlops.evaluate` belongs to the `mlops` domain but can be equipped by `analyst`
- The `agent.skills` tag on each agent is the M:N binding, not the skill name

### AP-004: Experiment Tracking Is Configurable

MLflow is the current experiment tracking backend but is treated as an adapter, not an assumption. The registry APIs return resolved objects (parsed tags, arrays, typed values) — consumers never see MLflow tag semantics directly. This keeps the door open for alternative backends without changing the API contracts.

### AP-005: Single External Entry Point

The API gateway (FR-008) is the only externally-facing HTTP endpoint. Backend services communicate on the internal Docker network. This provides:
- One port to document, one port to secure
- Aggregate health checking across all services
- Clean `/api/*` namespace independent of n8n webhook paths
- No consumer knowledge of internal service topology

### AP-006: LLM Flexibility

Agents are not locked to a single LLM provider. LiteLLM already proxies to multiple backends — the `agent.provider` and `agent.model` tags control routing per-agent. This enables:
- Local Ollama for fast iteration and cost-free development
- Cloud APIs (OpenAI, Anthropic, etc.) for evaluation agents that need stronger reasoning
- Different models per agent role — a `judge` agent can use a frontier model while a `writer` uses a local one
- No code changes — just tag updates via the agent registry API

### AP-007: Agent Development Lifecycle

Every agent has a system prompt and one or more supported tasks (equipped skills). Every task is benchmarked in MLflow using the evaluation triad: **dataset + method + metric** (FR-010).

```
Define Agent → Equip Tasks → Build Datasets → Benchmark (dataset+method+metric) → Refine → Re-benchmark
```

Each stage maps to existing or planned infrastructure:
- **Define**: Agent registry (FR-004) — system prompt + config
- **Equip**: Skills API (FR-005) — each skill defines a benchmarkable task
- **Dataset**: Curated input/expected pairs per task (MLflow + MinIO)
- **Method**: Agent + skill + config — the thing being evaluated
- **Metric**: Judge agent + scoring prompt — another agent that scores outputs
- **Benchmark**: Evaluation API (`/api/eval`), MLflow experiment runs
- **Refine**: Prompt versioning (MLflow model versions), config updates (agent tags)

Meta-agents (FR-009) participate in this loop — the `specifier` defines what success looks like, the `curator` builds datasets, the `evaluator` scores outputs. The metric is itself an agent with a task prompt, making the system self-referential.

---

## Functional Requirements

### FR-001: Structured Agent Tags

Replace the monolithic `agent.config` JSON blob with discrete, typed tags.

**Current** (single JSON string):
```json
{
  "agent.config": "{\"provider\":\"ollama\",\"model\":\"\",\"temperature\":0.3,...,\"mcp_tools\":\"all\"}"
}
```

**Proposed** (structured tags):
```json
{
  "use_case": "agent",
  "agent.description": "MLOps assistant for platform management",
  "agent.provider": "ollama",
  "agent.model": "",
  "agent.temperature": "0.3",
  "agent.top_p": "0.9",
  "agent.num_ctx": "32768",
  "agent.max_iterations": "10",
  "agent.mcp_servers": "n8n-knowledge,n8n-manager,mlflow",
  "agent.skills": "mlops.evaluate"
}
```

Key changes:
- `mcp_tools` string → `agent.mcp_servers` referencing catalog.yaml server names
- New `agent.skills` tag listing assigned skill names (at least one required — every agent must support at least one task)
- New `agent.description` for human-readable summary
- Config fields promoted to individual tags (queryable, not buried in JSON)
- `"all"` remains valid for `agent.mcp_servers` (unrestricted access)
- Empty string = no MCP access (chat-only agents like writer, reasoner)

### FR-002: Skills as Shared Prompts (Tasks)

Skills are prompts in the existing prompts registry with `use_case: skill`. They use `{DOMAIN}.{SKILL}` naming — the domain is an organizational category, NOT ownership. Any agent can equip any skill via its `agent.skills` tag.

Each skill defines a **task** — the atomic unit of agent capability that can be independently benchmarked. Every agent must have a system prompt and one or more supported tasks (equipped skills). Every task is evaluable via the evaluation triad (FR-010): dataset + method + metric.

Skills are NOT a separate registry. They live alongside agents and utility prompts in MLflow. The skills API (FR-005) is a view layer on top of the prompts registry, filtering by `use_case: skill`.

**Current** (agent-scoped semantics):
```json
{
  "name": "coder.review",
  "tags": { "use_case": "task", "task.description": "..." }
}
```

**Proposed** (domain-scoped, equippable by any agent):
```json
{
  "name": "coder.review",
  "tags": {
    "use_case": "skill",
    "skill.description": "Structured code review with severity-tagged issues and verdict",
    "skill.required_mcp_servers": "",
    "skill.output_format": "structured"
  }
}
```

**Naming convention**: `{DOMAIN}.{SKILL}` — names stay the same, semantics change. The domain prefix (`coder`, `writer`, `reasoner`, `mlops`) is a category for organization, not exclusive ownership.

| Name | Domain | Equippable By |
|------|--------|---------------|
| `coder.review` | coder | coder, mlops, devops |
| `coder.debug` | coder | coder, mlops, devops |
| `writer.email` | writer | writer, mlops |
| `writer.rewrite` | writer | writer, coder |
| `reasoner.solve` | reasoner | reasoner, analyst |
| `mlops.evaluate` | mlops | mlops, analyst |

Agents reference skills by `{DOMAIN}.{SKILL}` name in the `agent.skills` tag:
```json
{
  "agent.skills": "coder.review,coder.debug"
}
```

**Skill prompt resolution**: When chat loads an agent, the Prompt Resolver fetches all equipped skill prompts and enriches the system prompt with an "Available Skills" section — same pattern as current task discovery, but reading from the `agent.skills` tag instead of searching by naming convention.

**Skill tags** (on the MLflow Registered Model):
- `skill.description` — human-readable summary of what the skill does
- `skill.required_mcp_servers` — MCP servers this skill needs (empty = none). Agent must have these servers in `agent.mcp_servers` for the skill to function
- `skill.output_format` — `"structured"` | `"freeform"` | `"json"` (informational)

### FR-003: MCP Registry Endpoint

A new webhook endpoint that exposes catalog.yaml data as a queryable API.

```
POST /webhook/mcp
```

Actions:
- `list_servers` — returns all MCP servers with metadata
- `get_server` — returns specific server with tool list
- `list_tools` — returns all tools across all servers (flat list)

Data source: parsed from `catalog.yaml` at request time (always fresh, no caching needed).

Tool lists come from the MCP gateway itself — the registry queries the gateway's tool inventory.

### FR-004: Agent Registry Query API

Extend the existing `/webhook/prompts` endpoint (or add `/webhook/agents`):

```
POST /webhook/agents
```

Actions:
- `list` — returns all agents (prompts where `use_case=agent`) with parsed tags
- `get` — returns specific agent with full config, skills list, MCP servers
- `create` — creates agent prompt with structured tags
- `update` — updates agent tags (not the prompt template — use `/prompts` for that)
- `delete` — removes agent

Response includes resolved data:
```json
{
  "name": "mlops",
  "description": "MLOps assistant for platform management",
  "config": {
    "provider": "ollama",
    "model": "",
    "temperature": 0.3,
    "top_p": 0.9,
    "num_ctx": 32768,
    "max_iterations": 10
  },
  "mcp_servers": ["n8n-knowledge", "n8n-manager", "mlflow"],
  "skills": ["mlops.evaluate"],
  "prompt_version": "3",
  "prompt_alias": "production"
}
```

### FR-005: Skills Query API

Skills are a view on the prompts registry, not a separate store. The `/webhook/skills` endpoint filters prompts by `use_case=skill` and provides skill-specific operations (equip/unequip).

```
POST /webhook/skills
```

Actions:
- `list` — returns all prompts where `use_case=skill`, enriched with which agents equip them
- `get` — returns specific skill prompt with metadata
- `list_by_agent` — returns skills equipped by a specific agent (from `agent.skills` tag)
- `list_agents` — returns agents that have a specific skill equipped (reverse lookup)
- `equip` — adds a skill to an agent's `agent.skills` tag
- `unequip` — removes a skill from an agent's `agent.skills` tag

Skill CRUD (create, update, delete) uses the existing `/webhook/prompts` endpoint — skills are just prompts with `use_case: skill` tags.

### FR-006: Chat Workflow Reads Structured Tags

The Prompt Resolver in `chat.json` must read the new structured tags instead of parsing `agent.config` JSON blob. Backward compatibility: if `agent.config` exists (old format), parse it as fallback during migration.

### FR-007: Seed Data Migration

`data/seed-prompts.json` updated to use new tag schema.

**Agents** (7 total) get:
- `agent.description`
- `agent.mcp_servers` (replacing `mcp_tools` in the JSON blob)
- `agent.skills` (comma-separated shared skill names)
- Individual config tags (`agent.temperature`, etc.)
- `agent.config` JSON blob removed

**Skills** (6 total) get:
- Names unchanged — `{DOMAIN}.{SKILL}` format preserved (`coder.review`, `writer.email`, etc.)
- `use_case: "skill"` (was `"task"`)
- `skill.description` (was `task.description`)
- `skill.required_mcp_servers` (new)

**Utility prompts** (7 total: assistant, summarizer, classifier, extractor, rewriter, code-explainer, judge) unchanged — they are not agents or skills.

### FR-008: API Gateway — Unified Entry Point

Evolve the streaming proxy (Spec 008) into the stack's single external entry point. Currently, consumers must know individual service ports (n8n:5678, MLflow:5050, LiteLLM:4000, MCP Gateway:8811, etc.). The gateway consolidates all endpoints behind one port with clean route namespacing and aggregate health checking.

**Current state** (streaming proxy handles only `/v1/*`):
```
Client → :4010/v1/chat/completions → streaming proxy → LiteLLM (stream) or n8n (non-stream)
Client → :5678/webhook/prompts     → n8n directly
Client → :5050/api/...             → MLflow directly
```

**Proposed** (gateway proxies everything):
```
Client → :4010/v1/*          → existing streaming logic (unchanged)
Client → :4010/api/prompts   → n8n /webhook/prompts
Client → :4010/api/agents    → n8n /webhook/agents
Client → :4010/api/skills    → n8n /webhook/skills
Client → :4010/api/mcp       → n8n /webhook/mcp
Client → :4010/api/chat      → n8n /webhook/chat
Client → :4010/api/eval      → n8n /webhook/eval
Client → :4010/api/traces    → n8n /webhook/traces
Client → :4010/api/sessions  → n8n /webhook/sessions
Client → :4010/health        → aggregate health (all services)
Client → :4010/services      → service catalog with status
```

Key design:
- **`/api/*` namespace**: Clean proxy to n8n webhook endpoints. `POST /api/agents` → `POST http://n8n:5678/webhook/agents`. Auth header forwarded.
- **`/health`**: Aggregate health check — queries every service's health endpoint in parallel, returns per-service status with overall pass/fail. Replaces the current simple `{"status":"ok"}`.
- **`/services`**: Returns the service catalog — name, internal URL, health endpoint, current status, and the routes it handles. Acts as a live API directory.
- **Existing `/v1/*` routes**: Unchanged — streaming SSE logic from Spec 008 stays as-is.
- **Auth**: `X-API-Key` enforcement applies to all routes (existing behavior extended).
- **No n8n webhook exposure**: External consumers never hit n8n directly. n8n ports can be removed from docker-compose port bindings (internal only on `mlops-net`).

**Service registry** (configured in code, not dynamic):

| Service | Internal URL | Health Endpoint |
|---------|-------------|-----------------|
| n8n | `http://n8n:5678` | `/healthz` |
| MLflow | `http://mlflow:5050` | `/health` |
| LiteLLM | `http://litellm:4000` | `/health/liveliness` |
| MCP Gateway | `http://mcp-gateway:8811` | `/health` |
| Langfuse | `http://langfuse:3000` | `/api/public/health` |
| MinIO | `http://minio:9000` | `/minio/health/live` |

**What this is NOT**:
- Not a service mesh or Envoy/Istio-style proxy
- Not dynamic service registration (services are known at deploy time)
- Not rate limiting or circuit breaking (future concern)
- Does not proxy MLflow UI or n8n UI (those stay on their own ports for browser access)

### FR-009: Meta-Agents

Specialized agents that operate on other agents and skills as part of the development lifecycle (AP-007). These are regular agents in the registry — same tags, same prompt structure — but their purpose is to refine the system itself.

**Evaluator agent** (`evaluator`):
- Runs skill outputs through the `judge` prompt and scores them
- Uses MLflow to log evaluation results as experiment runs
- Equipped skills: `mlops.evaluate`
- MCP servers: `mlflow`
- Model: configurable — can use a stronger cloud model via LiteLLM for better judgment

**Dataset curator agent** (`curator`):
- Generates and curates evaluation datasets for specific skills
- Produces input/expected-output pairs stored in MLflow datasets or MinIO
- Equipped skills: (new) `curator.generate`, `curator.validate`
- MCP servers: `mlflow`
- Model: benefits from a stronger model for diverse test case generation

**Task specification agent** (`specifier`):
- Defines what a skill should do — acceptance criteria, edge cases, scoring rubrics
- Outputs structured task specifications that feed into evaluator and curator
- Equipped skills: (new) `specifier.define`, `specifier.rubric`
- MCP servers: `mlflow`
- Model: benefits from a stronger model for precise specification writing

These agents compose: `specifier` defines what success looks like → `curator` generates test cases → `evaluator` scores agent outputs against them.

**Scope note**: Agent definitions and registry entries are in scope for Spec 009. The automated pipeline that chains them together is a future spec.

### FR-010: Task Evaluation Framework

Every task (skill) is benchmarked in MLflow using a three-component evaluation triad:

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Dataset  │     │  Method  │     │  Metric  │
│ (what)   │     │  (how)   │     │ (score)  │
└────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                │
     ▼                ▼                ▼
  input/expected   agent + skill    judge agent
  pairs (JSONL)    + config         + scoring prompt
```

#### Dataset (what to test)

Curated input/expected-output pairs for a specific task. Each skill must have at least one dataset.

- **Storage**: MLflow registered model `eval:{DOMAIN}.{SKILL}` + JSONL files in MinIO
- **Linked to skill** via naming convention: `eval:coder.review`, `eval:mlops.evaluate`
- **Versioned**: MLflow model versions — datasets evolve as skills are refined

**Dataset structure** (JSONL):
```json
{"id": "cr-sec-001", "input": {"code": "eval(input())", "language": "python"}, "expected": {"verdict": "fail", "issues": [{"severity": "critical"}]}, "tags": ["security"], "difficulty": "easy"}
```

#### Method (how to execute)

The agent configuration that performs the task. A method is an agent + its equipped skill + config.

- **Agent**: system prompt + provider/model/temperature config
- **Skill**: the task prompt injected into the agent
- **MCP servers**: tool access needed by the skill (optional)
- **Fully described by registry data** — no separate method definition needed. The agent registry + skill registry together define the method.

A single task can be evaluated across multiple methods (e.g., run `coder.review` with `coder` agent on Ollama vs `coder` agent on Claude to compare).

#### Metric (how to score)

A judge that scores the method's output against the expected output. **The metric is itself an agent with a task prompt** — the scoring rubric is a skill.

- **Judge agent**: typically `evaluator`, but any agent can be a judge
- **Scoring prompt**: a skill like `mlops.evaluate` or a task-specific rubric from `specifier.rubric`
- **Model flexibility**: judges benefit from stronger models (AP-006) — a frontier model judging a local model's output

The judge receives: the original input, the expected output, and the actual output. It returns a structured score.

#### Evaluation run (MLflow experiment)

Each benchmark execution is logged as an MLflow experiment run:
- **Params**: `task` (skill name), `dataset` (dataset name + version), `method` (agent name + model), `metric` (judge agent + scoring skill)
- **Metrics**: `accuracy`, `precision`, `recall`, `f1`, `avg_score`, `case_count`
- **Artifacts**: full per-case results as JSONL

#### Lifecycle

1. `specifier` agent defines task acceptance criteria and scoring rubric
2. `curator` agent generates test cases matching the rubric → dataset
3. Human review / manual curation refines the dataset
4. `evaluator` agent runs method against dataset, scores with metric
5. Results logged as MLflow experiment run — compare across methods, models, prompt versions

**API access** via existing endpoints:
- Dataset CRUD: MLflow REST API (already available)
- Dataset files: MinIO S3 API (already available)
- Evaluation runs: `/api/eval` (existing prompt-eval workflow)

**Scope note**: Triad schema and storage conventions are in scope. Automated pipeline (specifier → curator → evaluator chaining) is a future spec.

---

## Non-Functional Requirements

### NFR-001: Backward Compatibility

The Prompt Resolver must handle both old (`agent.config` JSON blob) and new (structured tags) formats during migration. Old format treated as fallback — new tags take precedence.

### NFR-002: Query Performance

Registry queries must respond within 500ms. MLflow tag queries are indexed — no performance concern. MCP registry parses catalog.yaml (small file, <1ms).

### NFR-003: Single Source of Truth

- Agent config → MLflow tags (not duplicated elsewhere)
- MCP server definitions → catalog.yaml (not duplicated in MLflow)
- Agent ↔ MCP binding → `agent.mcp_servers` tag (references catalog entries by name)
- Agent ↔ Skill binding → `agent.skills` tag (comma-separated shared skill names)
- Skill definitions → MLflow prompts with `use_case: skill` (standalone, not agent-namespaced)

---

## Acceptance Criteria

### SC-001: Agent Registry
Given a running stack, when `POST /webhook/agents {"action":"list"}` is called, then all 7 agents are returned with parsed config, mcp_servers list, and skills list.

### SC-002: Agent Detail
Given agent "mlops", when `POST /webhook/agents {"action":"get","name":"mlops"}` is called, then response includes description, config object, mcp_servers array, and skills array.

### SC-003: Skills Registry
Given a running stack, when `POST /webhook/skills {"action":"list"}` is called, then all 6 skills are returned with descriptions and list of agents that have them equipped.

### SC-004: Skills by Agent
Given agent "coder" with `agent.skills: "coder.review,coder.debug"`, when `POST /webhook/skills {"action":"list_by_agent","agent":"coder"}` is called, then `["coder.review", "coder.debug"]` are returned with full skill metadata.

### SC-004b: Agents by Skill
Given skill "coder.review" equipped by agents coder, mlops, devops, when `POST /webhook/skills {"action":"list_agents","skill":"coder.review"}` is called, then `["coder", "mlops", "devops"]` are returned.

### SC-005: MCP Registry
Given a running stack, when `POST /webhook/mcp {"action":"list_servers"}` is called, then all 6 MCP servers are returned with title, description, and tool count.

### SC-006: MCP Server Detail
Given server "mlflow", when `POST /webhook/mcp {"action":"get_server","server":"mlflow"}` is called, then response includes title, description, and list of tool names.

### SC-007: Chat Uses Structured Tags
Given agent "devops" with `agent.mcp_servers: "n8n-manager,mlflow"`, when a chat message is sent, then the MCP Client is configured with only tools from those servers.

### SC-008: Seed Migration
Given `task workflow:seed-prompts`, when prompts are seeded, then all agents have structured tags (no `agent.config` JSON blob) and all tasks have `use_case: "skill"`.

### SC-009: Backward Compatibility
Given an agent with old `agent.config` JSON blob (no structured tags), when chat resolves the agent, then config is parsed from the blob as fallback.

### SC-010: Gateway Aggregate Health
Given a running stack, when `GET :4010/health` is called, then response includes per-service status for all 6 backend services with overall pass/fail.

### SC-011: Gateway API Proxy
Given a running stack, when `POST :4010/api/agents {"action":"list"}` is called, then response is identical to calling `POST :5678/webhook/agents {"action":"list"}` directly.

### SC-012: Gateway Service Catalog
Given a running stack, when `GET :4010/services` is called, then response lists all services with name, health status, and routes.

### SC-013: Gateway Auth Enforcement
Given `WEBHOOK_API_KEY` is set, when any `/api/*` route is called without the key, then 403 is returned.

### SC-014: Meta-Agent Registry
Given seed data is loaded, when `POST /api/agents {"action":"list"}` is called, then meta-agents `evaluator`, `curator`, and `specifier` appear alongside standard agents with appropriate skills and MCP bindings.

### SC-015: Meta-Agent LLM Override
Given agent `evaluator` with `agent.provider: "litellm"` and `agent.model: "anthropic/claude-sonnet-4-20250514"`, when a chat message is sent, then LiteLLM routes the request to the cloud API instead of Ollama.

### SC-016: Task Evaluation Triad
Given dataset `eval:coder.review`, method `coder` agent with `coder.review` skill, and metric `evaluator` agent with `mlops.evaluate` skill, when `POST /api/eval` runs the evaluation, then an MLflow experiment run is logged with params recording all three triad components and per-case scores as artifacts.

---

## Default Agent Configuration

### Agent ↔ MCP Server Mapping

| Agent | MCP Servers | Rationale |
|-------|-------------|-----------|
| mlops | n8n-knowledge, n8n-manager, mlflow | Full platform access |
| mcp | n8n-knowledge, n8n-manager | Workflow management focus |
| devops | n8n-manager, mlflow | Monitoring + execution inspection |
| analyst | mlflow | Data analysis only |
| coder | (none) | Code generation, no external tools |
| writer | (none) | Writing, no external tools |
| reasoner | (none) | Reasoning, no external tools |
| evaluator | mlflow | Evaluation scoring + experiment logging |
| curator | mlflow | Dataset generation + storage |
| specifier | mlflow | Task spec authoring + rubric storage |

Note: `coder` currently has `mcp_tools: "fetch"` — but `fetch` is a built-in gateway server, not in catalog.yaml. Decision: drop it (coder doesn't need web fetch for code generation).

### Agent ↔ Skill Mapping

| Agent | Equipped Skills | Rationale |
|-------|----------------|-----------|
| mlops | mlops.evaluate | Platform evaluation workflows |
| mcp | (none) | Pure workflow management |
| devops | coder.debug | Infrastructure debugging |
| analyst | mlops.evaluate, reasoner.solve | Analysis + problem solving |
| coder | coder.review, coder.debug, writer.rewrite | Code lifecycle skills |
| writer | writer.email, writer.rewrite | Writing variations |
| reasoner | reasoner.solve | Math/logic problem solving |
| evaluator | mlops.evaluate | Runs skill evaluations |
| curator | curator.generate, curator.validate | Generates + validates datasets |
| specifier | specifier.define, specifier.rubric | Defines tasks + scoring rubrics |

Skills can be re-equipped at any time via the `/webhook/skills {"action":"equip"}` API.

---

## Files

| File | Action |
|------|--------|
| `data/seed-prompts.json` | EDIT — migrate to structured tags, add meta-agents + new skills |
| `n8n-data/workflows/chat.json` | EDIT — Prompt Resolver reads structured tags |
| `n8n-data/workflows/prompt-crud.json` | EDIT — add agent/skill query actions (or new workflow) |
| `src/streaming_proxy.py` | EDIT — evolve into API gateway with `/api/*`, `/health`, `/services` |
| `docker-compose.yml` | EDIT — remove n8n external port binding (gateway only entry point) |
| `scripts/smoke-test.sh` | EDIT — add registry + gateway smoke tests |
| `scripts/agent-benchmark.py` | EDIT — use registry API for agent/skill discovery instead of hardcoded lists |
| `tests/test_integration.py` | EDIT — add registry integration tests |
| `tests/test_gateway.py` | NEW — gateway routing + health check tests |
| `data/datasets/` | NEW — evaluation dataset JSONL files (initial seed datasets for coder.review, mlops.evaluate) |

New files (if separate workflows):
| File | Action |
|------|--------|
| `n8n-data/workflows/agent-registry.json` | NEW — `/webhook/agents` endpoint |
| `n8n-data/workflows/mcp-registry.json` | NEW — `/webhook/mcp` endpoint |

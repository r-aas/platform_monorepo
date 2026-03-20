# Implementation Plan: Agent Gateway

**Branch**: `001-agent-gateway` | **Date**: 2026-03-20 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-agent-gateway/spec.md`

## Summary

Build a FastAPI gateway service where agents are composed of **identity** (system prompt) and **skills** (reusable groups of tasks, MCP servers, and prompt fragments). Agents are defined as Agent Spec YAML files, skills are managed via a CRUD registry backed by MLflow, and everything is invoked via an OpenAI-compatible `/v1/chat/completions` endpoint with `model=agent:{name}`. A meta-agent ("agent-ops") provides a conversational interface for managing agents and skills. Each task within a skill can be benchmarked independently via evaluation datasets tracked in MLflow. The gateway resolves skills to MCP server configs via MetaMCP URLs and routes to pluggable backends (n8n, Python). A validated workflow GitOps pipeline ensures only tested n8n workflows reach the repo and production.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: FastAPI, Pydantic, pyagentspec (Oracle Agent Spec SDK), mlflow, httpx, uvicorn
**Storage**: MLflow prompt registry (PostgreSQL-backed, already deployed)
**Testing**: pytest, httpx test client
**Target Platform**: k3d cluster (genai namespace), Helm chart deployed via ArgoCD
**Project Type**: Web service (API gateway)
**Performance Goals**: < 2s to first token for non-tool-use responses (matches existing n8n latency)
**Constraints**: Must preserve backward compatibility with existing `model={prompt_name}` routing
**Scale/Scope**: ~10 agents initially, single cluster

## Constitution Check

*GATE: Constitution is not yet populated for this repo. Applying CLAUDE.md principles instead.*

| Principle | Status | Notes |
|-----------|--------|-------|
| One interface, swap implementations | PASS | Core design — `model=agent:{name}` abstraction over n8n/Python runtimes |
| Local-first | PASS | Everything runs in k3d, Ollama native |
| Research before build | PASS | Oracle Agent Spec cloned, pyagentspec studied, existing infra mapped |
| Spec-driven development | PASS | This plan follows spec.md |
| TDD | ENFORCED | Tests written before implementation in tasks.md |
| Anti-sprawl | PASS | Single chart, reuses existing MLflow/MetaMCP/LiteLLM — no new databases |

## Project Structure

### Documentation (this feature)

```text
specs/001-agent-gateway/
├── spec.md              # Requirements (done)
├── plan.md              # This file
├── research.md          # Technology decisions
├── data-model.md        # Agent registry data model
├── contracts/           # API contracts
│   ├── openai-compat.md # /v1/chat/completions contract
│   └── agent-api.md     # /agents/* discovery API contract
└── tasks.md             # Ordered task list (next: /speckit.tasks)
```

### Source Code (repository root)

```text
charts/genai-agent-gateway/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    └── ingress.yaml

services/agent-gateway/
├── pyproject.toml
├── Dockerfile
├── src/agent_gateway/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan, health
│   ├── config.py            # Settings via pydantic-settings
│   ├── routers/
│   │   ├── chat.py          # /v1/chat/completions — OpenAI-compat routing
│   │   ├── agents.py        # /agents, /agents/{name}, /agents/{name}/spec
│   │   └── skills.py        # /skills CRUD + /skills/{name}/tasks
│   ├── registry.py          # MLflow prompt registry read/write (agents)
│   ├── skills_registry.py   # MLflow-backed skill CRUD (create/read/update/delete)
│   ├── composer.py          # Compose agent: base prompt + skill prompt fragments + merged MCP servers
│   ├── runtimes/
│   │   ├── base.py          # Runtime protocol (ABC)
│   │   ├── n8n.py           # n8n webhook runtime
│   │   ├── python.py        # Python/pyagentspec runtime (P2)
│   │   └── claude_code.py   # Claude Code/Agent SDK runtime (P2)
│   ├── agentspec/
│   │   ├── loader.py        # YAML → pyagentspec Agent deserialization + validation
│   │   ├── sync.py          # Agent Spec YAML → MLflow sync logic (resolves skill refs)
│   │   └── export.py        # MLflow → Agent Spec JSON export
│   ├── benchmark/
│   │   ├── runner.py        # Execute eval dataset against agent×skill×task
│   │   └── results.py       # Format + record results in MLflow experiment
│   └── workflows/
│       ├── export.py        # n8n dev → validate → repo
│       └── import_.py       # repo → n8n prod
└── tests/
    ├── conftest.py
    ├── test_chat.py
    ├── test_agents_api.py
    ├── test_skills_api.py
    ├── test_registry.py
    ├── test_agentspec_loader.py
    ├── test_sync.py
    ├── test_benchmark.py
    └── test_workflows.py

agents/                       # Agent Spec YAML definitions (source of truth)
├── _shared/
│   ├── llm-ollama.yaml       # Shared OllamaConfig ($component_ref target)
│   └── mcp-genai.yaml        # Shared MCP server config for MetaMCP genai namespace
├── agent-ops.yaml            # Meta-agent for managing agents/skills
└── mlops.yaml                # Example agent definition

skills/                       # Seed skill definitions (synced to registry on deploy)
├── kubernetes-ops.yaml       # Skill: k8s operations (tasks + mcp_servers + prompt fragment)
├── mlflow-tracking.yaml      # Skill: MLflow experiment tracking
├── agent-management.yaml     # Skill: CRUD agents (used by agent-ops)
├── skill-management.yaml     # Skill: CRUD skills (used by agent-ops)
└── benchmark-runner.yaml     # Skill: run evaluations (used by agent-ops)

skills/eval/                  # Evaluation datasets per skill×task
├── kubernetes-ops/
│   ├── deploy-model.json     # Test cases for the deploy-model task
│   └── check-status.json     # Test cases for the check-status task
└── mlflow-tracking/
    └── log-metrics.json

workflows/                    # Versioned n8n workflow JSONs (exported from dev)
├── chat-v1.json
├── openai-compat-v1.json
└── ...
```

**Structure Decision**: Service code lives in `services/agent-gateway/` (not `src/` at repo root) to keep the monorepo clean — each service is self-contained with its own pyproject.toml and Dockerfile. The Helm chart follows the existing `charts/genai-*` pattern for ArgoCD auto-discovery. Agent definitions, skill definitions, and workflow JSONs live at repo root as shared artifacts. Skill YAML files in `skills/` are seed data synced to the registry on deploy — the CRUD API is the runtime source of truth.

**Design decision — no toolboxes/tools abstractions**: Our internal model uses MCP server URLs directly (with optional tool_filter). Agent Spec's MCPToolBox/StreamableHTTPTransport wrapping is only produced on export via `/agents/{name}/spec`. This keeps YAML authoring simple and avoids forcing users to understand Agent Spec's component_type hierarchy just to point at an MCP server.

## Research Decisions

### R1: Agent Spec Version

**Decision**: Target pyagentspec 26.2.0 (current latest)
**Rationale**: Spec said 26.1.0 but current `AgentSpecVersionEnum.current_version` is `26.2.0`. This version adds `auth` on RemoteTransport and `transforms` on Agent. Backward compatible — we can serialize at 26.1.0 for older consumers.
**Alternative rejected**: 25.4.x — missing `toolboxes` field on Agent, which we need for MCPToolBox.

### R2: MCP Server ↔ MetaMCP Mapping

**Decision**: Skills reference MetaMCP namespace endpoints directly as MCP server URLs. No MCPToolBox abstraction in our model — just URLs with optional tool filters.
**Rationale**: MetaMCP endpoints expose a single Streamable HTTP MCP interface per namespace. Wrapping these in MCPToolBox/StreamableHTTPTransport objects adds indirection we don't need. Skills just say "connect to this MCP server URL, use these tools." On Agent Spec export, we translate to MCPToolBox format for interop.
**Example** (our model):
```yaml
mcp_servers:
  - url: http://genai-metamcp.genai.svc.cluster.local:12008/metamcp/genai/mcp
    tool_filter: ["kubectl_get", "kubectl_apply"]
```
**Export** (Agent Spec JSON): translates to `toolboxes: [{ component_type: MCPToolBox, client_transport: { component_type: StreamableHTTPTransport, url: "..." } }]`

### R3: LLM Config Mapping

**Decision**: Use `OllamaConfig` pointing at LiteLLM (which proxies to Ollama). Store in shared `_shared/llm-ollama.yaml` referenced via `$component_ref`.
**Rationale**: OllamaConfig extends OpenAiCompatibleConfig — fields are `url`, `model_id`, `api_key` (SensitiveField). LiteLLM's `/v1` endpoint is OpenAI-compatible, so OllamaConfig with `url: http://genai-litellm.genai.svc.cluster.local:4000/v1` works. Using LiteLLM as the url (not raw Ollama) preserves trace logging.
**Alternative rejected**: OpenAiCompatibleConfig directly — OllamaConfig is more semantically correct and the inheritance is trivial (OllamaConfig is literally `pass`).

### R4: MLflow Prompt Registry Schema

**Decision**: Store agent definitions as MLflow prompts with convention:
- Prompt name: `agent:{name}` (e.g., `agent:mlops`)
- Prompt template: the system_prompt text
- Version tags: `runtime`, `workflow`, `llm_model`, `mcp_servers_json`, `agentspec_version`
- Task prompts: separate prompt `agent:{name}:{task}` per task

**Rationale**: MLflow's prompt registry supports named prompts with versioned templates and arbitrary tags. Tags carry structured metadata without requiring schema changes. The `agent:` prefix avoids collision with existing `{prompt_name}` prompts.
**Alternative rejected**: Storing full Agent Spec JSON as a prompt — MLflow prompt templates are strings, not structured data. Using tags keeps metadata queryable.

### R5: Runtime Routing Architecture

**Decision**: Gateway reads agent metadata from MLflow at invocation time, dispatches to runtime based on `runtime` tag.
```
Client → Gateway /v1/chat/completions (model=agent:mlops)
  → MLflow lookup: get prompt "agent:mlops" + tags
  → Runtime dispatch:
    - runtime=n8n → POST to n8n webhook (workflow from tag)
    - runtime=python → local pyagentspec execution
  → Stream response back in OpenAI SSE format
```
**Rationale**: MLflow is already deployed and serves as the single source of truth at runtime. The gateway is stateless — it reads from MLflow, routes to runtime, streams back. No agent state in the gateway.
**Alternative rejected**: Reading YAML files directly at runtime — requires filesystem access in the container and doesn't support dynamic updates without restart.

### R6: n8n Webhook Integration

**Decision**: Gateway translates between OpenAI format and n8n webhook format. The n8n `chat-v1` workflow already accepts `{ chatInput, sessionId }` via webhook and returns streaming responses.
**Translation**:
- OpenAI `messages[-1].content` → n8n `chatInput`
- OpenAI `user` or header → n8n `sessionId`
- n8n SSE chunks → OpenAI `data: {"choices":[{"delta":{"content":"..."}}]}` format

**Rationale**: The existing n8n chat-v1 workflow handles the full tool loop (MCP tool calls, session management, tracing). The gateway doesn't re-implement this — it just translates the wire format.

### R7: Workflow GitOps Pipeline

**Decision**: Two Taskfile tasks backed by Python scripts in `services/agent-gateway/`:
- `task workflows:export` — calls n8n API to list dev project workflows, validates each (schema, webhook reachability, test invocation), strips volatile/environment-specific fields, writes deterministic JSON to `workflows/`
- `task workflows:import` — reads `workflows/*.json`, resolves credentials by type/name for target environment, imports via n8n API

**Validation gate** (FR-015):
1. Schema check: workflow JSON has required fields (nodes, connections, trigger/webhook node)
2. Webhook reachability: if workflow has a webhook trigger, verify the URL responds
3. Test invocation: send a minimal test payload, verify non-error response

**Credential portability** (FR-020):
- On export: replace credential IDs with `{ "type": "ollamaApi", "name": "Ollama Local" }` portable references
- On import: look up credentials by type+name in target n8n, substitute IDs

**Deterministic JSON** (FR-019):
- Sort keys, stable node ordering by node name
- Strip: `id` (auto-generated), `updatedAt`, `createdAt`, `versionId`, `active`, `meta.executionCount`

### R8: Backward Compatibility (FR-008)

**Decision**: The gateway checks if `model` starts with `agent:`. If yes, agent path. If no, proxy to existing LiteLLM (same behavior as before).
**Rationale**: Existing clients using `model=qwen2.5:14b` or `model={prompt_name}` must not break. The gateway sits in front of LiteLLM and adds agent routing on top.

### R9: Agent = System Prompt + Skills

**Decision**: Agent YAML files follow Oracle Agent Spec format with `metadata.skills` referencing skill names. The system prompt is the agent's identity. Skills provide everything else — tools, specialized instructions, and testable tasks.

**Example `agents/mlops.yaml`**:
```yaml
component_type: Agent
name: mlops
description: MLOps assistant for model lifecycle management
metadata:
  runtime: n8n
  workflow: chat-v1
  skills:
    - kubernetes-ops
    - mlflow-tracking
mcp_servers:
  - url: http://genai-metamcp.genai.svc.cluster.local:12008/metamcp/genai/mcp
inputs:
  - title: domain
    type: string
    default: machine learning operations
llm_config:
  $component_ref: _shared/llm-ollama
system_prompt: |
  You are an expert in {{domain}}.
  You help users with model training, evaluation, deployment, and monitoring.
  You are methodical and always verify results after taking actions.
agentspec_version: "26.2.0"
```

Agents can declare their own `mcp_servers` (always-available). Skills bring additional MCP servers required for their tasks. At invocation, the effective set is agent's `mcp_servers` + all skill `mcp_servers` (deduplicated by URL). The agent's system prompt is purely identity; skills carry the task-specific instructions and may require specific MCP servers.

### R10: Skill Schema

**Decision**: A skill is a YAML file with tasks, MCP server references, prompt fragment, and evaluation metadata. Stored in MLflow as a registered model (versioned, tagged). CRUD API at runtime.

**Example `skills/kubernetes-ops.yaml`**:
```yaml
name: kubernetes-ops
description: Kubernetes cluster operations and deployment management
version: "1.0.0"
tags: ["infrastructure", "deployment"]

# MCP servers this skill connects to (MetaMCP namespace endpoints)
mcp_servers:
  - url: http://genai-metamcp.genai.svc.cluster.local:12008/metamcp/genai/mcp
    tool_filter: ["kubectl_get", "kubectl_apply", "kubectl_logs", "kubectl_describe"]

# Instructions appended to agent's system prompt when this skill is equipped
prompt_fragment: |
  When performing Kubernetes operations:
  - Always check current state before making changes
  - Use kubectl_get to inspect resources before applying
  - Verify deployments succeed with kubectl_describe after applying
  - Report pod status and any errors clearly

# Named tasks this skill enables (independently benchmarkable)
tasks:
  - name: deploy-model
    description: Deploy a trained model to the cluster
    inputs:
      - title: model_name
        type: string
      - title: namespace
        type: string
        default: genai
    evaluation:
      dataset: skills/eval/kubernetes-ops/deploy-model.json
      metrics: ["task_completion", "correctness"]

  - name: check-status
    description: Check deployment status and pod health
    inputs:
      - title: deployment_name
        type: string
    evaluation:
      dataset: skills/eval/kubernetes-ops/check-status.json
      metrics: ["task_completion", "accuracy"]
```

**Why MLflow registered models for skills**: MLflow models support versioning (each update = new version), arbitrary tags, and a REST API for CRUD. Using models (not prompts) for skills avoids conflating agents (prompts) and skills (models) in the same namespace.

**Why not MCPToolBox/toolboxes**: Agent Spec's MCPToolBox is an abstraction layer (component_type, client_transport, StreamableHTTPTransport) that wraps what is fundamentally an MCP server URL. We store the URL directly. On Agent Spec JSON export (`/agents/{name}/spec`), we translate to the MCPToolBox structure for interop. This keeps our internal model simple — an MCP server is a URL, optionally with a tool filter.

**Alternative rejected**: Separate database for skills — adds infrastructure. MLflow is already deployed and has the version+tag+API surface we need.

### R11: Unified Agent Invocation Model

**Decision**: The gateway resolves every agent invocation into a single, runtime-agnostic payload — the **AgentRunConfig**. This is the complete, reproducible recipe for an agent run. Every runtime receives the same inputs; the runtime is just the execution engine.

**AgentRunConfig** (what the gateway computes before dispatching):
```python
@dataclass
class AgentRunConfig:
    # Identity — from agent YAML system_prompt
    system_prompt: str

    # Capabilities — resolved from skills
    prompt_fragments: list[str]          # one per skill, appended to system_prompt
    mcp_servers: list[dict]              # merged from all skills — [{url, tool_filter}]
    allowed_tools: list[str]             # merged from skill tool_filters

    # Invocation
    message: str                         # user's input
    agent_params: dict                   # {{placeholder}} values

    # Metadata
    agent_name: str
    session_id: str
    llm_config: dict                     # model, url, api_key
```

**Composition steps** (same for ALL runtimes):
1. Load agent definition from MLflow (system prompt + mcp_servers + skill list + llm config)
2. For each skill, load from skills registry (prompt fragment + mcp_servers + tool_filter)
3. Compose:
   - `effective_prompt = system_prompt + "\n\n" + "\n\n".join(prompt_fragments)`
   - `mcp_servers = agent.mcp_servers + flatten(skill.mcp_servers for each skill)` → deduplicated by URL
   - `allowed_tools = union(skill.tool_filter for each skill)`
4. Resolve `{{placeholders}}` in effective_prompt from agent_params
5. Pass AgentRunConfig to runtime

**Runtime translation** (each runtime maps AgentRunConfig to its native format):

| Field | n8n | Python | Claude Code |
|-------|-----|--------|-------------|
| effective_prompt | Workflow system message node | `Agent(system_prompt=...)` | `--system-prompt "..."` |
| mcp_servers | MetaMCP namespace URL in workflow env | MCP server URLs → `MCPToolBox` at runtime | `--mcp-config mcp.json` |
| allowed_tools | n8n tool nodes (pre-configured) | tool_filter from skills | `--allowedTools "Read,Edit,..."` |
| message | `chatInput` in webhook POST body | User message in conversation | Prompt argument to `claude -p` |
| llm_config | `INFERENCE_BASE_URL` env var | `OllamaConfig(url=..., model_id=...)` | `--model` flag (uses Anthropic API) |
| session_id | n8n session memory | Conversation history | `--resume {session_id}` |

**Key invariant**: Given the same AgentRunConfig, any runtime should produce functionally equivalent results (modulo LLM differences). This is what makes benchmarking across runtimes meaningful — same inputs, different engines, compare outputs.

**Rationale**: Composition at runtime means skill updates take effect immediately — no re-sync needed. The agent's identity (system prompt) stays stable while capabilities (skills) evolve independently. The AgentRunConfig is also what gets logged to MLflow traces — you can reproduce any past invocation.

### R12: Agent-Ops Meta-Agent

**Decision**: `agent-ops` is a regular agent defined in `agents/agent-ops.yaml` with four skills:
- `agent-management` — tasks: create-agent, update-agent, delete-agent, list-agents
- `skill-management` — tasks: create-skill, update-skill, delete-skill, list-skills
- `benchmark-runner` — tasks: run-benchmark, list-results
- `n8n-workflow-ops` — tasks: list-workflows, get-workflow, create-workflow, update-workflow, validate-workflow, execute-workflow

The agent/skill management skills' MCP servers point at the gateway's own API (self-referential — agent-ops uses the gateway's `/agents` and `/skills` endpoints as MCP tools). This is implemented as a dedicated MCP server that wraps the gateway's REST API.

The n8n-workflow-ops skill uses the existing n8n MCP server in MetaMCP (20 tools: 7 node docs + 13 workflow CRUD). This gives agent-ops conversational access to all n8n workflow operations — listing workflows, reading workflow structure, creating new workflows, validating configurations, and triggering test executions. The tool_filter selects the workflow management tools, not the node documentation tools.

**Example `agents/agent-ops.yaml`**:
```yaml
component_type: Agent
name: agent-ops
description: Platform agent for managing agents, skills, workflows, and benchmarks
metadata:
  runtime: n8n
  workflow: chat-v1
  skills:
    - agent-management
    - skill-management
    - benchmark-runner
    - n8n-workflow-ops
llm_config:
  $component_ref: _shared/llm-ollama
system_prompt: |
  You are agent-ops, the platform management agent.
  You help users create, configure, and optimize AI agents.
  When asked to create or modify agents, use your management tools.
  When asked about capabilities, query the skills registry.
  When asked to test or benchmark, run evaluations and report results.
  When asked about workflows, use your n8n workflow tools to inspect,
  create, or validate workflows. Only modify workflows in the dev project.
  Be concise and confirm actions after completing them.
agentspec_version: "26.2.0"
```

**Example `skills/n8n-workflow-ops.yaml`**:
```yaml
name: n8n-workflow-ops
description: Manage n8n workflows — list, inspect, create, validate, execute
version: "1.0.0"
tags: ["automation", "workflows", "n8n"]

mcp_servers:
  - url: http://genai-metamcp.genai.svc.cluster.local:12008/metamcp/genai/mcp
    tool_filter:
    - list_workflows
    - get_workflow
    - create_workflow
    - update_workflow
    - delete_workflow
    - activate_workflow
    - deactivate_workflow
    - execute_workflow
    - get_workflow_executions
    - list_workflow_tags
    - validate_workflow
    - create_workflow_from_template
    - get_available_nodes

prompt_fragment: |
  When managing n8n workflows:
  - Only create or modify workflows in the dev project
  - Validate workflows before activating them
  - Report workflow structure clearly (nodes, connections, triggers)
  - Warn before deleting or deactivating active workflows
  - Use get_available_nodes to help users discover node types

tasks:
  - name: list-workflows
    description: List all workflows with their activation status
  - name: create-workflow
    description: Create a new workflow from description or template
  - name: validate-workflow
    description: Check a workflow for configuration errors
  - name: inspect-workflow
    description: Show workflow structure, nodes, and connections
```

**Alternative rejected**: Building agent-ops as a separate service — it's just an agent like any other, composed from skills. The only special thing is that its skills' MCP servers operate on the system itself.

### R13: Task Benchmarking Architecture

**Decision**: Evaluation datasets are JSON files in `skills/eval/{skill}/{task}.json`. Each file contains test cases:

```json
{
  "task": "deploy-model",
  "skill": "kubernetes-ops",
  "cases": [
    {
      "id": "deploy-basic",
      "input": "Deploy the fraud-detection model to the genai namespace",
      "expected_output_contains": ["deployment", "created", "fraud-detection"],
      "expected_tools_used": ["kubectl_apply"],
      "max_latency_seconds": 30
    },
    {
      "id": "deploy-with-replicas",
      "input": "Deploy sentiment-analysis with 3 replicas",
      "expected_output_contains": ["replicas: 3", "sentiment-analysis"],
      "expected_tools_used": ["kubectl_apply"]
    }
  ]
}
```

The benchmark runner:
1. Sends each test case to the agent via `/v1/chat/completions`
2. Records: actual output, tool calls made, latency
3. Evaluates: output contains expected strings, correct tools used, within latency budget
4. Logs to MLflow experiment `eval:{agent}:{skill}:{task}` with one run per benchmark execution

**Rationale**: Uses pyagentspec's evaluation model (Metric + Dataset → Evaluator) conceptually, but implemented simply as JSON test cases + assertion checks. MLflow experiments make results queryable and comparable across versions.

### R14: Claude Code Runtime (P2)

**Decision**: Claude Code as a runtime backend via CLI headless mode (`claude -p`), invoked from the gateway or directly from n8n Code nodes. Each agent invocation gets an isolated sandbox workspace.

**Architecture**:
```
Client → Gateway (model=agent:code-reviewer)
  → MLflow lookup → runtime=claude-code
  → Provision sandbox: /data/sandboxes/{agent}/{session-id}/
  → Clone/mount target repo into sandbox
  → Invoke: claude -p "{composed_prompt}" \
      --system-prompt "{identity + skill fragments}" \
      --allowedTools "Read,Edit,Grep,Glob,Bash(git *)" \
      --mcp-config /tmp/mcp-{session}.json \
      --output-format stream-json \
      --max-turns 10 \
      --max-budget-usd 5.00 \
      --permission-mode bypassPermissions
  → Stream response back as OpenAI SSE
  → Cleanup sandbox (or persist for session continuity)
```

**Sandbox isolation** (per agent invocation):
- k8s: `emptyDir` volume per pod, or PVC subdirectory `/data/sandboxes/{agent}/{session-id}/`
- Gateway creates sandbox dir, clones target repo (or mounts as read-only + overlay)
- CLI `cwd` pointed at sandbox — all file operations scoped to it
- `--allowedTools` restricts to safe tools (no `rm -rf`, no writes outside sandbox)
- Cleanup after session completes (or preserve for multi-turn via `--resume`)

**n8n integration** (two paths):
1. **Gateway-mediated**: n8n workflow calls gateway with `model=agent:{name}`, gateway dispatches to Claude Code runtime. Clean separation, all agents use same interface.
2. **Direct from n8n**: n8n Code node shells out to `claude -p`. Simpler for one-off tasks. Agent-ops can create these workflows.

```javascript
// n8n Code node — direct Claude Code invocation
const { execSync } = require('child_process');
const result = execSync(`claude -p "${$input.item.json.message}" \
  --system-prompt "${systemPrompt}" \
  --allowedTools "Read,Edit,Grep,Glob" \
  --output-format json \
  --max-turns 5`, {
  cwd: `/data/sandboxes/${agentName}/${sessionId}`,
  env: { ...process.env, ANTHROPIC_API_KEY: $env.ANTHROPIC_API_KEY },
  timeout: 120000
});
return JSON.parse(result);
```

**MCP config for Claude Code** (generated per invocation from skill mcp_servers):
```json
{
  "mcpServers": {
    "metamcp-genai": {
      "type": "sse",
      "url": "http://genai-metamcp.genai.svc.cluster.local:12008/metamcp/genai/mcp"
    }
  }
}
```

This gives Claude Code access to all MCP servers from the agent's skills (same servers as n8n runtime), plus its native file/bash/grep tools scoped to the sandbox.

**When to use Claude Code vs n8n**:

| Use Case | Runtime | Why |
|----------|---------|-----|
| Chat-based Q&A, simple tool use | n8n | Lower cost, existing workflow |
| Code review, refactoring, debugging | claude-code | Native code understanding, file manipulation |
| Multi-step codebase analysis | claude-code | Session continuity, deep reasoning |
| Workflow automation, data pipelines | n8n | Visual workflow builder, n8n node ecosystem |
| High-stakes tasks needing best reasoning | claude-code | Opus model access, extended thinking |

**Trade-offs**: Claude Code requires an Anthropic API key (not local Ollama). Cost per invocation is higher. Best reserved for high-value tasks where Claude's reasoning capabilities justify the cost. The gateway makes this transparent — same `model=agent:{name}` interface regardless of runtime.

### R15: Python Runtime (P2)

**Decision**: Defer to Phase 2. The Python runtime will use `pyagentspec` directly to execute agents locally — loading the Agent Spec, connecting to MetaMCP for tools, calling LiteLLM for inference. The interface is the same `Runtime` ABC as n8n.
**Rationale**: n8n runtime covers all P1 requirements. Python runtime adds value for lightweight agents that don't need n8n's full workflow engine.

## Key Integration Points

| From | To | Protocol | Notes |
|------|----|----------|-------|
| Client | Gateway | HTTP (OpenAI SSE) | `model=agent:{name}` |
| Gateway | MLflow (agents) | HTTP (MLflow REST API) | Prompt lookup by name, tag queries |
| Gateway | MLflow (skills) | HTTP (MLflow REST API) | Skill lookup via model registry |
| Gateway | n8n | HTTP (Webhook POST) | `chatInput` + `sessionId`, SSE response |
| Gateway | LiteLLM | HTTP (OpenAI proxy) | Passthrough for non-agent `model=` requests |
| agent-ops | Gateway | HTTP (REST) | Self-referential — agent-ops calls /agents, /skills APIs |
| `task agents:sync` | MLflow | HTTP (MLflow REST API) | Write prompts + tags |
| `task agents:sync` | Filesystem | YAML read | Load from `agents/` directory |
| `task agents:benchmark` | Gateway | HTTP (OpenAI) | Run test cases against agent |
| `task agents:benchmark` | MLflow | HTTP (MLflow REST API) | Record eval results |
| `task workflows:export` | n8n API | HTTP | List/get workflows from dev project |
| `task workflows:import` | n8n API | HTTP | Create/update workflows in prod project |
| Gateway | MetaMCP | — | Not direct — runtimes connect to MetaMCP via MCP server URLs from skills |

## Complexity Tracking

No constitution violations to justify — all decisions align with CLAUDE.md principles.

| Decision | Complexity | Why Acceptable |
|----------|-----------|----------------|
| New FastAPI service | Medium | Necessary — no existing service handles agent routing. Reuses pyagentspec, MLflow client. |
| Skills registry (MLflow models) | Medium | Reuses existing MLflow — no new database. Convention-based versioning via model registry. |
| Agent composition at runtime | Low | String concatenation (prompts) + URL dedup (MCP servers). Stateless in gateway. |
| agent-ops meta-agent | Low | Just another agent with skills. Self-referential via REST API as MCP server. |
| Task benchmarking | Medium | JSON test cases + MLflow experiments. No new infrastructure. |
| Workflow validation gate | Medium | Prevents broken workflows from reaching prod — essential for "only what works" principle |

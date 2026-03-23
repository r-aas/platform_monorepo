# Data Model: Agent Gateway

**Date**: 2026-03-20 | **Spec**: [spec.md](spec.md)

## Overview

The agent gateway has **no dedicated database**. All persistent state lives in existing systems:

| Data | Store | Access |
|------|-------|--------|
| Agent definitions (source of truth) | Git repo (`agents/*.yaml`) | Filesystem / Git |
| Agent definitions (runtime lookup) | MLflow prompt registry | MLflow REST API |
| Skill definitions (seed) | Git repo (`skills/*.yaml`) | Filesystem / Git |
| Skill definitions (runtime, CRUD) | MLflow model registry | MLflow REST API |
| Evaluation datasets | Git repo (`skills/eval/`) | Filesystem / Git |
| Benchmark results | MLflow experiments | MLflow REST API |
| Workflow definitions (source of truth) | Git repo (`workflows/*.json`) | Filesystem / Git |
| Workflow definitions (runtime) | n8n database | n8n REST API |
| Tool aggregation | MetaMCP | Streamable HTTP MCP |
| LLM inference | LiteLLM → Ollama | OpenAI-compat API |
| Traces | MLflow tracking | MLflow REST API |

## Entities

### Agent Definition (YAML → MLflow)

```
agents/{name}.yaml  ──sync──▶  MLflow prompt "agent:{name}"
                                 ├── template: system_prompt text
                                 └── tags: runtime, workflow, llm_model,
                                           llm_url, mcp_servers_json,
                                           agentspec_version, description
```

**Fields from Agent Spec YAML**:

| Field | Type | Stored In | Notes |
|-------|------|-----------|-------|
| name | string | MLflow prompt name (`agent:{name}`) | Unique identifier |
| description | string | Tag `agent_description` | Human-readable |
| system_prompt | string | MLflow prompt template | Supports `{{placeholder}}` |
| llm_config.url | string | Tag `llm_url` | LiteLLM endpoint |
| llm_config.model_id | string | Tag `llm_model` | e.g., `qwen2.5:14b` |
| mcp_servers | list | Tag `mcp_servers_json` (JSON) | MetaMCP endpoint URLs + tool filters |
| metadata.runtime | string | Tag `runtime` | `n8n` or `python` |
| metadata.workflow | string | Tag `workflow` | n8n workflow name |
| inputs | list | Tag `input_schema` (JSON) | Parameter schema |
| agentspec_version | string | Tag `agentspec_version` | e.g., `26.2.0` |

### Shared Component ($component_ref)

```
agents/_shared/llm-ollama.yaml   ──ref──▶  Referenced by agents via $component_ref
agents/_shared/mcp-genai.yaml    ──ref──▶  Referenced by agents via $component_ref
```

Shared components are not synced to MLflow independently — they're resolved during sync and their values are inlined into each agent's tags.

### Workflow Definition (n8n → Git → n8n)

```
n8n dev project  ──export──▶  workflows/{name}.json  ──import──▶  n8n prod project
```

**Portable JSON fields** (after export stripping):

| Field | Kept | Stripped |
|-------|------|---------|
| name | Yes | — |
| nodes | Yes (sorted by name) | — |
| connections | Yes | — |
| settings | Yes | — |
| id | — | Stripped (auto-generated) |
| active | — | Stripped (set on import) |
| updatedAt / createdAt | — | Stripped (volatile) |
| versionId | — | Stripped (instance-specific) |
| meta.executionCount | — | Stripped (volatile) |
| staticData | Conditional | Only if non-empty |

**Credential references** (portable format):

```json
// In exported JSON (portable):
"credentials": {
  "ollamaApi": { "$portable": true, "type": "ollamaApi", "name": "Ollama Local" }
}

// In n8n (instance-specific, resolved on import):
"credentials": {
  "ollamaApi": { "id": "42", "name": "Ollama Local" }
}
```

## State Transitions

### Agent Lifecycle

```
YAML authored → sync validates → MLflow prompt created/updated → gateway serves
     │                │                                               │
     ▼                ▼                                               ▼
  Git commit    Validation error              Client request with model=agent:{name}
               (rejects sync)                  → MLflow lookup → runtime dispatch
```

### Workflow Lifecycle

```
Edit in n8n dev → export validates → Git commit → import to n8n prod
      │                 │                                │
      ▼                 ▼                                ▼
  Dev project    Validation failure             Prod project (read-only)
  (editable)    (rejects export,                (import-only)
                 no commit)
```

### Skill Definition (YAML → MLflow Model Registry)

```
skills/{name}.yaml  ──seed──▶  MLflow model "skill:{name}"
CRUD API            ──write──▶  MLflow model "skill:{name}" (new versions)
```

**Skill fields**:

| Field | Type | Stored In | Notes |
|-------|------|-----------|-------|
| name | string | MLflow model name (`skill:{name}`) | Unique identifier |
| description | string | Model tag `description` | Human-readable |
| version | string | Model tag `version` | Semantic version |
| tags | string[] | Model tags | Categorization |
| mcp_servers | list[MCPServer] | Model tag `mcp_servers_json` | `[{url, tool_filter}]` — direct MCP server references |
| prompt_fragment | string | Model tag `prompt_fragment` | Instructions appended to agent prompt |
| tasks | Task[] | Model tag `tasks_json` | Named units of work with evaluation refs |

### Task (within Skill)

| Field | Type | Notes |
|-------|------|-------|
| name | string | Unique within skill |
| description | string | What this task does |
| inputs | Property[] | Expected input parameters |
| evaluation.dataset | string | Path to JSON eval dataset in repo |
| evaluation.metrics | string[] | Metric names to compute |

### Benchmark Results (MLflow Experiments)

```
MLflow experiment: eval:{agent}:{skill}:{task}
  └── Run per benchmark execution
       ├── Params: agent, skill, task, llm_model, skill_version
       ├── Metrics: pass_rate, avg_latency, total_cases
       └── Artifacts: per-case results JSON
```

### AgentRunConfig (computed at invocation time, logged to traces)

The gateway resolves every invocation into this structure before dispatching to any runtime. This is what gets logged to MLflow — the complete recipe to reproduce the run.

```
AgentRunConfig:
  system_prompt:     string     # agent's base identity prompt
  prompt_fragments:  string[]   # one per skill, appended to system_prompt
  mcp_servers:       list       # agent's own + all skills' — [{url, tool_filter}], deduplicated
  allowed_tools:     string[]   # merged tool filters from skills
  message:           string     # user's input
  agent_params:      dict       # {{placeholder}} values
  agent_name:        string
  session_id:        string
  llm_config:        dict       # model, url, api_key ref
  runtime:           string     # "n8n" | "python" | "claude-code"
```

Same AgentRunConfig → any runtime. Swap runtime, re-run, compare. This is what makes cross-runtime benchmarking work.

## Relationships

```
Agent ──has mcp_servers──▶ MCP Server URLs (always-available, agent-level)
Agent ──has skills──▶ Skill[] (metadata.skills = skill names)
Skill ──has tasks──▶ Task[] (named units of work)
Skill ──has mcp_servers──▶ MCP Server URLs (required for skill's tasks)
Skill ──has fragment──▶ prompt_fragment (appended to agent system_prompt)
Task ──has eval──▶ Evaluation Dataset (JSON in repo)
Agent ──references──▶ Workflow (metadata.workflow = workflow name)
Agent ──references──▶ LlmConfig (llm_config = OllamaConfig pointing at LiteLLM)
Agent ──synced-to──▶ MLflow Prompt (agent:{name})
Skill ──stored-in──▶ MLflow Model (skill:{name})
Workflow ──deployed-to──▶ n8n (webhook endpoint)
MCP Server URL ──proxied-by──▶ MetaMCP (namespace endpoint)
Benchmark ──recorded-in──▶ MLflow Experiment (eval:{agent}:{skill}:{task})

Agent-Ops ──manages──▶ Agent[] (via agent-management skill)
Agent-Ops ──manages──▶ Skill[] (via skill-management skill)
Agent-Ops ──runs──▶ Benchmark[] (via benchmark-runner skill)
```

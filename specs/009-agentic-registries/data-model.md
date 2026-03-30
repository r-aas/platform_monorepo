# Data Model: AgenticOps Registries

## Storage Layer

All registries use existing infrastructure. pgvector is the only new service — a dedicated PostgreSQL instance with the `vector` extension for embedding storage and similarity search.

| Registry | Storage | Source of Truth |
|----------|---------|-----------------|
| Agent | MLflow Registered Models + Tags | `{name}.SYSTEM` prompts |
| Skill | MLflow Registered Models + Tags | `{DOMAIN}.{SKILL}` prompts with `use_case: skill` |
| MCP | `catalog.yaml` + gateway runtime | Static YAML + live tool inventory |
| Vectors | pgvector (PostgreSQL + `vector` extension) | Evaluation embeddings, RAG retrieval |

### pgvector Connection Details

| Property | Value |
|----------|-------|
| Host (inter-container) | `pgvector` |
| Port | `5432` |
| User | `vectors` (env: `PGVECTOR_USER`) |
| Database | `vectors` (env: `PGVECTOR_DB`) |
| Password | Docker secret: `pgvector_password` |
| n8n node | `@n8n/n8n-nodes-langchain.vectorStorePGVector` |

Used by n8n workflows for:
- Storing document/chunk embeddings for RAG retrieval
- Evaluation dataset similarity search
- Agent memory (conversation embedding lookup)

---

## Agent Schema

An agent is an MLflow Registered Model named `{name}.SYSTEM`.

### MLflow Tags (on Registered Model)

| Tag Key | Type | Example | Required | Description |
|---------|------|---------|----------|-------------|
| `use_case` | string | `"agent"` | ✓ | Discriminator — identifies this as an agent |
| `agent.description` | string | `"MLOps assistant for platform management"` | ✓ | Human-readable summary |
| `agent.provider` | string | `"ollama"` | ✓ | LLM provider |
| `agent.model` | string | `""` | ✓ | Model override (empty = use `INFERENCE_DEFAULT_MODEL`) |
| `agent.temperature` | string | `"0.3"` | ✓ | Sampling temperature (0.0–1.0) |
| `agent.top_p` | string | `"0.9"` | ✓ | Nucleus sampling |
| `agent.num_ctx` | string | `"32768"` | ✓ | Context window size |
| `agent.max_iterations` | string | `"10"` | ✓ | Max agent loop iterations |
| `agent.mcp_servers` | string | `"n8n-manager,mlflow"` | ✓ | Comma-separated MCP server names, `"all"`, or `""` |
| `agent.skills` | string | `"coder.review,coder.debug"` | ✓ | Comma-separated `{DOMAIN}.{SKILL}` names, or `""` |

All tag values are strings (MLflow tag constraint). Numeric values parsed at read time.

### MLflow Model Version Tags

| Tag Key | Type | Description |
|---------|------|-------------|
| `mlflow.prompt.is_prompt` | string | `"true"` — marks this as a prompt |
| `mlflow.prompt.text` | string | The system prompt template |
| `mlflow.prompt.commit_message` | string | Version description |

### Resolved Agent Object (API response)

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

---

## Skill Schema

A skill is a prompt in the existing MLflow prompts registry with `use_case: skill`. Named `{DOMAIN}.{SKILL}` — the domain is an organizational category, not ownership. Any agent can equip any skill.

### MLflow Tags (on Registered Model)

| Tag Key | Type | Example | Required | Description |
|---------|------|---------|----------|-------------|
| `use_case` | string | `"skill"` | ✓ | Discriminator |
| `skill.description` | string | `"Structured code review with verdict"` | ✓ | What this skill does |
| `skill.required_mcp_servers` | string | `"mlflow"` | ✓ | MCP servers needed (empty = none) |
| `skill.output_format` | string | `"structured"` | | `structured` / `freeform` / `json` |

### Skill Prompt Template

The skill's prompt template (stored in `mlflow.prompt.text` on the model version) defines the instructions injected into the agent's system prompt when the skill is equipped and activated.

### Resolved Skill Object (API response)

```json
{
  "name": "coder.review",
  "description": "Structured code review with severity-tagged issues and verdict",
  "required_mcp_servers": [],
  "output_format": "structured",
  "equipped_by": ["coder", "mlops", "devops"],
  "prompt_version": "1",
  "prompt_alias": "production"
}
```

### Skill Inventory

| Name | Domain | Description | Required MCP | Output |
|------|--------|-------------|-------------|--------|
| `coder.review` | coder | Code review with severity tags and verdict | (none) | structured |
| `coder.debug` | coder | Root cause analysis with structured fix | (none) | structured |
| `writer.email` | writer | Professional email with structure constraints | (none) | structured |
| `writer.rewrite` | writer | Text transformation preserving meaning | (none) | freeform |
| `reasoner.solve` | reasoner | Step-by-step problem solving with verification | (none) | structured |
| `mlops.evaluate` | mlops | Run and summarize prompt evaluations | mlflow | structured |
| `curator.generate` | curator | Generate evaluation test cases for a skill | mlflow | structured |
| `curator.validate` | curator | Validate dataset quality and coverage | mlflow | structured |
| `specifier.define` | specifier | Define task acceptance criteria and edge cases | (none) | structured |
| `specifier.rubric` | specifier | Create scoring rubric for skill evaluation | (none) | structured |

---

## MCP Server Schema

MCP servers are defined in `mcp-servers/catalog.yaml`. The registry reads this file and enriches it with live tool data from the gateway.

### catalog.yaml Entry (existing)

```yaml
mlflow:
  type: server
  title: "MLflow"
  description: "Experiment tracking, run analysis, model registry"
  image: genai-mcp-mlflow:latest
  env: [...]
  secrets: [...]
```

### Resolved MCP Server Object (API response)

```json
{
  "name": "mlflow",
  "title": "MLflow",
  "description": "Experiment tracking, run analysis, model registry",
  "image": "genai-mcp-mlflow:latest",
  "tools": [
    "get_experiments",
    "get_runs",
    "get_run",
    "query_runs",
    "get_run_artifacts",
    "get_best_run",
    "compare_runs",
    "get_registered_models",
    "get_model_versions",
    "search_runs_by_tags"
  ],
  "tool_count": 10,
  "used_by_agents": ["mlops", "devops", "analyst"]
}
```

### MCP Server Inventory

| Server | Tools | Default Agents |
|--------|-------|----------------|
| `n8n-knowledge` | search_nodes, get_node, validate_node, search_templates, get_template, validate_workflow, create_workflow, list_workflows | mlops, mcp |
| `n8n-manager` | list_workflows, get_workflow, create_workflow, update_workflow, delete_workflow, activate_workflow, deactivate_workflow, list_executions, get_execution, run_webhook | mlops, mcp, devops |
| `mlflow` | get_experiments, get_runs, get_run, query_runs, get_run_artifacts, get_best_run, compare_runs, get_registered_models, get_model_versions, search_runs_by_tags | mlops, devops, analyst |
| `gitlab` | create_branch, create_issue, create_merge_request, create_or_update_file, push_files, search_repositories | (none by default) |
| `kubernetes` | kubectl_get, kubectl_describe, kubectl_apply, kubectl_delete, kubectl_logs, kubectl_exec, kubectl_port_forward, kubectl_patch, kubectl_rollout | (none by default) |
| `claude-code` | Bash, Read, Write, Edit, LS, Grep, Glob, Replace | (none by default) |

---

## Task Evaluation Schema

Every task (skill) is benchmarked using a triad: **dataset + method + metric**. All three are stored in existing infrastructure (MLflow + MinIO).

### Triad Overview

| Component | What It Is | Storage | Identity |
|-----------|-----------|---------|----------|
| **Dataset** | Input/expected pairs | MLflow Registered Model + MinIO JSONL | `eval:{DOMAIN}.{SKILL}` |
| **Method** | Agent + skill + config | Composed from agent registry + skill registry | `{agent}.{skill}` at runtime |
| **Metric** | Judge agent + scoring prompt | Agent registry entry + skill prompt | `{judge_agent}.{scoring_skill}` |

### Dataset Schema

#### MLflow Tags (on `eval:{DOMAIN}.{SKILL}` Registered Model)

| Tag Key | Type | Example | Description |
|---------|------|---------|-------------|
| `use_case` | string | `"dataset"` | Discriminator |
| `dataset.skill` | string | `"coder.review"` | Target skill being evaluated |
| `dataset.description` | string | `"Security-focused code review cases"` | What this dataset tests |
| `dataset.case_count` | string | `"42"` | Number of test cases |
| `dataset.tags` | string | `"security,injection,edge-cases"` | Content categories |

#### Dataset Record (JSONL line)

```json
{
  "id": "cr-sec-001",
  "input": {
    "code": "eval(input())",
    "language": "python",
    "context": "Web application handler"
  },
  "expected": {
    "verdict": "fail",
    "issues": [{"severity": "critical", "category": "security", "description": "Code injection via eval"}]
  },
  "tags": ["security", "injection"],
  "difficulty": "easy"
}
```

### Method Schema

A method is not a separate entity — it is the **composition** of an agent + a skill + the agent's config at evaluation time. Resolved from registry data:

```json
{
  "agent": "coder",
  "skill": "coder.review",
  "model": "qwen2.5:14b",
  "provider": "ollama",
  "temperature": 0.3,
  "mcp_servers": []
}
```

The same task can be evaluated across different methods:
- Same skill, different agents (does `devops` review code as well as `coder`?)
- Same agent, different models (Ollama local vs cloud API)
- Same agent, different prompt versions (v1 vs v2)

### Metric Schema

The metric is a **judge agent with a scoring task prompt**. The judge is itself an agent in the registry.

```json
{
  "judge_agent": "evaluator",
  "scoring_skill": "mlops.evaluate",
  "model": "anthropic/claude-sonnet-4-20250514",
  "provider": "litellm"
}
```

The judge receives three inputs per case:
1. **Original input** from the dataset
2. **Expected output** from the dataset
3. **Actual output** from the method

Returns a structured score per case.

### Evaluation Run (MLflow Experiment)

Each benchmark execution is logged as an MLflow experiment run combining all three components:

- **Params**: `task` (skill), `dataset` (name + version), `method.agent`, `method.model`, `method.prompt_version`, `metric.judge`, `metric.model`, `metric.scoring_skill`
- **Metrics**: `accuracy`, `precision`, `recall`, `f1`, `avg_score`, `case_count`
- **Artifacts**: Full per-case results as JSONL artifact

#### Per-Case Result Record

```json
{
  "case_id": "cr-sec-001",
  "input": { "code": "eval(input())", "language": "python" },
  "expected": { "verdict": "fail", "severity": "critical" },
  "actual": { "verdict": "fail", "issues": [{"severity": "critical", "category": "security"}] },
  "score": 0.95,
  "judge_reasoning": "Correctly identified injection vulnerability. Minor: missed specific eval() mention in description."
}
```

---

## Relationships

```
                              EVALUATION TRIAD
                    ┌────────────────────────────────────┐
                    │                                    │
┌─────────┐ equips ┌┴────────┐  evaluated by ┌─────────┐│  scored by  ┌──────────┐
│  Agent   │─ M:N ─│  Skill  │◄── 1:N ──────│ Dataset ││◄────────────│  Metric  │
│ (MLflow) │       │ (=Task) │               │ (MLflow) │             │(agent+   │
└────┬─────┘       └─────────┘               └──────────┘             │ skill)   │
     │ uses                                                           └──────────┘
     │ M:N                                        ▲                       ▲
┌────┴──────┐                                     │                       │
│ MCP Server│                              ┌──────┴───────────────────────┴──────┐
│ (catalog) │                              │  MLflow Experiment Run              │
└───────────┘                              │  params: task, dataset, method,     │
                                           │          metric                     │
                                           │  metrics: accuracy, f1, avg_score   │
                                           │  artifacts: per-case JSONL          │
                                           └────────────────────────────────────┘
```

- **Agent ↔ Skill (Task)**: Many-to-many via `agent.skills` tag. Any agent can equip any skill. Each skill defines a benchmarkable task.
- **Agent ↔ MCP Server**: Many-to-many via `agent.mcp_servers` tag. Servers are shared infrastructure.
- **Skill → MCP Server**: Dependency via `skill.required_mcp_servers`. Advisory — the skill needs these servers to function, but the agent must independently have them in `agent.mcp_servers`.
- **Skill ↔ Dataset**: One-to-many. Each dataset targets one skill (`dataset.skill` tag). A skill can have multiple datasets (e.g., security-focused, performance-focused).
- **Metric**: A judge agent + scoring skill. The metric is itself an agent in the registry — the system is self-referential. The `evaluator` agent with `mlops.evaluate` skill is the default metric, but any agent+skill pair can be a judge.
- **MLflow Experiment Run**: Ties together dataset + method (agent+skill+config) + metric (judge+scoring skill). All three are recorded as run params for full reproducibility.

### Validation Rule

When equipping a skill, if `skill.required_mcp_servers` lists servers not in the agent's `agent.mcp_servers`, the API returns a warning (not an error — the skill can still be equipped, but it won't have the tools it needs).

---

## Migration: Old → New Tag Format

### Agent Tag Migration

| Old (agent.config JSON) | New (structured tags) |
|------------------------|----------------------|
| `agent.config.provider` | `agent.provider` |
| `agent.config.model` | `agent.model` |
| `agent.config.temperature` | `agent.temperature` |
| `agent.config.top_p` | `agent.top_p` |
| `agent.config.num_ctx` | `agent.num_ctx` |
| `agent.config.max_iterations` | `agent.max_iterations` |
| `agent.config.mcp_tools` | `agent.mcp_servers` (values change — tool names → server names) |
| (none) | `agent.skills` (new) |
| (none) | `agent.description` (new) |

### Skill Tag Migration

Skill names are unchanged (`{DOMAIN}.{SKILL}` format preserved). Only tags change:

| Old Tag | New Tag |
|---------|---------|
| `use_case: "task"` | `use_case: "skill"` |
| `task.description` | `skill.description` |
| (none) | `skill.required_mcp_servers` |
| (none) | `skill.output_format` |

### Backward Compatibility

The Prompt Resolver checks for structured tags first. If `agent.provider` exists, use structured tags. If not, fall back to parsing `agent.config` JSON blob. This allows gradual migration.

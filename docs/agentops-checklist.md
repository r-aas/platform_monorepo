# MLOps / AgentOps Requirements Checklist

Status: Done = implemented, Partial = partial, No = not yet

## Prompt Management

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 1 | Prompt registry with versioning | Done | MLflow Model Registry, immutable versions with commit messages |
| 2 | Template variable substitution | Done | `{{variable}}` syntax, rendered in n8n Code nodes |
| 3 | Production/staging/canary aliases | Done | MLflow aliases, `set_canary`/`get_canary`/`clear_canary` actions |
| 4 | Prompt diff between versions | Done | `diff` action compares any two versions |
| 5 | Seed prompts (idempotent) | Done | `scripts/seed_prompts.py` + `data/seed-prompts.json` |
| 6 | Agent prompts in registry | Done | `agent:*` naming convention, agent config in MLflow tags |

## Evaluation & Testing

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 7 | LLM-as-judge scoring | Done | relevance, accuracy, coherence, custom criteria |
| 8 | Multi-test-case evaluation with aggregation | Done | Batch eval with `avg_scores` summary |
| 9 | A/B evaluation (production vs staging) | Done | `ab_eval` action, side-by-side comparison |
| 10 | Regression testing | Partial | Manual via smoke tests, no automated baseline comparison |
| 11 | Automated eval on prompt version change | No | Could trigger eval via MLflow webhook on version create |

## Deployment

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 12 | Canary deployment with traffic splitting | Done | Sticky session routing, configurable `traffic_pct` |
| 13 | Promote/rollback aliases | Done | `promote` action sets production alias to any version |
| 14 | n8n workflow promotion to k8s | Done | `task deploy` with namespace targeting |
| 15 | Progressive rollout | Partial | Manual `traffic_pct` adjustment, no auto-ramp |
| 16 | Auto-rollback on drift detection threshold | No | Drift detection exists, auto-rollback not wired |

## Observability

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 17 | Execution tracing | Done | MLflow experiments, structured trace logging |
| 18 | Trace search by prompt/source/status | Done | `search` action with filters |
| 19 | Latency, token, error rate metrics | Done | Logged per trace, aggregated in `summary` |
| 20 | Drift detection with baselines | Done | `baseline_set`/`baseline_get`/`drift_check` actions |
| 21 | Session management | Done | Multi-turn conversations with overflow protection |
| 22 | Cost tracking | Done | LiteLLM logs token counts + model pricing to MLflow |
| 23 | Trace health endpoint | Done | `health` action with `traces_last_hour` |

## Agent Operations

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 24 | Multi-agent support | Done | MCP agent + tool-based agents via router |
| 25 | Dynamic agent loading from registry | Done | `agent-router.json` loads prompt from MLflow at runtime |
| 26 | Agent config as data, not code | Done | System prompt + tags (`agent.tools`, `agent.model`, `agent.temperature`) |
| 27 | Session continuity across turns | Done | Session ID threaded through agent calls |
| 28 | Trace logging per agent interaction | Done | Each agent call creates a trace with `source` = agent name |
| 29 | Agent-to-agent communication | No | No inter-agent messaging; each agent is independent |
| 30 | Agent performance comparison dashboard | No | Traces exist per agent, no aggregated comparison view |

## Feedback & Human-in-the-Loop

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 31 | Trace feedback/rating submission | Done | `feedback` action with rating + correction + annotator |
| 32 | Feedback stored as MLflow tags | Done | Tags on trace run |
| 33 | Feedback aggregation | Partial | Manual via `feedback_search`, no automatic aggregation |
| 34 | Export corrections for fine-tuning | Done | `export_corrections` action |
| 35 | Feedback-driven prompt optimization | No | GEPA script exists but not wired to feedback loop |

## Data Management

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 36 | Dataset upload/download | Done | MLflow artifacts via `/datasets` endpoint |
| 37 | Experiment browsing and run inspection | Done | `/experiments` endpoint with `list`/`get`/`runs` |
| 38 | MinIO object storage backend | Done | MLflow artifact store |
| 39 | Dataset versioning with lineage | No | Each upload is a new run, no explicit version chain |

## Security & Safety

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 40 | Output filtering / guardrails | No | |
| 41 | PII detection | No | |
| 42 | RBAC for prompt/agent access | No | |
| 43 | Audit log for prompt changes | Partial | MLflow tracks version history with timestamps |

## Infrastructure

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 44 | Docker Compose local stack | Done | Full stack: n8n, MLflow, LiteLLM, PostgreSQL, MinIO, Ollama (host) |
| 45 | k8s promotion pipeline | Done | Taskfile-driven deploy to k3d namespaces |
| 46 | MCP gateway for tool aggregation | Done | `mcp-gateway` container, SSE transport |
| 47 | Subworkflow architecture (DRY) | Done | `_subworkflows/` + `_tools/` with RESOLVE placeholders |
| 48 | Config-as-code for agents | Done | Prompts seeded from Python, loaded at runtime |
| 49 | GitOps for workflow sync | No | Workflows in git but no automatic sync to n8n |
| 50 | LLM proxy gateway | Done | LiteLLM routes all Code node inference; `success_callback: ["mlflow"]` logs every call |
| 51 | Automatic LLM call logging | Done | LiteLLM → MLflow callback (model, messages, tokens, latency) |

## Summary

- **Done**: 38/51 (75%)
- **Partial**: 6/51 (12%)
- **Not yet**: 7/51 (14%)

## Agents

| Agent | Prompt Key | Type | Tools | Purpose |
|-------|------------|------|-------|---------|
| mlops | `agent:mlops` | tools | prompt_registry, run_evaluation, trace_operations, experiment_explorer | MLOps platform management |
| mcp | `agent:mcp` | mcp | All via MCP gateway | n8n workflow management |
| devops | `agent:devops` | tools | experiment_explorer, trace_operations | Infrastructure monitoring |
| analyst | `agent:analyst` | tools | trace_operations, experiment_explorer | Data analysis on traces |

# Architecture — GenAI MLOps v2.0

## System Overview

A Docker Compose-based local MLOps + AgentOps platform combining **n8n** (workflow automation) and **MLflow** (experiment tracking & prompt registry). All intelligence runs through n8n webhook workflows backed by MLflow as the universal data store. No new containers were added for v2.0 — all capabilities are n8n workflows and host scripts.

## Full Architecture

```
┌─ CLIENTS ────────────────────────────────────────────────────────────────────┐
│  OpenAI SDK  │  curl / browser  │  benchmark.py  │  drift_monitor.py        │
└──────┬───────┴────────┬─────────┴───────┬────────┴────────┬──────────────────┘
       │                │                 │                  │
┌──────┴────────────────┴─────────────────┴──────────────────┴──────────────────┐
│  n8n WEBHOOK GATEWAY  (8 workflows, ~50+ actions)                            │
│                                                                              │
│  ┌─────────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ openai-compat   │ │ prompt-crud  │ │ prompt-eval  │ │ mlflow-data      │  │
│  │ /v1/models      │ │ /prompts     │ │ /eval        │ │ /datasets        │  │
│  │ /v1/chat/*      │ │ 12 actions   │ │ 6 actions    │ │ 4 actions        │  │
│  │ /v1/embeddings  │ │ +canary mgmt │ │ +ab_eval     │ │                  │  │
│  │ +canary routing │ │              │ │ +judges      │ │                  │  │
│  └────────┬────────┘ └──────────────┘ └──────────────┘ └──────────────────┘  │
│  ┌────────┴────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ mlflow-expts    │ │ trace-v1     │ │ sessions-v1  │ │ mcp-agent        │  │
│  │ /experiments    │ │ /traces      │ │ /sessions    │ │ /agent           │  │
│  │ 5 actions       │ │ 10 actions:  │ │ 5 actions:   │ │ +session support │  │
│  │                 │ │ log,get,     │ │ create,get,  │ │ +trace logging   │  │
│  │                 │ │ search,      │ │ append,list, │ │                  │  │
│  │                 │ │ summary,     │ │ close        │ │                  │  │
│  │                 │ │ feedback,    │ │              │ │                  │  │
│  │                 │ │ feedback_*,  │ │              │ │                  │  │
│  │                 │ │ baseline_*,  │ │              │ │                  │  │
│  │                 │ │ drift_check  │ │              │ │                  │  │
│  └─────────────────┘ └──────────────┘ └──────────────┘ └──────────────────┘  │
│                              │                                               │
│          ┌───────────────────┘ trace logging (fire-and-forget)               │
│          │   from openai-compat, prompt-eval, mcp-agent                      │
└──────────┼───────────────────────────────────────────────────────────────────┘
           │
┌──────────┴───────────────────────────────────────────────────────────────────┐
│  MLflow  (:5050)                                                             │
│                                                                              │
│  ┌─────────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ Prompt Registry  │ │ Eval Expts   │ │ __datasets   │ │ __traces         │  │
│  │ (reg. models)    │ │ {name}-eval  │ │ (dataset     │ │ (execution logs, │  │
│  │ +canary tags     │ │ (runs w/     │ │  storage)    │ │  token counts,   │  │
│  │                  │ │  metrics +   │ │              │ │  feedback)       │  │
│  │                  │ │  judges)     │ │              │ │                  │  │
│  └─────────────────┘ └──────────────┘ └──────────────┘ └──────────────────┘  │
│  ┌─────────────────┐ ┌──────────────┐ ┌──────────────┐                       │
│  │ __sessions      │ │ __baselines  │ │ __drift      │                       │
│  │ (conversation   │ │ (performance │ │ (monitoring   │                       │
│  │  history as     │ │  thresholds) │ │  results)     │                       │
│  │  run tags)      │ │              │ │               │                       │
│  └─────────────────┘ └──────────────┘ └───────────────┘                       │
└──────────────────────────────────────────────────────────────────────────────┘
           │                    │                     │
┌──────────┴────────────────────┴─────────────────────┴────────────────────────┐
│  INFRASTRUCTURE                                                              │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ n8n-postgres  │  │mlflow-postgres│  │ MinIO (S3)   │  │ MCP Gateway      │  │
│  │ (workflow DB) │  │(tracking DB) │  │ (artifacts)  │  │ :8811/sse        │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │ 31 tools         │  │
│                                                        └──────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │ Ollama (HOST — native Metal GPU)  localhost:11434                       │ │
│  │ qwen2.5:14b, nomic-embed-text, + others                                │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Data Flows

### Chat Request Flow

```
Client → /v1/chat/completions {model, messages}
  │
  ├── model is MLflow prompt?
  │     ├── YES → fetch template → check canary config → roll dice
  │     │         ├── production version (default)
  │     │         └── staging version (if canary enabled & dice < traffic_pct)
  │     │         → render template → inference → trace log → response
  │     │           (system_fingerprint: fp_{name}_v{ver}[_canary])
  │     │
  │     └── NO → model in allowlist?
  │               ├── YES → direct passthrough → trace log → response
  │               │         (system_fingerprint: fp_inference)
  │               └── NO → 404
  │
  └── Response includes trace_id for feedback correlation
```

### Feedback Loop

```
Production traffic → trace logging → feedback collection → drift detection
     ↓                    ↓                ↓                    ↓
trace_id in response   MLflow __traces  corrections export   baseline comparison
     ↓                    ↓                ↓                    ↓
client submits rating  searchable logs  fine-tuning data     auto-alert if degraded
```

### Agent Session Flow

```
Client → /agent {message, session_id?}
  │
  ├── session_id present?
  │     ├── YES → Session Loader fetches history → prepends context
  │     └── NO  → stateless (current behavior)
  │
  └── AI Agent (Ollama + 31 MCP tools) → Trace Logger
        ├── logs trace (fire-and-forget)
        └── if session_id: appends user msg + agent response to session
```

### A/B Testing Flow

```
1. Set canary:  POST /prompts {action:"set_canary", name, staging_version, traffic_pct}
2. Traffic splits automatically in /v1/chat/completions
3. Both versions get traced with version info
4. Compare: POST /eval {action:"ab_eval", prompt_name, test_cases}
5. Review results → promote or rollback
6. Clear canary: POST /prompts {action:"clear_canary", name}
```

## Services & Ports

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| n8n | genai-n8n | 5678 | Workflow automation + API gateway |
| MLflow | genai-mlflow | 5050 | Experiment tracking, prompt registry |
| MinIO | genai-minio | 9000/9001 | S3-compatible artifact storage |
| MCP Gateway | genai-mcp-gateway | 8811 | Unified MCP server endpoint |
| n8n MCP Knowledge | genai-mcp-knowledge | 3100 (internal) | n8n node docs + templates |
| n8n MCP Manager | genai-mcp-manager | 3200 (internal) | Workflow CRUD + execution |
| n8n Postgres | genai-n8n-postgres | — | n8n metadata store |
| MLflow Postgres | genai-mlflow-postgres | — | MLflow backend store |

## Workflows Summary

| # | ID | Endpoint | Actions | v2.0 Changes |
|---|-----|----------|---------|--------------|
| 1 | `openai-compat-v1` | `GET/POST /webhook/v1/*` | models, chat, embeddings | +canary routing, +trace logging |
| 2 | `prompt-crud-v1` | `POST /webhook/prompts` | 12 actions | +set_canary, get_canary, clear_canary |
| 3 | `prompt-eval-v1` | `POST /webhook/eval` | 6 actions | +ab_eval, +trace logging |
| 4 | `mlflow-data-v1` | `POST /webhook/datasets` | 4 actions | — |
| 5 | `mlflow-experiments-v1` | `POST /webhook/experiments` | 5 actions | — |
| 6 | `mcp-agent-v1` | `POST /webhook/agent` | chat (+session) | +session support, +trace logging |
| 7 | `trace-v1` | `POST /webhook/traces` | 10 actions | **NEW** |
| 8 | `sessions-v1` | `POST /webhook/sessions` | 5 actions | **NEW** |

## MLflow Experiments (Data Model)

| Experiment | Purpose | Key Tags/Metrics |
|------------|---------|------------------|
| `{name}-eval` | Eval runs per prompt | prompt_version, test case results, judge scores |
| `__datasets` | Dataset storage | name, schema, rows as tags |
| `__traces` | Execution logs | trace_id, source, model, latency_ms, tokens, feedback |
| `__sessions` | Conversation history | session_id, status, msg_N_role/content |
| `__baselines` | Performance thresholds | prompt_name, avg_latency_ms, error_rate |

## Host Scripts

| Script | Task Command | Purpose |
|--------|-------------|---------|
| `smoke-test.sh` | `task test-smoke` | 53-case endpoint verification |
| `benchmark.py` | `task benchmark` | Prompt benchmarks (latency + quality) |
| `optimize_prompt.py` | `task optimize -- name` | GEPA optimization → staging |
| `drift_monitor.py` | `task drift-check` | Compare recent traces against baselines |
| `setup-n8n-api.sh` | `task setup-n8n-api` | Create n8n owner + API key |
| `setup-agent.sh` | `task setup-agent` | Create Ollama credential |

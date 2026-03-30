<!-- status: shipped -->
<!-- pr: #3 -->
# Spec 007: Agent Tool Routing

## Problem

All 5 agent-mode agents (`mlops`, `mcp`, `devops`, `analyst`, `coder`) use `mcp_tools: "all"`, giving every agent access to all 31 MCP tools. This causes:
- **Irrelevant tool calls**: coder agent tries to use MLflow tools, analyst tries to manage workflows
- **Slower agent loops**: larger tool lists increase token usage and latency per iteration
- **Reduced focus**: agents work better with tools scoped to their domain

## Current State

The MCP Client node in `chat.json` already supports dynamic tool selection:
```
include: mcp_tools === 'all' ? 'all' : 'selected'
includeTools: mcp_tools.split(',').map(t => t.trim())
```

The infrastructure is ready — only the `agent.config` tags in `seed-prompts.json` need updating.

## Available Tools (31 total)

| Server | Tools | Count |
|--------|-------|-------|
| n8n-manager | list_workflows, get_workflow, create_workflow, update_workflow, delete_workflow, activate_workflow, deactivate_workflow, list_executions, get_execution, delete_execution, run_webhook | 11 |
| mlflow | get_experiments, get_experiment_by_name, get_experiment_metrics, get_experiment_params, get_runs, get_run, query_runs, get_run_artifacts, get_run_artifact, get_run_metrics, get_run_metric, get_best_run, compare_runs, get_registered_models, get_model_versions, get_model_version, search_runs_by_tags, get_artifact_content, health | 19 |
| fetch | fetch | 1 |
| n8n-knowledge | (currently broken — encoding bug in gateway init) | 0 |

## Requirements

### FR-001: Per-agent tool subsets

Update `mcp_tools` in `agent.config` tag for each agent in `seed-prompts.json`:

| Agent | Current | New | Rationale |
|-------|---------|-----|-----------|
| `mcp` | `all` | `all` | General admin — needs everything |
| `mlops` | `all` | `all` | Platform management — needs workflow + MLflow + webhook bridge |
| `devops` | `all` | `run_webhook,list_workflows,get_workflow,list_executions,get_execution,activate_workflow,deactivate_workflow,health` | Monitoring + operational control. No workflow CRUD, no MLflow analysis |
| `analyst` | `all` | `run_webhook,get_experiments,get_experiment_by_name,get_experiment_metrics,get_experiment_params,get_runs,get_run,query_runs,get_run_metrics,get_run_metric,get_best_run,compare_runs,search_runs_by_tags,get_artifact_content` | Data analysis — MLflow read + webhook bridge for traces/experiments. No workflow management |
| `coder` | `all` | `fetch` | Documentation lookup only. n8n-knowledge tools added when server is fixed |
| `writer` | `""` | `""` | No change — chat only |
| `reasoner` | `""` | `""` | No change — chat only |

### FR-002: Request-level override preserved

The existing Prompt Resolver merge order (`defaults → storedCfg → reqCfg`) already handles this. A request body with `"mcp_tools": "all"` overrides the agent default. No code changes needed.

### FR-003: Smoke test coverage

Add 1 smoke test that verifies an agent with restricted tools responds correctly (doesn't error on tool selection).

## Files Changed

| File | What |
|------|------|
| `data/seed-prompts.json` | FR-001: Update mcp_tools for devops, analyst, coder |
| `scripts/smoke-test.sh` | FR-003: 1 new test case |
| `specs/007-agent-tool-routing/spec.md` | This spec |

## Verification

| Check | Expected |
|-------|----------|
| Smoke tests | All pass |
| Integration tests | 48/48 pass (no changes needed) |
| Offline tests | All pass |
| POST /chat with agent_name=coder | Works with restricted tools |
| POST /chat with agent_name=analyst | Works with restricted tools |
| POST /chat with agent_name=devops | Works with restricted tools |
| POST /chat with mcp_tools override | Override takes precedence |

## Known Issues

- **n8n-knowledge broken**: Gateway fails to initialize n8n-knowledge server (`invalid character 'â'`). Tool routing will add n8n-knowledge tools to coder/mlops once fixed.
- **Tool name stability**: MCP tool names could change between server versions. Tool routing uses exact names.

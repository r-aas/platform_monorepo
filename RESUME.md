# Platform Monorepo — Session Resume

## Session: 2026-03-21 — Factory Worker Run 4

### Built

- **Benchmark runner** — `services/agent-gateway/src/agent_gateway/benchmark/runner.py`
  - `CaseResult` + `BenchmarkResult` dataclasses with computed `pass_rate`, `avg_latency`, `total_cases`
  - `evaluate_case(case, actual_output, tools_used, latency_seconds)` — pure evaluation function
  - `load_dataset(path)` — loads JSON eval dataset from disk
  - `run_benchmark_task(skill, task, agent, dataset_path, tracking_uri)` — bridge for endpoint

- **Benchmark results** — `services/agent-gateway/src/agent_gateway/benchmark/results.py`
  - `record_results(results, tracking_uri)` — creates MLflow experiment `eval:{agent}:{skill}:{task}`, logs pass_rate/avg_latency/total_cases metrics, attaches per-case artifact

- **Benchmark endpoint** — `POST /skills/{name}/tasks/{task}/benchmark?agent={name}`
  - Returns 202 with benchmark_id (MLflow run_id), skill, task, agent
  - 404 for unknown skill/task, 422 if task has no evaluation ref

- **Eval datasets** — `skills/eval/kubernetes-ops/deploy-model.json` (3 cases) + `check-status.json` (2 cases)

- **Taskfile** — `task agents:benchmark SKILL=... TASK=... AGENT=...`

- **Gateway MCP server** — `services/agent-gateway/src/agent_gateway/mcp_server.py`
  - JSON-RPC 2.0 over HTTP POST at `/gateway-mcp`
  - Methods: `initialize`, `tools/list`, `tools/call`
  - Tools: `list_agents`, `get_agent`, `list_skills`, `get_skill`, `create_skill`, `delete_skill`
  - Proper JSON-RPC error codes (-32601 for method not found)
  - Success results: `{content: [{type: text, text: ...}]}`
  - Error results: `{content: [...], isError: true}`

### Test Status

89 tests passing:
- test_benchmark.py (17) — evaluate_case pure logic, load_dataset, BenchmarkResult aggregation, benchmark endpoint
- test_mcp_server.py (12) — tools/list schema, tools/call dispatch, error handling, initialize
- All prior 60 tests still passing

### Commits This Session

- `8ff828b` feat(agent-gateway): benchmark runner with eval datasets and MLflow logging [B.05]
- `c42dffa` feat(agent-gateway): gateway MCP server exposing REST API as MCP tools [B.06]

### Branch

`001-agent-gateway` — clean

### What's NOT Done (B items remaining)

| Item | What | Status |
|------|------|--------|
| B.07 | Python runtime | Blocked (needs pyagentspec eval) |
| B.08 | Claude Code runtime | Blocked (needs headless testing) |
| B.10-B.15 | Skill library expansion | Priority 2 — next after P1 complete |
| B.16-B.18 | New agents | Priority 3 |

### Next Steps

- [local] B.10: Skill YAML — data-ingestion (S3/GCS read → postgres/vector store) in `skills/data-ingestion.yaml`
- [local] B.11: Skill YAML — vector-store-ops (pgvector/qdrant index management) in `skills/vector-store-ops.yaml`

### Notes

- All Priority 1 non-blocked items complete (B.01–B.06, B.09)
- MCP server at `/gateway-mcp` uses raw JSON-RPC — no fastmcp dependency needed for stub
- registry.py functions (get_agent, list_agents) are async — await directly, NOT to_thread
- skills_registry.py functions are sync — use asyncio.to_thread
- `uv run pytest` MUST be run from `services/agent-gateway/`, not monorepo root

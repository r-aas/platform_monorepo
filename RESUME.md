# Platform Monorepo — Session Resume

## Session: 2026-03-21 — Factory Worker Run 3

### Built

- **Workflow export** — `services/agent-gateway/src/agent_gateway/workflows/export.py`
  - `strip_volatile(workflow)` — removes id, active, updatedAt, createdAt, versionId, meta.executionCount
  - `sort_nodes(workflow)` — alphabetical sort for stable diffs
  - `portabilize_credentials(workflow)` — replaces raw credential IDs with `{$portable: true, type, name}`
  - `export_workflow(workflow)` — full pipeline (strip → sort → portabilize)
  - `fetch_workflows(n8n_base_url, api_key)` — async fetch from n8n API
  - `export_all(n8n_base_url, api_key, output_dir)` — fetch + export all to JSON files

- **Workflow import** — `services/agent-gateway/src/agent_gateway/workflows/import_.py`
  - `fetch_credentials(n8n_base_url, api_key)` — returns `{(type, name): id}` map
  - `resolve_credentials(workflow, cred_map)` — replaces portable refs with real IDs; raises ValueError on missing
  - `import_workflow(workflow, n8n_base_url, api_key)` — POST to target n8n
  - `import_all(workflows_dir, n8n_base_url, api_key)` — resolve + import all JSONs

- **Taskfile tasks** — `task workflows:export` and `task workflows:import` wired to `settings.n8n_base_url` / `settings.n8n_api_key`

### Test Status

60 tests passing:
- test_workflows.py (21) — full coverage of all transformation + resolution functions
- All prior 39 tests still passing

### Commits This Session

- `0577bf8` feat(agent-gateway): workflow export/import with validation gate [B.04]

### Branch

`001-agent-gateway` — clean

### What's NOT Done (B items remaining)

| Item | What | Status |
|------|------|--------|
| B.05 | Benchmark runner | Not started |
| B.06 | Gateway MCP server | Not started |
| B.07 | Python runtime | Blocked (needs pyagentspec eval) |
| B.08 | Claude Code runtime | Blocked (needs headless testing) |

### Next Steps

- [local] B.05: Benchmark runner (Phase 8, T047-T052) — `benchmark/runner.py`, `results.py`
- [local] B.06: Gateway MCP server (T045) — `mcp_server.py`

### Notes

- `uv run pytest` MUST be run from `services/agent-gateway/`, not monorepo root
- Workflow export/import design: pure functions for transformation, async thin wrappers for network — test without mocks
- `task workflows:export` reads `AGW_N8N_BASE_URL` and `AGW_N8N_API_KEY` from env (or config defaults)

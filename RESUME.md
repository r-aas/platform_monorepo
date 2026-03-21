# Platform Monorepo — Session Resume

## Session: 2026-03-21 — Factory Worker Run 2

### Built

- **Hybrid embedding search** — `services/agent-gateway/src/agent_gateway/embeddings.py`
  - `cosine_similarity(a, b)` — pure vector math
  - `get_embedding(text)` — async, calls Ollama `/v1/embeddings`, returns `None` on failure
  - `hybrid_score(keyword, embedding_sim)` — 70/30 blend, graceful fallback to keyword-only
- **Wired into all 3 search endpoints**: agents/search, skills/search, tasks/search, mcp/search
- **Config**: added `AGW_OLLAMA_BASE_URL` (default `http://192.168.5.2:11434`) and `AGW_OLLAMA_EMBEDDING_MODEL` (default `nomic-embed-text`)
- **Fixed test_registry.py regression** from B.09: updated mocks to use `get_prompt_version` instead of `get_prompt` (MLflow 3.x API)
- 39 tests passing, 0 lint errors

### Test Status

39 tests passing:
- test_embeddings.py (9) — cosine sim, get_embedding success/fail, hybrid_score variants
- test_registry.py (3) — fixed to mock get_prompt_version
- All prior tests passing

### Commits This Session

- `3b7aa3e` feat(agent-gateway): add hybrid embedding search to all search endpoints [B.02]

### Branch

`001-agent-gateway` — clean

### What's NOT Done (B items remaining)

| Item | What | Status |
|------|------|--------|
| B.04 | Workflow export/validation | Not started |
| B.05 | Benchmark runner | Not started |
| B.06 | Gateway MCP server | Not started |
| B.07 | Python runtime | Blocked (needs pyagentspec eval) |
| B.08 | Claude Code runtime | Blocked (needs headless testing) |

### Next Steps

- [local] B.04: Workflow GitOps export (Phase 6, T038-T042) — `workflows/export.py`, `import_.py`
- [local] B.05: Benchmark runner (Phase 8, T047-T052) — `benchmark/runner.py`, `results.py`
- [local] B.06: Gateway MCP server (T045) — `mcp_server.py`

### Notes

- `uv run pytest` MUST be run from `services/agent-gateway/`, not monorepo root
- Post-commit test failures from monorepo root are false negatives (ModuleNotFoundError on agent_gateway)
- Ollama embedding model `nomic-embed-text` must be pulled: `ollama pull nomic-embed-text`

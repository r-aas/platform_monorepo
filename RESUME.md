# Platform Monorepo — Session Resume

## Session: 2026-03-21 — Factory Worker Run 12

### Built

- **Embedding LRU Cache** — `services/agent-gateway/src/agent_gateway/embeddings.py`
  - `EmbeddingCache` class: `OrderedDict`-based LRU eviction, configurable `maxsize` (default 512)
  - Module-level `_cache` singleton shared across all callers
  - `get_embedding()` now checks cache before HTTP — repeated texts skip Ollama entirely
  - Failed embeddings (None) are NOT cached
  - `clear_embedding_cache()` / `embedding_cache_size()` helpers for testing
  - 8 new tests: 5 EmbeddingCache unit tests + 3 integration tests via get_embedding

- **Skill search endpoint coverage** — `tests/test_skills_api.py`
  - 4 new tests for GET /skills/search
  - Cases: keyword match, no match → empty, hybrid scoring with embedding, fallback to keyword-only

- **Agent search endpoint coverage** — `tests/test_agents_api.py` (new file)
  - 4 new tests for GET /agents/search
  - Same 4-case pattern as skills tests

### Test Status

214 tests passing (+16 from run 12):
- 8 new in test_embeddings.py (D.01 cache)
- 4 new in test_skills_api.py (D.02 skill search)
- 4 new in test_agents_api.py (D.03 agent search, new file)
- All prior 198 tests still passing

### Commits This Run

- `365d12d` feat(agent-gateway): LRU embedding cache — EmbeddingCache + module singleton [D.01]
- `49003c7` test(agent-gateway): skill + agent semantic search endpoint coverage [D.02][D.03]

### Branch

`001-agent-gateway` — clean

### Phase D Status

| Item | What | Status |
|------|------|--------|
| D.01 | Embedding service LRU cache | ✅ Done |
| D.02 | Skill search with semantic similarity | ✅ Done (B.02 impl + tests added) |
| D.03 | Agent search with semantic similarity | ✅ Done (B.02 impl + tests added) |
| D.04 | MCP tool search with semantic similarity | ⏳ Next |
| D.05 | Benchmark runner end-to-end | Queued |
| D.06 | Eval dataset expansion | Queued |
| D.07 | Auto-prompt optimization | Queued |

### Next Steps

- [local] Phase D: D.04 — MCP tool search with semantic similarity
  - Similar to D.02/D.03: check if implementation exists in routers/mcp.py
  - If yes: add endpoint tests for /mcp/search (keyword, no-match, hybrid, fallback)
  - If coverage gap: add implementation first

### Notes

- Cache test isolation pattern: call `clear_embedding_cache()` at start of each test that uses `get_embedding()` — module singleton persists across tests
- D.02+D.03 implementations were already present from B.02 — tests confirmed correctness

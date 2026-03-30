<!-- status: draft -->
# Plan 020: Dashboard Data Enrichment

## Approach

Enrich the existing `scripts/dashboard.py` with 6 new data collectors. All changes are additive — no existing code modified except wiring new functions into the poll loops and adding UI panels.

## Architecture

```
dashboard.py
├── poll_infra (5s) ← existing
│   ├── _docker_stats()
│   ├── _probe_webhooks()
│   ├── _kubectl_pods()
│   ├── _kubectl_nodes()
│   ├── _neo4j_health()      ← NEW (FR-004)
│   └── _pgvector_health()   ← NEW (FR-005)
├── poll_mlops (30s) ← existing
│   ├── _langfuse_metrics() ← ENHANCED (FR-006)
│   ├── _mlflow_metrics()
│   ├── _n8n_executions()   ← NEW (FR-001)
│   ├── _litellm_metrics()  ← NEW (FR-002)
│   └── _prompt_lifecycle()  ← NEW (FR-003)
└── poll_platform (30s) ← existing (unchanged)
```

## Technology Decisions

### TD-001: n8n Execution API
Use n8n REST API `GET /api/v1/executions` with the API key from `secrets/n8n_api_key`. This API returns workflow name, status, timing, and error details. Verified working locally.

### TD-002: LiteLLM Metrics
LiteLLM's `/metrics` prometheus endpoint returns empty (not configured). Instead, use Langfuse's per-model breakdown which already captures LiteLLM's callback data. FR-002 will use `GET /api/public/observations?type=GENERATION` grouped by model field. This avoids adding LiteLLM config and leverages data already flowing through.

### TD-003: Neo4j Health
Use Neo4j HTTP API at `http://neo4j:7474` for status check (returns version info). For node/relationship counts, use the query endpoint `POST /db/neo4j/query/v2` with Cypher queries. No auth needed for community edition in Docker network.

### TD-004: pgvector Health
Use `asyncpg` (already a transitive dep via many services) to connect: `host=pgvector, user=vectors, db=vectors, password=<from secret>`. Query `pg_extension` for version and `pg_stat_user_tables` for vector table info.

### TD-005: Langfuse Model Breakdown
Enhance existing `_langfuse_metrics()` to add per-model grouping. Use `GET /api/public/observations?type=GENERATION` with pagination to get model name, token counts, and status for aggregation.

### TD-006: Prompt Lifecycle
Enhance existing prompt listing by calling `POST /webhook/prompts {"action":"list"}` (already done) and adding version/canary details. Each prompt in the list already returns aliases and version info — just need to surface it to the UI.

## Files Changed

| File | Change | Lines Est. |
|------|--------|-----------|
| `scripts/dashboard.py` | Add 6 new collector functions, wire into poll loops | +200 |
| `scripts/dashboard-static/index.html` | Add Operations panels (executions, inference, prompts) | +80 |
| `scripts/dashboard-static/topology.js` | Neo4j/pgvector node badges | +20 |
| `scripts/smoke-test.sh` | Dashboard API assertions for new fields | +30 |
| `tests/test_dashboard_enrichment.py` | Unit tests for new collectors (offline) | +60 |

## Implementation Order

1. **FR-004 + FR-005**: Neo4j and pgvector health (infra poll, simplest — just HTTP/SQL probes)
2. **FR-001**: n8n executions (most operationally useful, well-documented API)
3. **FR-006**: Langfuse model breakdown (enhance existing function)
4. **FR-003**: Prompt lifecycle (enhance existing data with version/canary badges)
5. **FR-002**: LiteLLM metrics via Langfuse (depends on FR-006 model breakdown)

## Risks

| Risk | Mitigation |
|------|-----------|
| n8n API key missing/expired | Graceful fallback — show "API key needed" badge |
| Neo4j Cypher query slow | 3s timeout, cache result for 30s |
| pgvector password not in secrets | Read from `secrets/pgvector_password`, fallback to env var |
| Langfuse pagination for model breakdown | Limit to last 100 observations, aggregate in-memory |
| Dashboard.py exceeding manageable size | Extract collectors into `scripts/dashboard_collectors.py` if >500 lines added |

## Dependencies

- n8n REST API key (`secrets/n8n_api_key`) — already exists from `setup-n8n-api.sh`
- Langfuse API keys — already configured in dashboard
- Neo4j on port 7474 — already in compose
- pgvector password — already in secrets
- No new Python packages needed (httpx already available)

<!-- status: draft -->
# Tasks 020: Dashboard Data Enrichment

## Task Order (TDD)

### Phase 1: Data Store Health (FR-004, FR-005)

#### Task 1: Neo4j health collector
**Test first**: `tests/test_dashboard_enrichment.py::test_neo4j_health_response_shape`
- Add `_neo4j_health()` to `dashboard.py`
- Probe `GET http://neo4j:7474` for status + version
- Cypher query for node/relationship counts via `/db/neo4j/query/v2`
- Wire into `poll_infra` (5s cycle)
- Add to `/api/status` response under `services.neo4j`
- 3s timeout, graceful degradation if Neo4j down

**Files**: `scripts/dashboard.py`, `tests/test_dashboard_enrichment.py`
**SC**: SC-007, SC-008

#### Task 2: pgvector health collector
**Test first**: `tests/test_dashboard_enrichment.py::test_pgvector_health_response_shape`
- Add `_pgvector_health()` to `dashboard.py`
- Connect via httpx to pgvector's existing health probe OR subprocess psql
- Query extension version, vector table count, total vectors
- Wire into `poll_infra` (5s cycle)
- Add to `/api/status` response under `services.pgvector`

**Files**: `scripts/dashboard.py`, `tests/test_dashboard_enrichment.py`
**SC**: SC-009, SC-010

#### Task 3: Topology badges for Neo4j + pgvector
- Add node/relationship count badge to Neo4j topology node
- Add vector count badge to pgvector topology node
- Health coloring already works (service status)

**Files**: `scripts/dashboard-static/topology.js`
**SC**: SC-008, SC-010

### Phase 2: n8n Executions (FR-001)

#### Task 4: n8n execution history collector
**Test first**: `tests/test_dashboard_enrichment.py::test_n8n_executions_response_shape`
- Add `_n8n_executions()` to `dashboard.py`
- `GET /api/v1/executions?limit=50` with API key from `secrets/n8n_api_key`
- Compute: success_rate, errors_1h, errors_24h, avg_duration by workflow
- Wire into `poll_mlops` (30s cycle)
- Add to `/api/status` under `mlops.executions`

**Files**: `scripts/dashboard.py`, `tests/test_dashboard_enrichment.py`
**SC**: SC-001

#### Task 5: Executions UI panel
- Add "Workflow Executions" panel to Operations tab
- Success rate gauge, error count badges
- Scrollable recent executions list with status icons
- Workflow name, duration, timestamp, error message (if failed)

**Files**: `scripts/dashboard-static/index.html`
**SC**: SC-002

### Phase 3: Langfuse Enhancement (FR-006)

#### Task 6: Langfuse model breakdown + error rate
**Test first**: `tests/test_dashboard_enrichment.py::test_langfuse_model_breakdown_shape`
- Enhance `_langfuse_metrics()` in `dashboard.py`
- Query `GET /api/public/observations?type=GENERATION&limit=100`
- Group by model: requests, tokens_in, tokens_out, avg_latency
- Compute error_rate from status codes
- Add to `/api/status` under `mlops.langfuse.by_model` and `mlops.langfuse.error_rate`

**Files**: `scripts/dashboard.py`, `tests/test_dashboard_enrichment.py`
**SC**: SC-011

#### Task 7: Langfuse model breakdown UI
- Add per-model breakdown table to Operations tab Langfuse panel
- Error rate gauge
- Sortable columns: model, requests, tokens, latency

**Files**: `scripts/dashboard-static/index.html`
**SC**: SC-012

### Phase 4: Prompt Lifecycle (FR-003)

#### Task 8: Prompt lifecycle enrichment
**Test first**: `tests/test_dashboard_enrichment.py::test_prompt_lifecycle_shape`
- Enhance existing prompt list data in `poll_mlops`
- Extract: version_count, production_version, staging_version, canary_enabled, canary_pct
- Add to `/api/status` under `prompts` array

**Files**: `scripts/dashboard.py`, `tests/test_dashboard_enrichment.py`
**SC**: SC-005

#### Task 9: Prompt version badges in UI
- Add version badge to agent/prompt cards in Services tab
- Show canary indicator when active (% split)
- Production version number + "v{N}" badge

**Files**: `scripts/dashboard-static/index.html`
**SC**: SC-006

### Phase 5: LiteLLM via Langfuse (FR-002)

#### Task 10: LiteLLM metrics from Langfuse data
**Test first**: `tests/test_dashboard_enrichment.py::test_inference_metrics_shape`
- Derive from FR-006 model breakdown data (already computed)
- Add to `/api/status` under `mlops.inference`
- Per-model: requests, tokens_in, tokens_out, avg_latency_ms, errors

**Files**: `scripts/dashboard.py`, `tests/test_dashboard_enrichment.py`
**SC**: SC-003

#### Task 11: Inference metrics UI panel
- Add "Inference Metrics" panel to Operations tab
- Per-model table with requests, tokens, latency, errors
- Total token count summary

**Files**: `scripts/dashboard-static/index.html`
**SC**: SC-004

### Phase 6: Smoke Tests + Verification

#### Task 12: Smoke test additions
- Add dashboard API assertions for new fields in `scripts/smoke-test.sh`
- Verify: `mlops.executions`, `mlops.inference`, `mlops.langfuse.by_model`, `prompts[].production_version`, `services.neo4j`, `services.pgvector`

**Files**: `scripts/smoke-test.sh`

#### Task 13: Full verification
- Run `task qa:smoke` — all new tests pass
- Run `task dashboard` — verify UI panels render
- Screenshot proof of new panels
- Update RESUME.md

## Dependencies

```
Task 1 ──────────────────────────┐
Task 2 ──────────────────────────┤
Task 3 (depends on 1, 2) ───────┤
Task 4 ──────────────────────────┤
Task 5 (depends on 4) ──────────┤
Task 6 ──────────────────────────┤
Task 7 (depends on 6) ──────────┤
Task 8 ──────────────────────────┤
Task 9 (depends on 8) ──────────┤
Task 10 (depends on 6) ─────────┤
Task 11 (depends on 10) ────────┤
Task 12 (depends on all) ───────┤
Task 13 (depends on 12) ────────┘
```

Parallelizable: Tasks 1+2, 4, 6, 8 can all run in parallel (independent collectors).

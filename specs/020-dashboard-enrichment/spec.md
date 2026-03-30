<!-- status: shipped -->
<!-- pr: #16 -->
# Spec 020: Dashboard Data Enrichment

## Problem

The Observatory Dashboard (Spec 014) covers ~40% of available stack data. Critical operational signals are invisible:

1. **n8n execution history** — no visibility into workflow success/fail rates, error patterns, or execution trends. When a workflow breaks, we only know via smoke test failure, not real-time.
2. **LiteLLM cost/usage** — no token spend tracking per model or request. Can't answer "how much inference am I burning?"
3. **Prompt lifecycle** — no view of version history, canary experiment results, or A/B test outcomes. Promotion decisions require manual API calls.
4. **Data store health** — Neo4j and pgvector have zero monitoring. Graph and vector stores could be down or degraded without dashboard awareness.
5. **LLM performance distribution** — Langfuse has latency data but the dashboard only shows p50/p95 aggregates. No per-model breakdown, no error rate visibility.

The dashboard should be the single pane of glass for the entire stack — Constitution Principle XII requires it to be "a live, real-time topology of every subsystem, service, agent, and MCP server."

## Approach

Enrich the existing `scripts/dashboard.py` with new data collectors on the slow poll path (30s). Add new UI panels to the Services and Operations tabs. No new services — all data comes from existing APIs.

**Priority order** (highest impact first):
1. n8n execution history (most operationally useful)
2. LiteLLM model metrics (cost visibility)
3. Prompt version timeline (prompt lifecycle visibility)
4. Neo4j/pgvector health (data store awareness)

## Requirements

### FR-001: n8n Execution History

The dashboard polls n8n REST API `GET /api/v1/executions?limit=50` (30s cycle) and displays:
- Last 50 executions: workflow name, status (success/error/waiting), started_at, finished_at, duration
- Aggregated stats: success rate (%), error count (last 1h/24h), avg duration by workflow
- Error details: for failed executions, show the error message and failing node name
- Displayed in Operations tab as a new "Workflow Executions" panel

**SC-001**: Dashboard `/api/status` response includes `mlops.executions` with `total`, `success_rate`, `errors_1h`, `errors_24h`, `recent` (last 10 executions).

**SC-002**: Operations tab shows execution success rate gauge, error count badges, and a scrollable recent executions list with status icons.

### FR-002: LiteLLM Model Metrics

The dashboard polls LiteLLM's `/metrics` prometheus endpoint (30s cycle) and extracts:
- Total requests per model
- Total tokens (input + output) per model
- Average latency per model
- Error count per model
- Displayed in Operations tab as "Inference Metrics" panel with per-model breakdown

**SC-003**: Dashboard `/api/status` response includes `mlops.inference` with per-model `requests`, `tokens_in`, `tokens_out`, `avg_latency_ms`, `errors`.

**SC-004**: Operations tab shows a model metrics table with sortable columns.

### FR-003: Prompt Version Timeline

The dashboard polls n8n webhook `POST /webhook/prompts {"action":"list"}` (30s cycle, already partially done) and enriches with:
- Per-prompt version count, current production version, staging version (if canary active)
- Canary status and traffic split percentage
- Last promotion date (from version timestamps)
- Displayed in Services tab under Agents section as version badges

**SC-005**: Dashboard `/api/status` response includes `prompts` array with `name`, `production_version`, `staging_version`, `canary_enabled`, `canary_pct`, `version_count`, `last_updated`.

**SC-006**: Agent cards show production version badge and canary indicator when active.

### FR-004: Neo4j Health Check

The dashboard probes Neo4j HTTP API `GET http://neo4j:7474` (5s infra cycle) and reports:
- Connection status (up/down)
- Node/relationship counts via Cypher: `MATCH (n) RETURN count(n)` + `MATCH ()-[r]->() RETURN count(r)`
- Displayed in topology and service cards

**SC-007**: Dashboard `/api/status` includes `services.neo4j` with `status`, `node_count`, `relationship_count`.

**SC-008**: Neo4j appears in topology with health coloring and node/relationship count badges.

### FR-005: pgvector Health Check

The dashboard probes pgvector via PostgreSQL connection and reports:
- Connection status (up/down)
- Vector extension version (`SELECT extversion FROM pg_extension WHERE extname = 'vector'`)
- Table count with vector columns
- Total vector count across tables
- Displayed in topology and service cards

**SC-009**: Dashboard `/api/status` includes `services.pgvector` with `status`, `extension_version`, `vector_tables`, `total_vectors`.

**SC-010**: pgvector appears in topology with health coloring and vector count badge.

### FR-006: Langfuse Error Rate & Model Breakdown

Enhance existing Langfuse polling (30s) to include:
- Error rate: `GET /api/public/observations?type=GENERATION&statusCode=5xx` vs total
- Per-model breakdown: group observations by model name, show token counts and avg latency per model
- Displayed in Operations tab by enhancing existing Langfuse panel

**SC-011**: Dashboard `/api/status` `mlops.langfuse` includes `error_rate`, `by_model` (array of `{model, requests, tokens, avg_latency_ms}`).

**SC-012**: Operations tab Langfuse panel shows error rate gauge and per-model breakdown table.

## Non-Functional Requirements

### NFR-001: No New Services
All data comes from existing service APIs. No new containers, no new dependencies.

### NFR-002: Graceful Degradation
If any data source is unavailable (Neo4j down, n8n API key missing), the dashboard continues showing available data. Missing data shows "unavailable" badge, not an error.

### NFR-003: Polling Budget
Total slow-poll cycle (30s) must complete within 10s. Each new data source gets a 3s timeout. Failures are non-blocking (fire-and-forget with fallback).

### NFR-004: API Backward Compatibility
New fields are additive to `/api/status`. Existing fields and structure unchanged.

## Out of Scope

- Airflow/OpenMetadata integration (deferred — requires dataops profile)
- GitLab CI/CD metrics (separate spec — requires GitLab API access)
- Alerting/notification system (separate spec)
- Historical trend storage (requires time-series DB — future spec)
- Custom dashboard layouts/user preferences

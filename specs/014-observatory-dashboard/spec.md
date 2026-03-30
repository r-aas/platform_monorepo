<!-- status: shipped -->
# Spec 014: Observatory Dashboard

## Problem

Monitoring the genai-mlops stack required checking 5+ separate tools: `task health` for service status, `task doctor` for environment, `langfuse-metrics.py` for trace data, `session-archive.py` for sessions, and manual `curl` calls for webhook probing. No single view showed the full operational state — infrastructure health, webhook availability, MCP server status, Langfuse metrics, MLflow experiments, and agent status together. Debugging required constant terminal switching and mental aggregation across disconnected data sources.

## Approach

PEP 723 standalone FastAPI script (`scripts/dashboard.py`) with SSE for live updates. Serves a tabbed web UI at port 4020. Two polling tiers: fast (5s) for infrastructure health, slow (30s) for MLOps metrics (heavier API calls). All config read from `config.yaml` — single source of truth (Spec 010).

## Requirements

### FR-001: Infrastructure Health Polling (5s)

The dashboard polls all services defined in `config.yaml` via their health endpoints. Each check records:
- HTTP status code and response time (ms)
- Classification: application, database, or host service
- Docker container stats (CPU%, memory usage/limit, state, uptime) via `docker stats --no-stream`

Services: n8n, MLflow, LiteLLM, Langfuse, MinIO, Airflow, OpenMetadata, streaming-proxy, pgvector, Ollama (host).

### FR-002: Webhook Endpoint Probing

The dashboard probes all 9 webhook endpoints and 4 GET endpoints on each infra poll cycle:

| Endpoint | Method | Probe Body |
|----------|--------|------------|
| `/webhook/chat` | POST | `{"action": "health"}` (avoids triggering LLM inference) |
| `/webhook/traces` | POST | `{"action": "summary"}` |
| `/webhook/prompts` | POST | `{"action": "list"}` |
| `/webhook/eval` | POST | `{"prompt_name": "assistant", "model": "test"}` |
| `/webhook/sessions` | POST | `{"action": "list"}` |
| `/webhook/datasets` | POST | `{"action": "list"}` |
| `/webhook/experiments` | POST | `{"action": "list"}` |
| `/webhook/v1/models` | GET | — |
| `/webhook/a2a/agent-card` | GET | — |

A webhook is "alive" if it returns any HTTP response (200, 400, 404, 500) — any workflow response means n8n is routing. Auth via `X-API-Key` header from `WEBHOOK_API_KEY`.

### FR-003: MCP Server Status

The dashboard detects running MCP server containers by querying Docker for containers matching `genai-mcp-*` naming pattern. Reports running/stopped status for each of the 6 active servers: n8n-knowledge, n8n-manager, mlflow, kubernetes, claude-code, fetch.

### FR-004: n8n Workflow Listing via REST API

Uses the n8n REST API (`/api/v1/workflows`) with API key from `secrets/n8n_api_key` to list all workflows with their active/inactive status. Falls back to known workflow file list if API unavailable (401/timeout).

### FR-005: Agent Definitions

The dashboard displays 7 logical agents as distinct cards:
- Chat Agent, Eval Agent, Trace Logger, Session Manager, Prompt Manager, OpenAI Compat, A2A Server
- Each linked to its primary webhook endpoint for status indication

### FR-006: Langfuse Metrics (30s poll)

Queries Langfuse public API with basic auth (`LANGFUSE_PUBLIC_KEY:LANGFUSE_SECRET_KEY`):
- `GET /api/public/traces` — trace count, latency p50/p95 (last 24h)
- `GET /api/public/scores` — average quality scores by name
- `GET /api/public/observations` — token usage (input/output/total), cost, model breakdown

### FR-007: MLflow Metrics (30s poll)

Queries MLflow REST API (no auth):
- `GET /api/2.0/mlflow/experiments/search` — experiment count, recent runs
- `GET /api/2.0/mlflow/registered-models/search` — prompt/model count, versions

### FR-008: Session & Drift Metrics (30s poll)

Queries via n8n webhooks:
- `POST /webhook/sessions {"action":"list"}` — active/closed counts, message totals
- `POST /webhook/traces {"action":"drift_check"}` — latency/error/token drift vs baseline

### FR-009: SSE Live Updates

The `/api/events` endpoint streams Server-Sent Events:
- `event: infra` every 5 seconds with full infrastructure state
- `event: mlops` every 30 seconds with Langfuse/MLflow/session/drift data
- Browser reconnects automatically on connection drop

### FR-010: Three-Tab UI Layout

The UI has three tabs:

1. **Topology** — ReactFlow interactive architecture diagram showing service groups (DataOps, MLOps, AgentOps, Infra, Databases, Host) with animated connection edges. Color-coded by health status.

2. **Services** — Ops groups summary bar, infrastructure service cards (CPU/memory/status), agent cards, workflow list with active status, webhook status grid, MCP server status.

3. **Operations** — Langfuse trace stats (count, p50/p95 latency, error rate), quality scores, token usage, session counts, experiment counts, drift status, recent traces table.

### FR-011: JSON Snapshot API

`GET /api/status` returns the full merged state as JSON for programmatic consumption:
```json
{
  "infra": {"services": [...], "containers": [...], "webhooks": [...], "mcp": [...]},
  "mlops": {"traces": {...}, "scores": {...}, "experiments": {...}, "sessions": {...}},
  "timestamp": "..."
}
```

### FR-012: Ops Groups Summary

The Services tab header shows operational group status:
- DataOps (Airflow + OpenMetadata): healthy/degraded/down
- MLOps (MLflow + Langfuse + LiteLLM): healthy/degraded/down
- AgentOps (n8n + MCP Gateway + Streaming Proxy): healthy/degraded/down

## Acceptance Scenarios

### SC-001: Dashboard Starts
Given a running stack, `task dashboard` starts the dashboard at `http://localhost:4020` within 2 seconds. All three tabs render.

### SC-002: Service Down Detection
Given all services running, stopping one service (e.g., `docker stop genai-mlflow`) causes its card to turn red within 5 seconds on the Services tab and its topology node to change color.

### SC-003: Service Recovery Detection
Given a stopped service, restarting it causes the card to turn green within 5 seconds.

### SC-004: Webhook Status Accuracy
Given 9 active workflows, all 9 webhook endpoints show green (alive) status on the Services tab.

### SC-005: Langfuse Metrics Display
Given Langfuse with trace data, the Operations tab shows non-zero trace count, latency percentiles, and quality scores.

### SC-006: JSON API
`curl http://localhost:4020/api/status | jq .` returns valid JSON with both `infra` and `mlops` keys.

### SC-007: Graceful Degradation
If Langfuse is down, the Operations tab shows "unavailable" for trace metrics but the rest of the dashboard renders normally. Infrastructure and webhook sections are unaffected.

## Non-Functional Requirements

### NFR-001: Polling Overhead
Infrastructure polling (5s) MUST complete within 3 seconds. MLOps polling (30s) MUST complete within 10 seconds. Timeouts per-request: 3s for health checks, 5s for webhook probes, 10s for Langfuse/MLflow APIs.

### NFR-002: Zero External Dependencies
Dashboard runs as a standalone PEP 723 script. Dependencies: `fastapi`, `uvicorn`, `httpx`, `pyyaml`. No database, no Redis, no build step.

### NFR-003: Config-Driven
All service ports, health endpoints, and connection details come from `config.yaml` (Spec 010). No hardcoded service URLs.

### NFR-004: Dark Theme
Monospace font, dark background, color-coded status indicators. CSS grid layout, responsive.

## Architecture

```
Browser ──► FastAPI (port 4020)
              │
              ├─ GET /                        (HTML shell)
              ├─ GET /static/{file}           (JS/CSS assets)
              ├─ GET /api/events              (SSE stream)
              └─ GET /api/status              (JSON snapshot)

Background pollers:
  ├─ InfraPoller (5s)   → health endpoints, docker stats, webhooks, MCP, n8n API
  └─ MLOpsPoller (30s)  → Langfuse traces/scores, MLflow experiments, sessions, drift
```

## Files

| File | Status |
|------|--------|
| `scripts/dashboard.py` | Shipped (2023 lines) |
| `scripts/dashboard-static/app.js` | Shipped (main UI controller + SSE) |
| `scripts/dashboard-static/topology.js` | Shipped (ReactFlow topology tab) |
| `scripts/dashboard-static/panels.js` | Shipped (Services + Operations tab panels) |
| `scripts/dashboard-static/styles.css` | Shipped (dark theme, grid layout) |
| `Taskfile.yml` | Updated (added `dashboard` task) |

## Dependencies

```python
# /// script
# requires-python = ">=3.12"
# dependencies = ["fastapi>=0.115", "uvicorn>=0.34", "httpx>=0.27", "pyyaml>=6.0"]
# ///
```

## Taskfile Entry

```yaml
dashboard:
  desc: Platform observatory dashboard (http://localhost:4020)
  cmds:
    - uv run scripts/dashboard.py
```

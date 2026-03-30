<!-- status: deferred -->
<!-- parent: 009 -->
<!-- depends: 008, 009a, 009b -->
<!-- note: streaming proxy (spec 008) covers /v1/*. Full /api/* gateway deferred until k8s ingress (specs 012-013). -->
# Spec 009c: API Gateway

## Problem

Consumers must know individual service ports to interact with the stack: n8n on :5678, MLflow on :5050, LiteLLM on :4000, MCP Gateway on :8811. There is no single entry point, no aggregate health check, and no service catalog. The streaming proxy (Spec 008) already runs on :4010 handling `/v1/*` routes — it's the natural place to consolidate all external access.

## Parent Spec

[Spec 009: AgenticOps Registries](../009-agentic-registries/spec.md) — this spec implements FR-008.

## Dependencies

- **009a** (Structured Agent Tags) — agent config used by health checks
- **009b** (Registry APIs) — `/api/agents`, `/api/skills`, `/api/mcp` routes proxy to registry endpoints

## Requirements

### FR-001: `/api/*` Proxy Routes

The gateway proxies clean `/api/*` routes to n8n webhook endpoints:

```
POST :4010/api/prompts   → POST http://n8n:5678/webhook/prompts
POST :4010/api/agents    → POST http://n8n:5678/webhook/agents
POST :4010/api/skills    → POST http://n8n:5678/webhook/skills
POST :4010/api/mcp       → POST http://n8n:5678/webhook/mcp
POST :4010/api/chat      → POST http://n8n:5678/webhook/chat
POST :4010/api/eval      → POST http://n8n:5678/webhook/eval
POST :4010/api/traces    → POST http://n8n:5678/webhook/traces
POST :4010/api/sessions  → POST http://n8n:5678/webhook/sessions
POST :4010/api/datasets  → POST http://n8n:5678/webhook/datasets
```

Auth header (`X-API-Key`) forwarded to backend.

### FR-002: Aggregate Health Check

```
GET :4010/health
```

Queries all backend health endpoints in parallel, returns per-service status with overall pass/fail.

Services:
| Service | Internal URL | Health Endpoint |
|---------|-------------|-----------------|
| n8n | `http://n8n:5678` | `/healthz` |
| MLflow | `http://mlflow:5050` | `/health` |
| LiteLLM | `http://litellm:4000` | `/health/liveliness` |
| MCP Gateway | `http://mcp-gateway:8811` | `/health` |
| Langfuse | `http://langfuse:3000` | `/api/public/health` |
| MinIO | `http://minio:9000` | `/minio/health/live` |

### FR-003: Service Catalog

```
GET :4010/services
```

Returns service catalog — name, internal URL, health endpoint, current status, and routes handled. Acts as a live API directory.

### FR-004: Auth Enforcement on All Routes

`X-API-Key` enforcement applies to all `/api/*` routes. Existing `/v1/*` auth behavior unchanged.

### FR-005: Existing `/v1/*` Routes Unchanged

Streaming SSE logic from Spec 008 stays as-is. No behavioral changes to existing routes.

### FR-006: n8n Port Internalization

Remove n8n external port binding from docker-compose. n8n becomes internal-only on `mlops-net`. External consumers access everything through :4010.

**Exception**: n8n UI stays accessible on its own port for browser-based workflow editing.

### NFR-001: Gateway Latency

Proxy overhead must be < 10ms per request (negligible compared to backend processing).

### NFR-002: Graceful Degradation

If a backend service is down, the gateway returns 502 for that service's routes but continues serving other routes normally. Health endpoint reflects the degraded state.

## Files Changed

| File | Action |
|------|--------|
| `src/streaming_proxy.py` | EDIT — add `/api/*` proxy, `/health`, `/services` routes |
| `docker-compose.yml` | EDIT — remove n8n external port (keep internal), add n8n UI port if separate |
| `tests/test_gateway.py` | NEW — gateway routing, health check, auth tests |
| `scripts/smoke-test.sh` | EDIT — switch smoke tests to use :4010/api/* routes |

## Verification

| Check | FR | Expected |
|-------|-----|----------|
| `POST :4010/api/agents {"action":"list"}` | FR-001 | Same response as `POST :5678/webhook/agents {"action":"list"}` |
| `POST :4010/api/chat {"message":"hello","agent_name":"coder"}` | FR-001 | Chat response via gateway |
| `GET :4010/health` | FR-002 | Per-service status, overall pass/fail |
| `GET :4010/health` with n8n down | NFR-002 | n8n shows unhealthy, others healthy, overall fail |
| `GET :4010/services` | FR-003 | Service catalog with names, routes, status |
| `POST :4010/api/agents` without API key (auth enabled) | FR-004 | 403 |
| `POST :4010/v1/chat/completions` with stream=true | FR-005 | SSE streaming works as before |
| `curl http://localhost:5678/webhook/agents` from outside Docker | FR-006 | Connection refused (port not exposed) |
| Gateway proxy latency measurement | NFR-001 | < 10ms overhead |
| `bash scripts/smoke-test.sh` | All | All pass via gateway routes |
| `docker compose config --quiet` | FR-006 | Valid compose, n8n ports internal only |

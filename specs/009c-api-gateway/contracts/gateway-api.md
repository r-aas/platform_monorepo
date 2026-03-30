# API Contract: Gateway (Unified Entry Point)

## Base URL

```
http://localhost:4010
```

All external consumers use this single endpoint. Auth via `X-API-Key` header when `WEBHOOK_API_KEY` is set.

---

## Routes

### `/v1/*` — OpenAI-Compatible (existing, unchanged)

```
POST /v1/chat/completions    → streaming proxy logic (Spec 008)
GET  /v1/models              → pass-through to n8n
POST /v1/embeddings          → pass-through to n8n
```

### `/api/*` — n8n Webhook Proxy

All `/api/{endpoint}` routes proxy to `http://n8n:5678/webhook/{endpoint}` with:
- Method preserved (POST)
- Body forwarded as-is
- `X-API-Key` header forwarded
- Response returned as-is (no transformation)

| Gateway Route | Proxied To | Workflow |
|--------------|-----------|----------|
| `POST /api/prompts` | `POST /webhook/prompts` | prompt-crud |
| `POST /api/agents` | `POST /webhook/agents` | agent-registry |
| `POST /api/skills` | `POST /webhook/skills` | prompt-crud (skills actions) |
| `POST /api/mcp` | `POST /webhook/mcp` | mcp-registry |
| `POST /api/chat` | `POST /webhook/chat` | chat |
| `POST /api/eval` | `POST /webhook/eval` | prompt-eval |
| `POST /api/traces` | `POST /webhook/traces` | trace |
| `POST /api/sessions` | `POST /webhook/sessions` | sessions |

---

## Health & Discovery

### `GET /health` — Aggregate Health Check

Queries all backend service health endpoints in parallel. Returns per-service status.

**Response (all healthy):**
```json
{
  "status": "healthy",
  "services": {
    "n8n": { "status": "healthy", "latency_ms": 12 },
    "mlflow": { "status": "healthy", "latency_ms": 8 },
    "litellm": { "status": "healthy", "latency_ms": 5 },
    "mcp-gateway": { "status": "healthy", "latency_ms": 3 },
    "langfuse": { "status": "healthy", "latency_ms": 15 },
    "minio": { "status": "healthy", "latency_ms": 4 }
  },
  "healthy_count": 6,
  "total_count": 6
}
```

**Response (partial failure):**
```json
{
  "status": "degraded",
  "services": {
    "n8n": { "status": "healthy", "latency_ms": 12 },
    "mlflow": { "status": "unhealthy", "error": "Connection refused", "latency_ms": null },
    "litellm": { "status": "healthy", "latency_ms": 5 },
    "mcp-gateway": { "status": "healthy", "latency_ms": 3 },
    "langfuse": { "status": "unhealthy", "error": "Timeout after 5000ms", "latency_ms": null },
    "minio": { "status": "healthy", "latency_ms": 4 }
  },
  "healthy_count": 4,
  "total_count": 6
}
```

**Status values:**
- `healthy` — all services responding
- `degraded` — some services down
- `unhealthy` — critical services down (n8n or litellm)

**HTTP status codes:**
- `200` — healthy or degraded
- `503` — unhealthy (critical services down)

**Health check timeout:** 5 seconds per service. Non-responding services marked unhealthy.

### `GET /services` — Service Catalog

Returns the registered service catalog with current health status and the routes each service handles.

**Response:**
```json
{
  "services": [
    {
      "name": "n8n",
      "description": "Workflow automation — webhook endpoints for all APIs",
      "internal_url": "http://n8n:5678",
      "health_endpoint": "/healthz",
      "status": "healthy",
      "routes": [
        "POST /api/prompts",
        "POST /api/agents",
        "POST /api/skills",
        "POST /api/mcp",
        "POST /api/chat",
        "POST /api/eval",
        "POST /api/traces",
        "POST /api/sessions"
      ]
    },
    {
      "name": "mlflow",
      "description": "Experiment tracking, prompt registry, model registry",
      "internal_url": "http://mlflow:5050",
      "health_endpoint": "/health",
      "status": "healthy",
      "routes": []
    },
    {
      "name": "litellm",
      "description": "LLM proxy — OpenAI-compatible inference with logging",
      "internal_url": "http://litellm:4000",
      "health_endpoint": "/health/liveliness",
      "status": "healthy",
      "routes": [
        "POST /v1/chat/completions (stream=true)",
        "POST /v1/embeddings"
      ]
    },
    {
      "name": "mcp-gateway",
      "description": "On-demand MCP server management",
      "internal_url": "http://mcp-gateway:8811",
      "health_endpoint": "/health",
      "status": "healthy",
      "routes": []
    },
    {
      "name": "langfuse",
      "description": "LLM observability and trace ingestion",
      "internal_url": "http://langfuse:3000",
      "health_endpoint": "/api/public/health",
      "status": "healthy",
      "routes": []
    },
    {
      "name": "minio",
      "description": "S3-compatible artifact storage",
      "internal_url": "http://minio:9000",
      "health_endpoint": "/minio/health/live",
      "status": "healthy",
      "routes": []
    }
  ],
  "gateway_version": "0.2.0",
  "total_services": 6
}
```

---

## Error Responses

### Auth Failure (all routes)
```json
HTTP 403
{ "error": "Invalid or missing API key" }
```

### Upstream Timeout (`/api/*` proxy)
```json
HTTP 504
{ "error": "Upstream timeout", "service": "n8n", "timeout_ms": 30000 }
```

### Service Unavailable (`/api/*` proxy)
```json
HTTP 502
{ "error": "Service unavailable", "service": "n8n", "detail": "Connection refused" }
```

---

## Configuration

| Env Var | Default | Purpose |
|---------|---------|---------|
| `N8N_BASE_URL` | `http://n8n:5678` | n8n service URL |
| `LITELLM_BASE_URL` | `http://litellm:4000` | LiteLLM service URL |
| `MLFLOW_TRACKING_URI` | `http://mlflow:5050` | MLflow service URL |
| `MCP_GATEWAY_URL` | `http://mcp-gateway:8811` | MCP gateway URL |
| `LANGFUSE_URL` | `http://langfuse:3000` | Langfuse service URL |
| `MINIO_URL` | `http://minio:9000` | MinIO service URL |
| `WEBHOOK_API_KEY` | _(empty)_ | API key for auth enforcement |
| `HEALTH_CHECK_TIMEOUT_MS` | `5000` | Per-service health check timeout |
| `PORT` | `4010` | Gateway listen port |

---

## Implementation Notes

- **Evolves `src/streaming_proxy.py`** — not a new service. The streaming proxy becomes the API gateway.
- **Service registry is static** — defined in code as a list of `ServiceConfig` dataclasses. No dynamic registration.
- **Health checks are async** — all services queried concurrently via `asyncio.gather`. Total health check time = slowest service (max 5s).
- **`/api/*` proxy is trivial** — `httpx` pass-through, no body parsing, no transformation. ~10 lines per route, or a generic catch-all.
- **Docker Compose change** — n8n port binding removed from `ports:` (stays on `mlops-net` internally). Gateway is the only externally exposed HTTP port (4010).
- **UI ports unchanged** — n8n UI (5678), MLflow UI (5050), Langfuse UI (3100), MinIO Console (9001) stay exposed for browser access. Only webhook/API traffic goes through the gateway.

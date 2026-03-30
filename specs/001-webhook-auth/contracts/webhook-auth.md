# Contract: Webhook Authentication

**Feature**: 001-webhook-auth | **Date**: 2026-03-11

## Authentication Method

All `/webhook/*` endpoints accept authentication via the `X-API-Key` request header.

## Request

### Authenticated Request

```
POST /webhook/{path} HTTP/1.1
Host: localhost:5678
Content-Type: application/json
X-API-Key: <api-key-value>

{"action": "list"}
```

### Header

| Header | Required | Format | Example |
|--------|----------|--------|---------|
| `X-API-Key` | Yes (when auth enabled) | Plain string | `X-API-Key: dev-webhook-key-genai-mlops` |

## Responses

### 200 OK — Authenticated (or open mode)

Normal workflow response. Body varies by endpoint.

### 401 Unauthorized — Missing or invalid key

Returned when:
- `WEBHOOK_API_KEY` is configured (non-empty) AND
- Request has no `X-API-Key` header, OR
- Request has `X-API-Key` header with wrong value

```
HTTP/1.1 401 Unauthorized
```

**Note**: Response body format is determined by n8n's native auth handler. May be JSON, plain text, or empty. The 401 status code is the reliable indicator.

## Modes

| `WEBHOOK_API_KEY` value | Behavior |
|-------------------------|----------|
| Unset or empty string | **Open mode** — all requests accepted without auth |
| Whitespace-only | **Open mode** — treated as empty |
| Non-empty string | **Auth mode** — `X-API-Key` header required on all webhook requests |

## Scope

Auth applies uniformly to:
- All 9 webhook workflows (12 trigger nodes)
- All HTTP methods (GET, POST, PUT, DELETE)
- All webhook paths under `/webhook/*`

Auth does NOT apply to:
- n8n UI (`localhost:5678`)
- n8n REST API (`/api/v1/*`) — protected by `N8N_KEY`
- n8n webhook test path (`/webhook-test/*`) — n8n UI internal, requires n8n login
- MLflow API (`localhost:5050`)
- LiteLLM API (`localhost:4000`)
- Langfuse API (`localhost:3100`)

## Client Examples

### curl
```bash
curl -X POST http://localhost:5678/webhook/prompts \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-webhook-key-genai-mlops' \
  -d '{"action":"list"}'
```

### Python (requests)
```python
import requests
headers = {
    "Content-Type": "application/json",
    "X-API-Key": os.getenv("WEBHOOK_API_KEY", ""),
}
resp = requests.post(f"{BASE}/prompts", json={"action": "list"}, headers=headers)
```

### n8n Code node (internal)
```javascript
var WEBHOOK_KEY = process.env.WEBHOOK_API_KEY || 'dev-webhook-key-genai-mlops';
axios.post(N8N + '/traces', body, {
  headers: { 'X-API-Key': WEBHOOK_KEY }
});
```

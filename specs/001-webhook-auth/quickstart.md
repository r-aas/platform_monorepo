# Quickstart: Webhook Authentication

**Feature**: 001-webhook-auth | **Date**: 2026-03-11

## Enable Auth (default for local dev)

Auth is enabled automatically when `WEBHOOK_API_KEY` has a value in `.env`:

```bash
# .env (created by task setup from .env.example)
WEBHOOK_API_KEY=dev-webhook-key-genai-mlops
```

After `task n8n:import` (or `bash scripts/n8n-import-all.sh`), the import script:
1. Creates an `httpHeaderAuth` credential in n8n
2. Patches all 12 webhook nodes to require the `X-API-Key` header

## Disable Auth (open mode)

Set the key to empty:

```bash
# .env
WEBHOOK_API_KEY=
```

Re-run the import: `task n8n:import`. Webhook nodes remain as `auth=none`.

## Test Auth

### Verify rejection (auth enabled)

```bash
# No key — should get 401
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:5678/webhook/prompts \
  -H 'Content-Type: application/json' \
  -d '{"action":"list"}'
# Expected: 401
```

### Verify success (auth enabled)

```bash
# With key — should get 200
curl -sf -X POST http://localhost:5678/webhook/prompts \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: ${WEBHOOK_API_KEY}" \
  -d '{"action":"list"}' | jq .
# Expected: prompt list
```

### Run full test suite

```bash
# Smoke tests (include auth automatically)
task qa:smoke

# Agent benchmark (includes auth automatically)
uv run python scripts/agent-benchmark.py
```

## For Script Authors

All scripts that call webhook endpoints need the `X-API-Key` header:

```bash
# Bash
API_KEY="${WEBHOOK_API_KEY:-}"
curl -H "X-API-Key: $API_KEY" ...
```

```python
# Python
import os
headers = {"X-API-Key": os.getenv("WEBHOOK_API_KEY", "")}
requests.post(url, headers=headers, ...)
```

## Changing the Key

1. Update `WEBHOOK_API_KEY` in `.env`
2. Re-run `task n8n:import` (recreates credential with new value)
3. All clients pick up the new key from the env var automatically

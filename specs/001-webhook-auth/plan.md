# Implementation Plan: Webhook Authentication Middleware

**Branch**: `001-webhook-auth` | **Date**: 2026-03-11 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-webhook-auth/spec.md`

## Summary

Add API key authentication to all 12 webhook trigger nodes across 9 n8n workflows using n8n's native Header Auth credential mechanism. When `WEBHOOK_API_KEY` is configured, the import script creates an `httpHeaderAuth` credential and patches all webhook nodes to require the `X-API-Key` header. Internal service-to-service calls, smoke tests, and the agent benchmark are updated to include the key. When the key is unset/empty, the system operates in open mode (no auth enforcement).

## Technical Context

**Language/Version**: Bash (import script), JavaScript (n8n Code nodes), Python 3.12 (benchmark), Shell (smoke tests)
**Primary Dependencies**: n8n v1.123+ (native webhook headerAuth), axios (Code node HTTP), curl (smoke tests), urllib.request (import script)
**Storage**: n8n PostgreSQL (credentials table — managed by n8n API)
**Testing**: `scripts/smoke-test.sh` (83+ cases), `scripts/agent-benchmark.py` (11 cases)
**Target Platform**: Docker Compose (Colima, macOS)
**Project Type**: Infrastructure configuration change (no new services)
**Performance Goals**: <5ms auth overhead per request (SC-004) — n8n native auth is in-process header check
**Constraints**: n8n VM2 sandbox blocks `process.env` — Code nodes use hardcoded fallback for API key value
**Scale/Scope**: 12 webhook nodes across 9 workflows, 6 internal Code node call sites, ~34 curl calls in smoke tests, ~10 request calls in benchmark

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Workflow-First Architecture | ✅ PASS | Auth is native n8n webhook feature (`authentication: "headerAuth"`), not an external proxy or custom service. No new services added. |
| II. Test-First (NON-NEGOTIABLE) | ✅ PASS | Smoke tests updated with auth headers. Benchmark updated. Dedicated auth test cases added (401 without key, 200 with key). |
| III. Integration-First, No Mocking | ✅ PASS | All testing against live stack with real credentials on running compose stack. |
| IV. Observability by Default | ✅ PASS | No impact on trace pipeline — Trace Logger gets X-API-Key header for internal calls to `/traces` and `/sessions`. |
| V. Prompts Are Versioned Artifacts | ✅ N/A | No prompt changes required. |
| VI. Infrastructure as Configuration | ✅ PASS | Single env var (`WEBHOOK_API_KEY`) in `.env.example`. Import script manages credential lifecycle. No manual n8n UI configuration. |
| VII. Local-First | ✅ PASS | No cloud dependencies. Empty key = open mode for frictionless local dev. |

**Pre-design gate**: PASS — no violations. Proceed to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/001-webhook-auth/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: research findings
├── data-model.md        # Phase 1: entity model
├── quickstart.md        # Phase 1: setup guide
├── contracts/           # Phase 1: API contracts
│   └── webhook-auth.md  # Auth header contract
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
scripts/
├── n8n-import-all.sh    # EDIT: Add Step 6 — webhook auth credential + node patching
├── smoke-test.sh        # EDIT: Add X-API-Key header to all curl calls + auth test cases
└── agent-benchmark.py   # EDIT: Add X-API-Key header to all requests

n8n-data/workflows/
├── a2a-server.json      # EDIT: Code nodes add X-API-Key to internal axios calls
└── chat.json            # EDIT: Trace Logger + Prompt Resolver add X-API-Key to internal axios calls

.env.example             # EDIT: Set default value for WEBHOOK_API_KEY
```

**Structure Decision**: No new files or directories in the source tree. All changes are edits to existing files. The auth mechanism uses n8n's native credential system — no custom middleware, proxies, or services.

## Implementation Approach

### Mechanism: n8n Native Header Auth

n8n webhook nodes support `authentication: "headerAuth"` which references an `httpHeaderAuth` credential. The credential stores a header name (`X-API-Key`) and expected value. n8n validates incoming requests automatically before workflow execution — no custom code needed for the auth check itself.

**Credential creation** (via n8n REST API in import script):
```
POST /api/v1/credentials
{
  "name": "Webhook API Key",
  "type": "httpHeaderAuth",
  "data": {
    "name": "X-API-Key",
    "value": "<WEBHOOK_API_KEY value>"
  }
}
```

**Webhook node patching** (applied to all 12 trigger nodes):
```
Node parameters: { "authentication": "headerAuth", ...existing params... }
Node credentials: { "httpHeaderAuth": {"id": "<credential-id>"} }
```

### Changes by File

#### 1. `.env.example` — Default key value

```
WEBHOOK_API_KEY=dev-webhook-key-genai-mlops
```

Provides a known default for local development. Code nodes use this as their hardcoded fallback (same pattern as `LITELLM_API_KEY`).

#### 2. `scripts/n8n-import-all.sh` — Add Step 6

New inline Python block after existing Step 5 (Ollama credential). Follows identical pattern:

1. Read `WEBHOOK_API_KEY` from env, strip whitespace
2. If empty → skip (open mode), print message
3. If set → create `httpHeaderAuth` credential via `api_post`
4. Handle 409 Conflict (credential already exists) by finding existing credential ID
5. Fetch all workflows via `api_get("/workflows")`
6. For each workflow, find nodes with `type == "n8n-nodes-base.webhook"`
7. Set `node.parameters.authentication = "headerAuth"` and add credential reference
8. PUT updated workflow back via `api_put`

#### 3. `n8n-data/workflows/chat.json` — Internal calls

**Trace Logger** (node `n8`): Calls `/traces` and `/sessions` internally. Add `X-API-Key` header:
```javascript
var WEBHOOK_KEY = process.env.WEBHOOK_API_KEY || 'dev-webhook-key-genai-mlops';
// Add to axios calls:
axios.post(N8N + '/traces', body, { headers: { 'X-API-Key': WEBHOOK_KEY } })
axios.post(N8N + '/sessions', body, { headers: { 'X-API-Key': WEBHOOK_KEY } })
```

**Prompt Resolver** (node `n2`): Calls `/sessions` internally. Same pattern.

#### 4. `n8n-data/workflows/a2a-server.json` — Internal calls

**Build Agent Card** (node `a2`): Calls `/prompts`. Add `X-API-Key` header.

**A2A Handler** (node `a5`): Calls `/chat`, `/traces`, `/prompts`. Add `X-API-Key` header to all three.

#### 5. `scripts/smoke-test.sh` — Auth header

Add auth to helper functions and all curl calls:
```bash
API_KEY="${WEBHOOK_API_KEY:-}"
CURL_AUTH=()
if [ -n "$API_KEY" ]; then
  CURL_AUTH=(-H "X-API-Key: $API_KEY")
fi
```

Update `check_status()` and `check_json()` to include `"${CURL_AUTH[@]}"` in curl args.

Add dedicated auth test cases:
- Request without key when auth enabled → expect 401
- Request with valid key → expect 200

#### 6. `scripts/agent-benchmark.py` — Auth header

```python
API_KEY = os.getenv("WEBHOOK_API_KEY", "")
HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY
```

Apply `HEADERS` to all `requests.post()` calls.

### Internal Webhook Call Inventory

These Code node → webhook calls need the `X-API-Key` header:

| Workflow | Node | Calls | Endpoints |
|----------|------|-------|-----------|
| chat.json | Trace Logger (`n8`) | 2 | `/traces`, `/sessions` |
| chat.json | Prompt Resolver (`n2`) | 1 | `/sessions` |
| a2a-server.json | Build Agent Card (`a2`) | 1 | `/prompts` |
| a2a-server.json | A2A Handler (`a5`) | 3 | `/chat`, `/traces`, `/prompts` |

**NOT affected** (external service calls, not n8n webhooks):
- MLflow API calls (`http://mlflow:5050/...`) — 7 workflows
- LiteLLM calls (`http://litellm:4000/v1/...`) — 3 workflows
- Langfuse API calls (`http://langfuse:3000/...`) — 1 workflow

### Open Mode Behavior

When `WEBHOOK_API_KEY` is empty or unset:

1. Import script skips credential creation and webhook node patching
2. All webhook nodes remain `authentication: "none"` (workflow JSONs in git are always `auth=none`)
3. Smoke tests detect empty key, skip auth header (curl calls work as-is)
4. Internal Code node calls: fallback value `'dev-webhook-key-genai-mlops'` is sent but ignored by n8n (auth=none accepts all requests)
5. No code changes needed to toggle — purely env var driven

### FR-003 Deviation

The spec requires `Authorization: Bearer <key>` support (FR-003). This is **DROPPED** because:

- n8n's native `headerAuth` validates exactly one header name per credential
- Supporting both `X-API-Key` and `Authorization: Bearer` would require either a reverse proxy (new service) or custom auth-check Code nodes in every workflow
- Both alternatives violate Constitution Principle I (Workflow-First) and add complexity
- `X-API-Key` is the simpler, more explicit pattern for machine-to-machine auth

The spec will be updated to remove FR-003 after implementation.

### Spec Requirement Mapping

| Requirement | Implementation | Notes |
|-------------|---------------|-------|
| FR-001: Reject unauth with 401 | n8n native headerAuth | n8n returns 401 automatically |
| FR-002: X-API-Key header | httpHeaderAuth credential `name: "X-API-Key"` | |
| FR-003: Authorization: Bearer | **DROPPED** | See deviation above |
| FR-004: Constant-time comparison | n8n native | Internal credential comparison |
| FR-005: Open mode when key unset | Import script conditional — skip patching | |
| FR-006: Whitespace-only = open mode | `webhook_key.strip()` in import script | |
| FR-007: Internal service-to-service auth | Code nodes add X-API-Key to axios calls | |
| FR-008: Don't log/expose key | n8n native | Credentials encrypted in DB |
| FR-009: All HTTP methods | n8n native | headerAuth applies to all methods on node |
| FR-010: Fail fast before workflow | n8n native | Auth check before workflow execution |

### Webhook Nodes (12 total, 9 workflows)

| Workflow | Node Name | Path | Method |
|----------|-----------|------|--------|
| a2a-server.json | Agent Card Webhook | /a2a/agent-card | GET |
| a2a-server.json | A2A Endpoint | /a2a | POST |
| chat.json | Chat Webhook | /chat | POST |
| mlflow-data.json | Webhook | /datasets | POST |
| mlflow-experiments.json | Webhook | /experiments | POST |
| openai-compat.json | GET /v1/models | /v1/models | GET |
| openai-compat.json | POST /v1/chat/completions | /v1/chat/completions | POST |
| openai-compat.json | POST /v1/embeddings | /v1/embeddings | POST |
| prompt-crud.json | Webhook | /prompts | POST |
| prompt-eval.json | Webhook | /eval | POST |
| sessions.json | Webhook | /sessions | POST |
| trace.json | Webhook | /traces | POST |

## Complexity Tracking

> No constitution violations. No complexity justifications needed.

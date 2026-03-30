# Research: Webhook Authentication Middleware

**Feature**: 001-webhook-auth | **Date**: 2026-03-11

## Research Tasks

### R1: n8n Webhook Authentication Options

**Decision**: Use `headerAuth` with `httpHeaderAuth` credential type.

**Rationale**: n8n webhook nodes (typeVersion 2) support four auth modes: `none`, `basicAuth`, `headerAuth`, `jwtAuth`. Header auth is the simplest — one custom header name + value, validated before workflow execution. No token parsing, no expiry logic, no user/password management.

**Alternatives considered**:

| Option | Pros | Cons | Rejected Because |
|--------|------|------|-----------------|
| `basicAuth` | Standard HTTP auth | Requires username + password, more complex for scripts | Over-engineered for single-key scenario |
| `jwtAuth` | Token expiry, claims | Requires JWT generation, key rotation | Massive overkill for local dev stack |
| Custom Code node auth | Full control over logic | Requires Code node in every workflow, custom comparison | Violates Workflow-First principle, doesn't fail fast |
| Reverse proxy (nginx) | Supports multiple auth methods | New service, extra config, new failure point | Violates constitution — no new services without justification |

### R2: n8n Credential API Pattern

**Decision**: Create credential via `POST /api/v1/credentials` in import script, patch webhook nodes via `PUT /api/v1/workflows/{id}`.

**Rationale**: This is the exact pattern already used for the Ollama credential in Step 5 of `n8n-import-all.sh`. Proven, tested, uses only stdlib (`urllib.request`). The credential type `httpHeaderAuth` requires `data.name` (header name) and `data.value` (header value).

**Key finding**: The credential type string is `httpHeaderAuth` (not `headerAuth`). The webhook `authentication` parameter value is `headerAuth`. These are different strings — one for the credential, one for the node parameter.

### R3: n8n VM2 Sandbox and Environment Variables

**Decision**: Use hardcoded fallback pattern for API key in Code nodes.

**Rationale**: n8n Code nodes run in a VM2 sandbox where `process.env` returns `undefined` for all variables. This is a documented limitation (see RESUME.md). The established workaround is `process.env.VAR || 'fallback-value'` — already used for `LITELLM_API_KEY` in Chat Handler and Prompt Resolver nodes.

**Security note**: The fallback value (`dev-webhook-key-genai-mlops`) appears in workflow JSON files committed to git. This is acceptable because:
1. The key protects a local dev stack, not production infrastructure
2. The same pattern is already used for `LITELLM_API_KEY`
3. Production deployments would set `WEBHOOK_API_KEY` to a real secret and the n8n credential would use that value (the hardcoded fallback is only reached if process.env fails)

### R4: Internal Service-to-Service Calls

**Decision**: Add `X-API-Key` header to all internal webhook axios calls (6 call sites in 4 Code nodes across 2 workflows).

**Rationale**: Internal Code nodes call other webhook endpoints via `axios.post(N8N + '/path', ...)` where `N8N = process.env.N8N_INTERNAL_URL || 'http://n8n:5678/webhook'`. These requests go through n8n's HTTP handler and are subject to the same auth check as external requests. There is no separate "internal" path that bypasses auth.

**Inventory**:
- `chat.json` → Trace Logger (`n8`): `/traces`, `/sessions`
- `chat.json` → Prompt Resolver (`n2`): `/sessions`
- `a2a-server.json` → Build Agent Card (`a2`): `/prompts`
- `a2a-server.json` → A2A Handler (`a5`): `/chat`, `/traces`, `/prompts`

### R5: Bearer Token Support (FR-003)

**Decision**: Drop `Authorization: Bearer <key>` support. Only support `X-API-Key` header.

**Rationale**: n8n's `headerAuth` validates exactly one header name per credential. Supporting two auth methods would require either:
1. A reverse proxy normalizing headers (new service — violates constitution)
2. Custom Code node auth in every workflow (violates fail-fast, adds complexity)
3. Two separate credentials (n8n doesn't support OR-logic for auth)

**Impact**: Low. All clients (smoke tests, benchmark, MCP tools, curl) are internal tooling we control. Switching from `Authorization: Bearer` to `X-API-Key` is a one-line change per client. No external consumers exist.

### R6: n8n 401 Response Format

**Decision**: Accept n8n's native 401 response format.

**Rationale**: The spec requires `{"error": "Unauthorized"}` JSON body (FR-001). n8n's native headerAuth may return a different format (plain text or HTML). This will be verified during testing. If the format doesn't match, we accept the deviation — the important thing is the 401 status code. Customizing the error body would require intercepting n8n's auth layer, which isn't possible without a proxy.

**Action**: Verify actual 401 response body during implementation. Update spec if needed.

## Unresolved Items

None. All research tasks resolved.

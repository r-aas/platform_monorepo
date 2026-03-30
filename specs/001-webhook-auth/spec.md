<!-- status: shipped -->
<!-- pr: #1 -->
# Feature Specification: Webhook Authentication Middleware

**Feature Branch**: `001-webhook-auth`
**Created**: 2026-03-11
**Status**: Shipped
**Input**: User description: "Webhook authentication middleware for the genai-mlops stack. All /webhook/* endpoints are currently open with no auth. Need an API key middleware that protects all webhook endpoints."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - External Client Authentication (Priority: P1)

An external client (curl, script, application) calls any webhook endpoint on the genai-mlops stack. The system verifies the request carries a valid API key before processing it. Unauthenticated requests are rejected immediately with a clear error.

**Why this priority**: This is the core security feature. Without it, all 9 workflows and 50+ webhook actions are publicly accessible to anyone who can reach the host.

**Independent Test**: Send a request without an API key and verify rejection. Send a request with a valid API key and verify it succeeds. Can be tested against any single webhook endpoint.

**Acceptance Scenarios**:

1. **Given** a running stack with auth enabled, **When** a client sends a POST to `/webhook/prompts` with `{"action":"list"}` and a valid API key in the `X-API-Key` header, **Then** the request succeeds and returns prompt data (HTTP 200).
2. **Given** a running stack with auth enabled, **When** a client sends the same request without any API key, **Then** the request is rejected with HTTP 403.
3. **Given** a running stack with auth enabled, **When** a client sends the same request with an invalid API key, **Then** the request is rejected with HTTP 403.

---

### User Story 2 - Smoke Test Compatibility (Priority: P1)

The existing smoke test suite (83 test cases) continues to pass after auth is enabled. Smoke tests are updated to include the API key in all requests. No test logic changes — only the addition of an auth header.

**Why this priority**: Equal to P1 because the smoke tests are the primary quality gate (constitution: Test-First, NON-NEGOTIABLE). If auth breaks the test suite, the feature cannot ship.

**Independent Test**: Run `task qa:smoke` after enabling auth and verify all 83 cases still pass.

**Acceptance Scenarios**:

1. **Given** auth is enabled and smoke tests are updated with the API key, **When** `task qa:smoke` is run, **Then** all previously passing tests still pass.
2. **Given** auth is enabled, **When** smoke tests run without the API key configured, **Then** tests fail with clear 401 errors (not silent failures or timeouts).

---

### User Story 3 - Internal Service-to-Service Calls (Priority: P1)

Workflows that call other webhook endpoints internally (e.g., the Chat workflow calling the Trace Logger, or the MCP agent calling `/webhook/prompts`) continue to work without manual auth configuration per-call.

**Why this priority**: Equal to P1 because internal workflow orchestration is the backbone of the stack. If inter-workflow calls break, the entire system stops functioning.

**Independent Test**: Send a chat message to an MCP agent that triggers internal tool calls (e.g., mlops agent listing prompts). Verify the full chain completes without auth errors.

**Acceptance Scenarios**:

1. **Given** auth is enabled, **When** the Chat workflow's Trace Logger fires a request to `/webhook/traces`, **Then** the trace is logged successfully (internal call is authenticated).
2. **Given** auth is enabled, **When** an MCP agent calls `/webhook/prompts` via MCP tool, **Then** the prompt data is returned (the MCP tool call includes proper auth).
3. **Given** auth is enabled, **When** the eval workflow calls another internal endpoint, **Then** the call succeeds without additional configuration.

---

### User Story 4 - Agent Benchmark Compatibility (Priority: P2)

The agent benchmark script (`scripts/agent-benchmark.py`) works with auth enabled. The mlops agent benchmark test — which currently fails because the MCP agent calls internal webhooks without auth — now passes because auth is properly propagated through the MCP tool chain.

**Why this priority**: Unblocks the one remaining benchmark failure. Lower than P1 because the benchmark is a development tool, not a production quality gate.

**Independent Test**: Run `uv run python scripts/agent-benchmark.py` and verify the mlops test case passes.

**Acceptance Scenarios**:

1. **Given** auth is enabled and the benchmark script includes the API key, **When** the benchmark runs the mlops/mlops-list test case, **Then** the MCP agent successfully calls `/webhook/prompts` and returns results.
2. **Given** auth is enabled, **When** the full benchmark suite runs, **Then** all 11 test cases pass (including the previously failing mlops case).

---

### User Story 5 - Graceful Degradation Without Key (Priority: P3)

When no `WEBHOOK_API_KEY` is configured (empty or unset), the system operates in open mode with no auth enforcement. This preserves backward compatibility for quick local development without requiring immediate auth setup.

**Why this priority**: Convenience feature for onboarding. New users running `task dev` for the first time should not be blocked by auth misconfiguration.

**Independent Test**: Start the stack with `WEBHOOK_API_KEY=` (empty). Verify all endpoints respond without auth headers.

**Acceptance Scenarios**:

1. **Given** the stack starts with `WEBHOOK_API_KEY` empty or unset, **When** a client sends a request without any auth header, **Then** the request succeeds (open mode).
2. **Given** the stack starts with `WEBHOOK_API_KEY` set to a non-empty value, **When** a client sends a request without auth, **Then** the request is rejected with HTTP 403.

---

### Edge Cases

- What happens when the API key contains special characters (e.g., `=`, `+`, `/`)?
- How does the system behave when `WEBHOOK_API_KEY` is set to whitespace-only?
- How does auth interact with n8n's built-in webhook test mode (the n8n UI "Test workflow" button)?
- What happens when the GET endpoints (e.g., `GET /webhook/v1/models`) receive auth via query parameter instead of header?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST reject unauthenticated requests to all `/webhook/*` endpoints with HTTP 403 when a `WEBHOOK_API_KEY` is configured. (n8n Header Auth returns 403, not 401. Response body format is controlled by n8n — status code is the reliable indicator.)
- **FR-002**: System MUST accept authentication via `X-API-Key: <key>` request header.
- ~~**FR-003**: DROPPED — Bearer token auth removed per research.md R5. n8n's native Header Auth only supports custom header names.~~
- **FR-005**: System MUST allow all requests through without auth when `WEBHOOK_API_KEY` is empty or unset (open mode).
- **FR-006**: System MUST treat whitespace-only `WEBHOOK_API_KEY` values as unset (open mode).
- **FR-007**: System MUST authenticate internal service-to-service webhook calls using the same API key mechanism.
- **FR-008**: System MUST NOT log or expose the API key value in error messages, traces, or response bodies.
- **FR-009**: System MUST apply auth to all HTTP methods (GET, POST, PUT, DELETE) on webhook endpoints.
- **FR-010**: System MUST return the 403 response before executing any workflow logic (fail fast).

### Key Entities

- **API Key**: A shared secret string configured via environment variable. Used for symmetric authentication of webhook requests. Single key per deployment (no per-user or per-endpoint keys).
- **Webhook Endpoint**: Any URL path matching `/webhook/*` served by n8n. Currently 9 workflows exposing 50+ actions.

### Assumptions

- Single API key is sufficient for this deployment (no multi-tenant or per-user key management needed).
- Auth is applied uniformly to all webhook endpoints — no per-endpoint exemptions.
- Query parameter authentication (`?api_key=...`) is intentionally NOT supported to avoid key leakage in server logs and browser history.
- n8n's built-in "Test workflow" button in the UI uses a separate internal path (`/webhook-test/*`) which is not covered by this auth (n8n UI already requires its own login).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of webhook endpoints reject unauthenticated requests when auth is enabled (verified by smoke tests sending requests without key and expecting 403).
- **SC-002**: All 83+ existing smoke tests pass with auth enabled (zero regressions).
- **SC-003**: Agent benchmark achieves 11/11 pass rate (mlops test case unblocked).
- **SC-004**: Auth check adds less than 5ms overhead per request (negligible compared to workflow execution time).
- **SC-005**: A new developer can enable auth by setting one environment variable — no other configuration required.
- **SC-006**: Disabling auth (unsetting the variable) restores full open access with no code changes.

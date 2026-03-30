# Tasks: Webhook Authentication Middleware

**Input**: Design documents from `/specs/001-webhook-auth/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths included in all descriptions

---

## Phase 1: Setup

**Purpose**: Environment configuration for auth support

- [ ] T001 Add `WEBHOOK_API_KEY=dev-webhook-key-genai-mlops` to `.env.example`

---

## Phase 2: US1 — External Client Authentication (Priority: P1) 🎯 MVP

**Goal**: All 12 webhook trigger nodes across 9 workflows reject unauthenticated requests with HTTP 401 when `WEBHOOK_API_KEY` is configured

**Why Foundational**: This phase creates the auth mechanism (httpHeaderAuth credential + webhook node patching) that ALL other user stories depend on. No user story work can begin until this phase is complete.

**Independent Test**: `curl -s -o /dev/null -w "%{http_code}" -X POST localhost:5678/webhook/prompts -H 'Content-Type: application/json' -d '{"action":"list"}'` → 401

### Implementation

- [ ] T002 [US1] Add Step 6 inline Python block to `scripts/n8n-import-all.sh` — read `WEBHOOK_API_KEY` from env, strip whitespace, skip if empty (open mode), create `httpHeaderAuth` credential via `api_post("/credentials", ...)`, handle 409 Conflict by finding existing credential ID
- [ ] T003 [US1] Add webhook node patching logic to Step 6 in `scripts/n8n-import-all.sh` — fetch all workflows via `api_get("/workflows")`, find nodes with `type == "n8n-nodes-base.webhook"`, set `parameters.authentication = "headerAuth"` and `credentials.httpHeaderAuth.id = <cred_id>`, PUT updated workflow back
- [ ] T004 [US1] Run `bash scripts/n8n-import-all.sh` and verify: (1) credential "Webhook API Key" exists, (2) unauthenticated request → 401, (3) authenticated request with `X-API-Key` → 200

**Checkpoint**: Auth mechanism active — unauthenticated external requests are rejected. Internal workflow calls will fail until Phase 3.

---

## Phase 3: US3 — Internal Service-to-Service Calls (Priority: P1)

**Goal**: Code nodes that call other webhook endpoints internally include the `X-API-Key` header so inter-workflow orchestration works with auth enabled

**Independent Test**: Send a chat message that triggers trace logging. Verify the Trace Logger's internal call to `/webhook/traces` succeeds (no 401 in n8n execution logs).

**Dependency**: Phase 2 must be complete (auth mechanism must exist)

### Implementation

- [ ] T005 [P] [US3] Add `X-API-Key` header to internal axios calls in `n8n-data/workflows/chat.json` — Trace Logger node `n8` (2 calls: `/traces`, `/sessions`) and Prompt Resolver node `n2` (1 call: `/sessions`). Pattern: `var WEBHOOK_KEY = process.env.WEBHOOK_API_KEY || 'dev-webhook-key-genai-mlops';` then add `headers: { 'X-API-Key': WEBHOOK_KEY }` to each axios call
- [ ] T006 [P] [US3] Add `X-API-Key` header to internal axios calls in `n8n-data/workflows/a2a-server.json` — Build Agent Card node `a2` (1 call: `/prompts`) and A2A Handler node `a5` (3 calls: `/chat`, `/traces`, `/prompts`). Same WEBHOOK_KEY pattern
- [ ] T007 [US3] Re-import workflows via `bash scripts/n8n-import-all.sh` and verify: send a chat message via `POST /webhook/chat`, confirm trace appears at `/webhook/traces` (internal call authenticated)

**Checkpoint**: All internal service-to-service calls work with auth enabled. Full chat → trace → session pipeline functional.

---

## Phase 4: US2 — Smoke Test Compatibility (Priority: P1)

**Goal**: All 83+ existing smoke tests pass with auth enabled. Dedicated auth verification tests added.

**Independent Test**: `task qa:smoke` — all tests pass

**Dependency**: Phase 3 must be complete (internal calls must work or smoke tests testing chat/trace flows will fail)

### Implementation

- [ ] T008 [US2] Add auth header support to `scripts/smoke-test.sh` — define `API_KEY="${WEBHOOK_API_KEY:-}"` and `CURL_AUTH=()` array, conditionally add `-H "X-API-Key: $API_KEY"` when key is non-empty. Include `"${CURL_AUTH[@]}"` in `check_status()` and `check_json()` helper functions
- [ ] T009 [US2] Add `"${CURL_AUTH[@]}"` to ALL existing standalone curl calls in `scripts/smoke-test.sh` that hit `/webhook/*` endpoints (approximately 34 curl invocations)
- [ ] T010 [US2] Add dedicated auth test section to `scripts/smoke-test.sh` — (1) request without key when auth enabled → expect 401, (2) request with valid key → expect 200
- [ ] T011 [US2] Run `task qa:smoke` and verify all tests pass (83+ existing + new auth tests)

**Checkpoint**: Full regression suite passes. Auth verified both positively (200 with key) and negatively (401 without key).

---

## Phase 5: US4 — Agent Benchmark Compatibility (Priority: P2)

**Goal**: Agent benchmark script works with auth enabled. All 11 test cases pass including previously failing mlops case.

**Independent Test**: `uv run python scripts/agent-benchmark.py` — 11/11 pass

**Dependency**: Phase 2 must be complete (auth active). Phase 3 recommended (internal MCP tool calls need auth).

### Implementation

- [ ] T012 [US4] Add X-API-Key header to all `requests.post()` calls in `scripts/agent-benchmark.py` — define `API_KEY = os.getenv("WEBHOOK_API_KEY", "")` and `HEADERS = {"Content-Type": "application/json"}`, conditionally add `X-API-Key` when key is non-empty, apply HEADERS to all request calls
- [ ] T013 [US4] Run `uv run python scripts/agent-benchmark.py` and verify all test cases pass

**Checkpoint**: Benchmark fully functional with auth. mlops test case (previously failing due to unauthenticated MCP tool calls) now passes.

---

## Phase 6: US5 — Graceful Degradation Without Key (Priority: P3)

**Goal**: When `WEBHOOK_API_KEY` is empty/unset, system operates in open mode — no auth enforcement, full backward compatibility

**Independent Test**: Set `WEBHOOK_API_KEY=` (empty), re-run import, verify all endpoints respond without auth headers

**Dependency**: Phase 2 implementation includes open mode logic. This phase is verification-only.

### Implementation

- [ ] T014 [US5] Verify open mode — set `WEBHOOK_API_KEY=` in `.env`, run `bash scripts/n8n-import-all.sh`, confirm webhook nodes remain `authentication: "none"`, verify endpoints respond without auth: `curl -sf -X POST localhost:5678/webhook/prompts -H 'Content-Type: application/json' -d '{"action":"list"}'` → 200
- [ ] T015 [US5] Verify whitespace-only key treated as empty — set `WEBHOOK_API_KEY="   "`, re-run import, confirm open mode behavior (whitespace stripped, treated as empty)

**Checkpoint**: Open mode verified. New users can run `task dev` without auth configuration.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Spec updates, documentation validation, final verification

- [ ] T016 Update `specs/001-webhook-auth/spec.md` to remove FR-003 (Bearer token dropped per plan deviation in research.md R5)
- [ ] T017 [P] Run quickstart.md validation — execute all commands from `specs/001-webhook-auth/quickstart.md` end-to-end
- [ ] T018 Verify all success criteria from spec.md: SC-001 (all endpoints reject unauth), SC-002 (83+ smoke tests pass), SC-003 (11/11 benchmark), SC-004 (<5ms overhead), SC-005 (single env var setup), SC-006 (unsetting key restores open access)

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1: Setup
  └──→ Phase 2: US1 — Auth Mechanism (BLOCKS ALL)
         ├──→ Phase 3: US3 — Internal Calls (P1)
         │      └──→ Phase 4: US2 — Smoke Tests (P1)
         ├──→ Phase 5: US4 — Benchmark (P2) [can parallel with Phase 3/4]
         └──→ Phase 6: US5 — Open Mode Verification (P3) [can parallel with Phase 3-5]
                        └──→ Phase 7: Polish (after all stories complete)
```

### Critical Path

`T001 → T002 → T003 → T004 → T005/T006 → T007 → T008 → T009 → T010 → T011`

### User Story Independence

| Story | Depends On | Can Parallel With |
|-------|-----------|-------------------|
| US1 (Phase 2) | Setup only | Nothing — blocks all |
| US3 (Phase 3) | US1 | — |
| US2 (Phase 4) | US1, US3 | — |
| US4 (Phase 5) | US1 | US3, US2 |
| US5 (Phase 6) | US1 | US3, US2, US4 |

**Note**: US2 depends on US3 because smoke tests exercise internal call paths (chat → trace). If US3 isn't done, smoke tests for chat/trace workflows will fail with 401 on internal calls.

### Within Each Phase

- T002 → T003 (same file, credential must exist before patching nodes)
- T005 ∥ T006 (different files, true parallel)
- T008 → T009 → T010 (same file, sequential edits)

### Parallel Opportunities

```bash
# After Phase 2 checkpoint:
# Launch US3 workflow edits in parallel (different files):
Task T005: "chat.json internal calls"
Task T006: "a2a-server.json internal calls"

# After Phase 3 checkpoint:
# These can overlap if working on different files:
Task T012: "agent-benchmark.py auth headers" (US4)
Task T014: "Verify open mode" (US5)
# While also working on:
Task T008: "smoke-test.sh auth support" (US2)
```

---

## Implementation Strategy

### MVP First (Phase 1 + Phase 2)

1. Complete Phase 1: Setup (.env.example)
2. Complete Phase 2: Import script auth mechanism
3. **STOP and VALIDATE**: Verify 401/200 behavior manually
4. This alone secures all 12 webhook endpoints

### Incremental Delivery

1. Phase 1 + 2 → Auth active, external requests secured (US1 ✓)
2. Phase 3 → Internal calls work, full pipeline functional (US3 ✓)
3. Phase 4 → Smoke tests pass, quality gate restored (US2 ✓)
4. Phase 5 → Benchmark passes, dev tooling complete (US4 ✓)
5. Phase 6 → Open mode verified, backward compat confirmed (US5 ✓)
6. Phase 7 → Spec updated, all criteria verified

---

## Notes

- All 6 file changes are edits to existing files — no new files created
- Workflow JSON files in git always have `auth=none` — import script patches dynamically
- FR-003 (Bearer token) is dropped — spec update in Phase 7
- n8n 401 response body format may differ from spec's `{"error": "Unauthorized"}` — status code is the reliable indicator (research.md R6)
- Code node WEBHOOK_KEY fallback `'dev-webhook-key-genai-mlops'` appears in committed JSON — acceptable per research.md R3 security note

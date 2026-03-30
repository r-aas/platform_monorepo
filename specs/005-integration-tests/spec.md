<!-- status: shipped -->
<!-- pr: #1 -->
# 005: Integration Tests (pytest)

## Problem

The only automated testing against the live stack is `scripts/smoke-test.sh` — 87 bash curl commands with string-matching. This works but has drawbacks:

- No test isolation or fixtures — shared state between tests
- No parameterization — each agent/error case is a hand-written block
- No programmatic assertions — jq exit codes, not structured checks
- Can't run a subset easily (`pytest -k "chat"` vs commenting out bash blocks)
- No integration with pytest ecosystem (markers, fixtures, reporting)

The existing `tests/test_workflow_json.py` validates workflow JSON structure offline. No tests hit the live stack.

## Requirements

### FR-001: Shared test fixtures
Create `tests/conftest.py` with:
- `base_url` fixture reading `N8N_BASE_URL` env var
- `headers` fixture with conditional `X-API-Key` from `WEBHOOK_API_KEY`
- `api` helper fixture that wraps `requests.post` with base URL + headers + timeout
- Auto-skip when stack is unreachable (connection refused → skip entire module)

### FR-002: Integration marker
Add `integration` marker to `pyproject.toml` so tests can be selected:
- `uv run pytest -m integration` — only integration tests
- `uv run pytest -m "not integration"` — only offline tests
- `uv run pytest` — runs all (default)

### FR-003: Infrastructure tests
- LiteLLM health endpoint reachable
- n8n `/v1/models` returns ≥1 model

### FR-004: Chat completions tests
- Prompt-enhanced path (`model=assistant`) returns `system_fingerprint` starting with `fp_assistant`
- Direct model passthrough returns `fp_inference`
- Bad model → HTTP 404
- Missing messages → HTTP 400

### FR-005: Embeddings tests
- Happy path returns non-empty embedding vector
- Bad model → HTTP 404
- Missing input → HTTP 400

### FR-006: Prompt CRUD tests
- List returns count ≥ 1
- Get prompt by name returns template
- Versions returns ≥ 1 version
- Get or create (idempotent)
- Delete production guard → HTTP 400

### FR-007: Evaluation tests
- Eval with temperature=0 returns response
- Eval history returns action=history
- LLM-as-judge returns scores

### FR-008: Unified chat tests
Parameterized across agents:
- mlops, coder, writer, reasoner — all return non-empty `.response`
- Unknown agent → HTTP 404
- system_prompt override works

### FR-009: Trace tests
- Log trace → returns run_id
- Search traces → returns count
- Summary → returns total_calls
- Chat response includes trace_id

### FR-010: Session tests
- Create → returns session_id
- Append message → message_count ≥ 1
- Get → messages present
- Close → status=closed
- List → count ≥ 0
- Chat with session_id → session_id in response

### FR-011: Webhook auth tests (conditional)
Only when `WEBHOOK_API_KEY` is set:
- Request without key → HTTP 403
- Request with valid key → HTTP 200

**Acceptance**: `uv run pytest tests/test_integration.py -v` passes when stack is running. `uv run pytest tests/test_workflow_json.py` still passes (offline). `uv run pytest -m "not integration"` skips integration tests.

## Files Changed

| File | Action |
|------|--------|
| `specs/005-integration-tests/spec.md` | CREATE |
| `tests/conftest.py` | CREATE — shared fixtures |
| `tests/test_integration.py` | CREATE — live stack tests |
| `pyproject.toml` | EDIT — add integration marker |

## Verification

| Check | Expected |
|-------|----------|
| `uv run pytest tests/test_workflow_json.py` | All pass (offline) |
| `uv run pytest tests/test_integration.py -v` | All pass (stack up) |
| `uv run pytest -m "not integration"` | Only offline tests |
| `uv run pytest -m integration` | Only integration tests |

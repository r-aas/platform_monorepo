<!-- status: shipped -->
<!-- pr: #4 (constitution + spec only) -->
# Spec 008: Real HTTP Streaming

## Problem

The `/v1/chat/completions` endpoint fakes streaming. When `stream=true`, the Chat Handler waits for the full LLM response, splits it into word-level chunks, formats as SSE, and returns the entire payload in a single HTTP response. Clients receive all "chunks" at once — no token-by-token delivery.

This breaks compatibility with OpenAI client libraries that expect real SSE (chunked transfer encoding, tokens arriving progressively) and eliminates the primary UX benefit of streaming: perceived responsiveness.

## Root Cause

n8n webhook nodes buffer the full response before sending. The Respond to Webhook node cannot send incremental SSE chunks (n8n issue #25982, confirmed broken as of March 2026). This is a platform limitation, not a configuration issue.

## Approach: Streaming Proxy Sidecar (Constitution Principle I Escape Hatch)

A thin FastAPI service sits in front of the stack for OpenAI-compatible requests. It delegates to n8n for everything n8n can do (prompt resolution, tracing, session management) and handles streaming directly where n8n cannot.

```
Client ──► Streaming Proxy (port 4010) ──┬─► n8n (prompt resolution, tracing)
                                          └─► LiteLLM (streaming inference)
```

### Routing Logic

| Request | `stream` | Proxy behavior |
|---------|----------|----------------|
| `/v1/chat/completions` | `false` | Pass-through to n8n openai-compat (existing behavior) |
| `/v1/chat/completions` | `true` | Resolve prompt → stream from LiteLLM → log trace |
| `/v1/models` | — | Pass-through to n8n openai-compat |
| `/v1/embeddings` | — | Pass-through to n8n openai-compat |

### Streaming Flow (stream=true)

```
1. Parse request (model, messages, temperature, stream_options)
2. Prompt resolution:
   a. POST n8n /webhook/prompts {"action":"get","name":"{model}.SYSTEM"}
   b. If found: render template, build messages with system prompt
   c. If not found: use model name as LiteLLM model (direct passthrough)
3. Open SSE stream to client (Content-Type: text/event-stream)
4. POST LiteLLM /v1/chat/completions with stream=true
5. For each chunk from LiteLLM:
   a. Forward as `data: {chunk}\n\n` to client
   b. Accumulate content for trace logging
6. Send `data: [DONE]\n\n`
7. Fire-and-forget: POST n8n /webhook/traces with full response metrics
```

## Functional Requirements

### FR-001: Real SSE Streaming

When `stream=true`, the proxy MUST send SSE chunks to the client as they arrive from LiteLLM — not buffered. Each chunk follows the OpenAI format:

```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":N,"model":"M","choices":[{"index":0,"delta":{"content":"token"},"finish_reason":null}]}

```

**SC-001**: Client receives first chunk within 500ms of request (time-to-first-token), not after the full response completes.

### FR-002: Prompt Resolution for Streaming

The proxy MUST resolve MLflow prompt templates before streaming, matching the existing prompt-enhanced path behavior.

- Query n8n `/webhook/prompts` for `{model}.SYSTEM`
- If found: render template with `{{message}}` variable, use `INFERENCE_DEFAULT_MODEL` for inference
- If not found: pass model name directly to LiteLLM (direct passthrough)
- Canary routing is NOT required for v1 (simplification — add in follow-up)

**SC-002**: `stream=true` with `model=coder.SYSTEM` resolves the prompt and streams using the default inference model.
**SC-003**: `stream=true` with `model=qwen2.5:14b` passes through directly to LiteLLM.

### FR-003: Non-streaming Pass-through

When `stream=false` (or absent), the proxy MUST pass the request to n8n openai-compat unchanged. All existing behavior (prompt resolution, canary routing, trace logging) is preserved.

**SC-004**: `stream=false` response is identical to current n8n openai-compat response.

### FR-004: Trace Logging

Streaming responses MUST be traced via fire-and-forget POST to n8n `/webhook/traces`.

- `source: "stream"`
- Includes: model, prompt_name, prompt_version, latency_ms, token counts
- MUST NOT block the SSE stream or add latency to the client

**SC-005**: After a streaming request, a trace appears in Langfuse with source="stream".

### FR-005: Auth Consistency

The proxy MUST enforce the same `X-API-Key` header auth as n8n webhooks.

- Read `WEBHOOK_API_KEY` from environment
- If set: require `X-API-Key` header, return 403 on mismatch
- If unset: open mode (no auth)

**SC-006**: Streaming request without valid API key returns 403.

### FR-006: Usage Reporting

When client sends `stream_options: {"include_usage": true}`, the proxy MUST append a usage chunk after the final content chunk, per OpenAI spec.

**SC-007**: Streaming with `include_usage: true` returns a usage chunk with token counts.

### FR-007: Smoke + Integration Test Coverage

- 3 new smoke tests: real streaming (time-to-first-token), prompt-enhanced streaming, auth on streaming
- 2 new integration tests: streaming response parsing, trace verification

**SC-008**: All new tests pass in CI.

## Non-Functional Requirements

### NFR-001: Minimal Service

The proxy is a single Python file (< 300 lines). No ORM, no database, no state. Configuration via environment variables only. Uses `httpx` for async HTTP and SSE forwarding.

### NFR-002: Same Docker Network

The proxy runs in the same docker-compose stack. Reaches n8n at `http://n8n:5678`, LiteLLM at `http://litellm:4000`.

### NFR-003: Graceful Degradation

If n8n is unreachable for prompt resolution, the proxy falls back to direct LiteLLM passthrough (treating model name as a LiteLLM model). Streaming continues — prompt enhancement is best-effort.

## Out of Scope (Future Specs)

- **Agentic streaming**: Streaming with tool calls interleaved (requires significant architecture — separate spec)
- **Canary routing in streaming path**: Can be added once basic streaming works
- **WebSocket support**: SSE is sufficient for OpenAI compatibility
- **Session integration in streaming path**: Sessions work via `/webhook/chat`, not `/v1/chat/completions`

## Files (Expected)

| File | What |
|------|------|
| `src/streaming_proxy.py` | FastAPI streaming proxy (single file) |
| `Dockerfile.streaming` | Minimal Python image |
| `docker-compose.yml` | New `streaming-proxy` service |
| `scripts/smoke-test.sh` | FR-007: 3 new streaming smoke tests |
| `tests/test_integration.py` | FR-007: 2 new streaming integration tests |

## Verification

| Check | FR | Expected |
|-------|-----|----------|
| `curl -N -H "Accept: text/event-stream" :4010/v1/chat/completions` with `stream=true` | FR-001 | First SSE chunk arrives within 500ms (SC-001) |
| Streaming with `model=coder.SYSTEM` | FR-002 | Prompt resolved from MLflow, streamed via default model (SC-002) |
| Streaming with `model=qwen2.5:14b` | FR-002 | Direct passthrough to LiteLLM (SC-003) |
| Non-streaming request via proxy | FR-003 | Response identical to n8n openai-compat (SC-004) |
| Check Langfuse after streaming request | FR-004 | Trace with `source="stream"` appears (SC-005) |
| Streaming without `X-API-Key` when auth enabled | FR-005 | HTTP 403 (SC-006) |
| Streaming with `stream_options: {"include_usage": true}` | FR-006 | Usage chunk with token counts appended (SC-007) |
| `bash scripts/smoke-test.sh` | FR-007 | All streaming smoke tests pass (SC-008) |
| `uv run pytest tests/test_integration.py -v` | FR-007 | All streaming integration tests pass |
| `docker compose config --quiet` | NFR-002 | Compose file valid with streaming-proxy service |
| Proxy with n8n down, `stream=true` | NFR-003 | Falls back to direct LiteLLM passthrough |

## Architecture Decision Record

**Why a sidecar, not fix n8n?**
- n8n issue #25982 (broken streaming) and PR #20499 (not merged) confirm this is an upstream limitation
- Forcing SSE through n8n creates fragile workarounds (database-backed streaming, etc.)
- Constitution Principle I explicitly allows escape hatches for streaming
- The proxy is < 300 lines — less code than the n8n workaround would require

**Why not LiteLLM direct?**
- Loses prompt resolution (the main value-add of the stack)
- Loses trace logging to Langfuse via n8n
- Loses auth consistency
- The proxy adds prompt resolution + tracing while keeping LiteLLM as the streaming engine

**Why FastAPI?**
- R's standard stack (Constitution: Technology Stack)
- Native async/await + `StreamingResponse`
- `httpx.AsyncClient` for SSE forwarding
- Single file, minimal dependencies (`fastapi`, `uvicorn`, `httpx`)

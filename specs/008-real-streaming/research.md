# Research: n8n Streaming Capabilities

## Can n8n send a streaming HTTP response from a webhook?

**No (as of March 2026).**

n8n added a "Streaming" response mode to the Webhook trigger node (v1.5+), but it is broken:

- **Issue #25982** (Feb 2026, open): Respond to Webhook node sends the entire response as a single chunk — one `begin` event, one `item` with full text, one `end` event. No token-by-token delivery.
- **PR #20499** (Oct 2025, still open): Proposes structured SSE with proper event types. Not merged.
- n8n's streaming format is proprietary (`begin`/`item`/`end`), not OpenAI-compatible `data: {chunk}`.
- Community consensus: Respond to Webhook fires once per execution, cannot maintain persistent SSE.

Sources:
- https://github.com/n8n-io/n8n/issues/25982
- https://github.com/n8n-io/n8n/pull/20499
- https://community.n8n.io/t/send-sse-server-side-events-on-the-respond-to-webhook/42660

## Does LiteLLM support native streaming?

**Yes, fully.**

- `stream=True` on `/v1/chat/completions` → SSE chunks from Ollama converted to OpenAI format
- No special proxy config needed — works out of the box
- Supports `stream_options: {"include_usage": true}` for token counting
- Known issue: `/v1/responses` streaming missing some events (issue #20975) — does NOT affect `/v1/chat/completions`

Sources:
- https://docs.litellm.ai/docs/providers/ollama
- https://docs.litellm.ai/docs/completion/stream

## OpenAI SSE Format

Headers:
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

Chunk format:
```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":N,"model":"M","choices":[{"index":0,"delta":{"content":"token"},"finish_reason":null}]}\n\n
```

Final chunk: `finish_reason: "stop"`, empty delta.
Terminator: `data: [DONE]\n\n`
Optional usage chunk (if `include_usage: true`): empty choices, populated usage object.

## Current genai-mlops Implementation

The openai-compat workflow Chat Handler:
1. Always calls LiteLLM with `stream: false`
2. If `stream=true` in original request: splits full response into ~3-word chunks, pre-formats SSE lines, returns as single text blob
3. Respond to Webhook sends the entire pre-formatted SSE as one HTTP response

Client sees correctly formatted SSE data but receives it all at once — defeating the purpose of streaming.

## Recommended Approach

Thin FastAPI sidecar (< 300 lines) that:
1. Handles `stream=true` by resolving prompts via n8n, then streaming from LiteLLM
2. Passes `stream=false` through to n8n unchanged
3. Logs traces via fire-and-forget

This follows Constitution Principle I (Escape Hatches) and Principle VIII (Component Selection: sidecar for streaming).

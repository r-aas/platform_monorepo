# Contract: OpenAI-Compatible Chat API

**Endpoint**: `POST /v1/chat/completions`
**Spec**: FR-003, FR-008, FR-009, FR-012

## Request

Standard OpenAI chat completions request. Agent routing triggered by `model` prefix.

```json
{
  "model": "agent:mlops",
  "messages": [
    {"role": "user", "content": "How do I deploy a model?"}
  ],
  "stream": true,
  "agent_params": {
    "domain": "machine learning operations"
  }
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| model | string | Yes | `agent:{name}` for agent routing; any other value proxies to LiteLLM |
| messages | array | Yes | Standard OpenAI message objects |
| stream | boolean | No | Default true. SSE when true, JSON when false |
| agent_params | object | No | Values for `{{placeholder}}` resolution in system_prompt |

## Response (streaming)

```
data: {"id":"agw-abc123","object":"chat.completion.chunk","created":1711000000,"model":"agent:mlops","system_fingerprint":"agent:mlops@v3","choices":[{"index":0,"delta":{"role":"assistant","content":"To deploy"},"finish_reason":null}]}

data: {"id":"agw-abc123","object":"chat.completion.chunk","created":1711000000,"model":"agent:mlops","system_fingerprint":"agent:mlops@v3","choices":[{"index":0,"delta":{"content":" a model"},"finish_reason":null}]}

data: {"id":"agw-abc123","object":"chat.completion.chunk","created":1711000000,"model":"agent:mlops","system_fingerprint":"agent:mlops@v3","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

| Field | Value | Notes |
|-------|-------|-------|
| id | `agw-{uuid}` | Gateway-generated request ID |
| model | `agent:{name}` | Echoes the requested agent |
| system_fingerprint | `agent:{name}@v{version}` | Agent name + MLflow prompt version |
| choices[].delta | standard | Same as OpenAI streaming format |

## Response (non-streaming)

```json
{
  "id": "agw-abc123",
  "object": "chat.completion",
  "created": 1711000000,
  "model": "agent:mlops",
  "system_fingerprint": "agent:mlops@v3",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "To deploy a model..."},
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

## Error Responses

| Status | Condition | Body |
|--------|-----------|------|
| 404 | Agent not found | `{"error":{"message":"Agent 'foo' not found. Available: mlops, data-eng","type":"invalid_request_error","code":"model_not_found"}}` |
| 502 | Runtime backend down | `{"error":{"message":"Runtime 'n8n' unavailable for agent 'mlops'","type":"server_error","code":"runtime_unavailable"}}` |
| 503 | MLflow unreachable | `{"error":{"message":"Agent registry unavailable","type":"server_error","code":"registry_unavailable"}}` |

## Routing Logic

```
if model.startswith("agent:"):
    agent_name = model.removeprefix("agent:")
    agent = mlflow_lookup(agent_name)  # 404 if not found
    resolve_placeholders(agent.system_prompt, request.agent_params)
    dispatch_to_runtime(agent.runtime, agent.workflow, messages)
else:
    proxy_to_litellm(request)  # Backward compat (FR-008)
```

## Backward Compatibility (FR-008)

All non-`agent:` model values pass through unchanged to LiteLLM at `http://genai-litellm.genai.svc.cluster.local:4000`. Existing clients using `model=qwen2.5:14b` or `model={prompt_name}` continue to work identically.

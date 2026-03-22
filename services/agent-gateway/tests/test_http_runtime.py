"""Tests for the HTTP (headless LLM) runtime."""

from unittest.mock import AsyncMock, MagicMock, patch

from agent_gateway.models import AgentRunConfig, LlmConfig


# ─── invoke_sync ─────────────────────────────────────────────────────────────

@patch("agent_gateway.runtimes.http.httpx.AsyncClient")
async def test_http_invoke_sync_returns_content(mock_httpx_cls):
    """invoke_sync POSTs to llm_config.url and returns assistant content."""
    from agent_gateway.runtimes.http import HttpRuntime

    mock_client = AsyncMock()
    mock_httpx_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Deployment complete."}}]
    }
    mock_client.post.return_value = mock_response

    config = AgentRunConfig(
        system_prompt="You are mlops.",
        message="deploy model-x",
        agent_name="mlops",
        runtime="http",
        llm_config=LlmConfig(
            url="http://litellm:4000/v1",
            model_id="qwen2.5:14b",
            api_key="test-key",
        ),
    )

    runtime = HttpRuntime()
    result = await runtime.invoke_sync(config)
    assert result == "Deployment complete."

    call_args = mock_client.post.call_args
    assert call_args.args[0] == "http://litellm:4000/v1/chat/completions"
    body = call_args.kwargs["json"]
    assert body["model"] == "qwen2.5:14b"
    assert body["messages"][0] == {"role": "system", "content": "You are mlops."}
    assert body["messages"][1] == {"role": "user", "content": "deploy model-x"}


@patch("agent_gateway.runtimes.http.httpx.AsyncClient")
async def test_http_invoke_sync_no_api_key(mock_httpx_cls):
    """invoke_sync works without api_key — no Authorization header sent."""
    from agent_gateway.runtimes.http import HttpRuntime

    mock_client = AsyncMock()
    mock_httpx_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_client.post.return_value = mock_response

    config = AgentRunConfig(
        system_prompt="sys",
        message="hi",
        agent_name="test",
        runtime="http",
        llm_config=LlmConfig(url="http://ollama:11434/v1", model_id="qwen2.5:14b"),
    )

    runtime = HttpRuntime()
    result = await runtime.invoke_sync(config)
    assert result == "ok"

    headers = mock_client.post.call_args.kwargs.get("headers", {})
    assert "Authorization" not in headers


# ─── invoke (streaming) ───────────────────────────────────────────────────────

@patch("agent_gateway.runtimes.http.httpx.AsyncClient")
async def test_http_invoke_streams_sse_chunks(mock_httpx_cls):
    """invoke yields OpenAI SSE chunks from the LLM stream."""
    from agent_gateway.runtimes.http import HttpRuntime

    sse_lines = [
        'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        'data: {"choices":[{"delta":{"content":" world"}}]}',
        "data: [DONE]",
    ]

    async def fake_aiter_lines():
        for line in sse_lines:
            yield line

    mock_stream_resp = AsyncMock()
    mock_stream_resp.aiter_lines = fake_aiter_lines
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    # stream() is NOT a coroutine — it returns a context manager directly
    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    mock_httpx_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    config = AgentRunConfig(
        system_prompt="sys",
        message="hi",
        agent_name="test",
        runtime="http",
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )

    runtime = HttpRuntime()
    chunks = []
    async for chunk in runtime.invoke(config):
        chunks.append(chunk)

    assert any("Hello" in c for c in chunks)
    assert any("[DONE]" in c for c in chunks)


# ─── missing URL ──────────────────────────────────────────────────────────────

async def test_http_invoke_sync_missing_url():
    """invoke_sync raises ValueError when llm_config.url is empty."""
    from agent_gateway.runtimes.http import HttpRuntime

    config = AgentRunConfig(
        system_prompt="sys",
        message="hi",
        agent_name="test",
        runtime="http",
        llm_config=LlmConfig(url="", model_id="qwen2.5:14b"),
    )

    runtime = HttpRuntime()
    try:
        await runtime.invoke_sync(config)
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "url" in str(exc).lower()


# ─── registered in runtime registry ──────────────────────────────────────────

def test_http_runtime_registered():
    """'http' runtime is available via get_runtime."""
    from agent_gateway.runtimes import get_runtime
    from agent_gateway.runtimes.http import HttpRuntime

    runtime = get_runtime("http")
    assert isinstance(runtime, HttpRuntime)

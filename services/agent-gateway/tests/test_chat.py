"""Tests for chat completions router."""

from unittest.mock import AsyncMock, MagicMock, patch


from agent_gateway.models import AgentDefinition, AgentRunConfig, LlmConfig, SkillDefinition


@patch("agent_gateway.routers.chat.get_runtime")
@patch("agent_gateway.routers.chat.compose")
@patch("agent_gateway.routers.chat.get_agent")
async def test_chat_agent_route(mock_get_agent, mock_compose, mock_get_runtime, client):
    """POST /v1/chat/completions with model=agent:test routes to runtime."""
    mock_get_agent.return_value = AgentDefinition(
        name="test",
        system_prompt="You are test.",
        runtime="n8n",
        workflow="chat-v1",
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_compose.return_value = AgentRunConfig(
        system_prompt="You are test.",
        message="hello",
        agent_name="test",
        runtime="n8n",
        workflow="chat-v1",
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )

    mock_runtime = AsyncMock()
    mock_runtime.invoke_sync.return_value = "Hello! I'm test."
    mock_get_runtime.return_value = mock_runtime

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "agent:test", "messages": [{"role": "user", "content": "hello"}], "stream": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "agent:test"
    assert data["choices"][0]["message"]["content"] == "Hello! I'm test."


@patch("agent_gateway.routers.chat.get_agent")
async def test_chat_agent_not_found(mock_get_agent, client):
    """POST with nonexistent agent returns 404."""
    mock_get_agent.side_effect = KeyError("nonexistent")

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "agent:nonexistent", "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"]["message"].lower()


@patch("agent_gateway.routers.chat.get_runtime")
@patch("agent_gateway.routers.chat.compose")
@patch("agent_gateway.routers.chat.get_skill")
@patch("agent_gateway.routers.chat.get_agent")
async def test_chat_resolves_skills(mock_get_agent, mock_get_skill, mock_compose, mock_get_runtime, client):
    """Skills listed in agent.skills are resolved and passed to compose."""
    skill = SkillDefinition(name="kubernetes-ops", description="K8s skill", prompt_fragment="You can use kubectl.")
    mock_get_agent.return_value = AgentDefinition(
        name="test",
        system_prompt="You are test.",
        runtime="n8n",
        workflow="chat-v1",
        skills=["kubernetes-ops"],
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_get_skill.return_value = skill
    mock_compose.return_value = AgentRunConfig(
        system_prompt="You are test.",
        message="hello",
        agent_name="test",
        runtime="n8n",
        workflow="chat-v1",
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_runtime = AsyncMock()
    mock_runtime.invoke_sync.return_value = "ok"
    mock_get_runtime.return_value = mock_runtime

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "agent:test", "messages": [{"role": "user", "content": "hello"}], "stream": False},
    )
    assert resp.status_code == 200
    mock_get_skill.assert_called_once_with("kubernetes-ops")
    mock_compose.assert_called_once()
    assert mock_compose.call_args.kwargs["skills"] == [skill]


@patch("agent_gateway.routers.chat.get_runtime")
@patch("agent_gateway.routers.chat.compose")
@patch("agent_gateway.routers.chat.get_skill")
@patch("agent_gateway.routers.chat.get_agent")
async def test_chat_skips_missing_skills(mock_get_agent, mock_get_skill, mock_compose, mock_get_runtime, client):
    """Missing skills are skipped gracefully — request still succeeds."""
    mock_get_agent.return_value = AgentDefinition(
        name="test",
        system_prompt="You are test.",
        runtime="n8n",
        workflow="chat-v1",
        skills=["missing-skill"],
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_get_skill.side_effect = KeyError("missing-skill")
    mock_compose.return_value = AgentRunConfig(
        system_prompt="You are test.",
        message="hello",
        agent_name="test",
        runtime="n8n",
        workflow="chat-v1",
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_runtime = AsyncMock()
    mock_runtime.invoke_sync.return_value = "ok"
    mock_get_runtime.return_value = mock_runtime

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "agent:test", "messages": [{"role": "user", "content": "hello"}], "stream": False},
    )
    assert resp.status_code == 200
    assert mock_compose.call_args.kwargs["skills"] == []


@patch("agent_gateway.routers.chat.httpx.AsyncClient")
async def test_chat_litellm_fallback(mock_httpx_cls, client):
    """POST with non-agent model proxies to LiteLLM."""
    mock_httpx = AsyncMock()
    mock_httpx_cls.return_value.__aenter__ = AsyncMock(return_value=mock_httpx)
    mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    mock_httpx.post.return_value = mock_response

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "qwen2.5:14b", "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200

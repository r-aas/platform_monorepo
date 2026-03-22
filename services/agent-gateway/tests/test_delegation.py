"""Tests for agent-to-agent delegation protocol."""

from unittest.mock import AsyncMock, patch

from agent_gateway.models import AgentDefinition, AgentRunConfig, LlmConfig, SkillDefinition


# ─── success ─────────────────────────────────────────────────────────────────

@patch("agent_gateway.routers.delegation.get_runtime")
@patch("agent_gateway.routers.delegation.compose")
@patch("agent_gateway.routers.delegation.get_agent")
async def test_delegate_success(mock_get_agent, mock_compose, mock_get_runtime, client):
    """POST /v1/agents/{to}/delegate returns DelegationResult with success=True."""
    mock_get_agent.return_value = AgentDefinition(
        name="mlops",
        system_prompt="You are mlops.",
        runtime="n8n",
        workflow="chat-v1",
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_compose.return_value = AgentRunConfig(
        system_prompt="You are mlops.",
        message="deploy model-x to staging",
        agent_name="mlops",
        runtime="n8n",
        workflow="chat-v1",
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_runtime = AsyncMock()
    mock_runtime.invoke_sync.return_value = "Deployed model-x to staging."
    mock_get_runtime.return_value = mock_runtime

    resp = await client.post(
        "/v1/agents/mlops/delegate",
        json={"from_agent": "developer", "task": "deploy model-x to staging"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["to_agent"] == "mlops"
    assert data["from_agent"] == "developer"
    assert data["result"] == "Deployed model-x to staging."
    assert data["error"] is None


# ─── agent not found ──────────────────────────────────────────────────────────

@patch("agent_gateway.routers.delegation.get_agent")
async def test_delegate_agent_not_found(mock_get_agent, client):
    """POST to unknown agent returns 404."""
    mock_get_agent.side_effect = KeyError("nonexistent")

    resp = await client.post(
        "/v1/agents/nonexistent/delegate",
        json={"from_agent": "developer", "task": "do something"},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"]["message"].lower()


# ─── runtime unavailable ──────────────────────────────────────────────────────

@patch("agent_gateway.routers.delegation.get_runtime")
@patch("agent_gateway.routers.delegation.compose")
@patch("agent_gateway.routers.delegation.get_agent")
async def test_delegate_runtime_unavailable(mock_get_agent, mock_compose, mock_get_runtime, client):
    """Unknown runtime returns 502."""
    mock_get_agent.return_value = AgentDefinition(
        name="mlops",
        system_prompt="You are mlops.",
        runtime="unknown-runtime",
        llm_config=LlmConfig(),
    )
    mock_compose.return_value = AgentRunConfig(system_prompt="", message="", agent_name="mlops")
    mock_get_runtime.side_effect = ValueError("Runtime 'unknown-runtime' not registered")

    resp = await client.post(
        "/v1/agents/mlops/delegate",
        json={"from_agent": "developer", "task": "do something"},
    )
    assert resp.status_code == 502
    assert "unavailable" in resp.json()["error"]["message"].lower()


# ─── skill resolution ─────────────────────────────────────────────────────────

@patch("agent_gateway.routers.delegation.get_runtime")
@patch("agent_gateway.routers.delegation.compose")
@patch("agent_gateway.routers.delegation.get_skill")
@patch("agent_gateway.routers.delegation.get_agent")
async def test_delegate_resolves_skills(mock_get_agent, mock_get_skill, mock_compose, mock_get_runtime, client):
    """Skills in agent.skills are resolved and passed to compose."""
    skill = SkillDefinition(name="kubernetes-ops", description="K8s", prompt_fragment="kubectl")
    mock_get_agent.return_value = AgentDefinition(
        name="mlops",
        system_prompt="You are mlops.",
        runtime="n8n",
        workflow="chat-v1",
        skills=["kubernetes-ops"],
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_get_skill.return_value = skill
    mock_compose.return_value = AgentRunConfig(
        system_prompt="You are mlops.",
        message="check pods",
        agent_name="mlops",
        runtime="n8n",
        workflow="chat-v1",
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_runtime = AsyncMock()
    mock_runtime.invoke_sync.return_value = "Pods are running."
    mock_get_runtime.return_value = mock_runtime

    resp = await client.post(
        "/v1/agents/mlops/delegate",
        json={"from_agent": "developer", "task": "check pods"},
    )
    assert resp.status_code == 200
    mock_get_skill.assert_called_once_with("kubernetes-ops")
    mock_compose.assert_called_once()
    assert mock_compose.call_args.kwargs["skills"] == [skill]


# ─── optional params passthrough ─────────────────────────────────────────────

@patch("agent_gateway.routers.delegation.get_runtime")
@patch("agent_gateway.routers.delegation.compose")
@patch("agent_gateway.routers.delegation.get_agent")
async def test_delegate_params_forwarded(mock_get_agent, mock_compose, mock_get_runtime, client):
    """Optional params are forwarded to compose as agent_params."""
    mock_get_agent.return_value = AgentDefinition(
        name="mlops",
        system_prompt="You are mlops.",
        runtime="n8n",
        workflow="chat-v1",
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_compose.return_value = AgentRunConfig(
        system_prompt="You are mlops.",
        message="deploy",
        agent_name="mlops",
        runtime="n8n",
        workflow="chat-v1",
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
    )
    mock_runtime = AsyncMock()
    mock_runtime.invoke_sync.return_value = "done"
    mock_get_runtime.return_value = mock_runtime

    resp = await client.post(
        "/v1/agents/mlops/delegate",
        json={"from_agent": "developer", "task": "deploy", "params": {"env": "staging"}},
    )
    assert resp.status_code == 200
    assert mock_compose.call_args.kwargs["params"] == {"env": "staging"}

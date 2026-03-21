"""Tests for agent registry (MLflow prompt lookup)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_gateway.models import AgentDefinition
from agent_gateway.registry import get_agent, list_agents


@pytest.fixture
def mock_prompt_version():
    version = MagicMock()
    version.template = "You are a test agent."
    version.version = 3
    version.tags = {
        "runtime": "n8n",
        "workflow": "chat-v1",
        "llm_model": "qwen2.5:14b",
        "llm_url": "http://litellm:4000/v1",
        "agentspec_version": "26.2.0",
        "agent_description": "Test agent",
        "mcp_servers_json": json.dumps([{"url": "http://metamcp/genai/mcp", "tool_filter": None}]),
        "skills_json": json.dumps(["skill-a"]),
    }
    return version


@patch("agent_gateway.registry.mlflow.MlflowClient")
async def test_get_agent(mock_client_cls, mock_prompt_version):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_prompt_version.return_value = mock_prompt_version

    agent = await get_agent("test-agent")
    assert isinstance(agent, AgentDefinition)
    assert agent.name == "test-agent"
    assert agent.system_prompt == "You are a test agent."
    assert agent.runtime == "n8n"
    assert agent.skills == ["skill-a"]
    assert len(agent.mcp_servers) == 1


@patch("agent_gateway.registry.mlflow.MlflowClient")
async def test_get_agent_not_found(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_prompt_version.side_effect = Exception("not found")

    with pytest.raises(KeyError):
        await get_agent("nonexistent")


@patch("agent_gateway.registry.mlflow.MlflowClient")
async def test_list_agents(mock_client_cls, mock_prompt_version):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_prompt = MagicMock()
    mock_prompt.name = "agent:test-agent"
    mock_client.search_prompts.return_value = [mock_prompt]
    mock_client.get_prompt_version.return_value = mock_prompt_version

    agents = await list_agents()
    assert len(agents) == 1
    assert agents[0].name == "test-agent"

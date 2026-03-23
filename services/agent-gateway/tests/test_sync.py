"""Tests for agent sync to MLflow."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_gateway.agentspec.sync import sync_agent
from agent_gateway.models import AgentDefinition, LlmConfig, MCPServerRef


@pytest.fixture
def sample_agent():
    return AgentDefinition(
        name="test-agent",
        description="Test agent",
        system_prompt="You are a test agent.",
        mcp_servers=[MCPServerRef(url="http://metamcp:12008/metamcp/genai/mcp")],
        skills=["skill-a", "skill-b"],
        llm_config=LlmConfig(url="http://litellm:4000/v1", model_id="qwen2.5:14b"),
        runtime="n8n",
        workflow="chat-v1",
        agentspec_version="26.2.0",
    )


@patch("agent_gateway.agentspec.sync.mlflow.MlflowClient")
def test_sync_agent_creates_prompt(mock_client_cls, sample_agent):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.search_prompts.return_value = []

    sync_agent(sample_agent)

    mock_client.create_prompt.assert_called_once_with(
        name="agent:test-agent",
        description="Test agent",
    )


@patch("agent_gateway.agentspec.sync.mlflow.MlflowClient")
def test_sync_agent_creates_version_with_tags(mock_client_cls, sample_agent):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.search_prompts.return_value = []

    sync_agent(sample_agent)

    call_args = mock_client.create_prompt_version.call_args
    assert call_args.kwargs["name"] == "agent:test-agent"
    assert "You are a test agent." in call_args.kwargs["template"]

    tags = call_args.kwargs["tags"]
    assert tags["runtime"] == "n8n"
    assert tags["workflow"] == "chat-v1"
    assert tags["llm_model"] == "qwen2.5:14b"
    assert tags["llm_url"] == "http://litellm:4000/v1"
    assert tags["agentspec_version"] == "26.2.0"
    assert tags["agent_description"] == "Test agent"

    mcp_servers = json.loads(tags["mcp_servers_json"])
    assert len(mcp_servers) == 1
    assert mcp_servers[0]["url"] == "http://metamcp:12008/metamcp/genai/mcp"

    skills = json.loads(tags["skills_json"])
    assert skills == ["skill-a", "skill-b"]


@patch("agent_gateway.agentspec.sync.mlflow.MlflowClient")
def test_sync_agent_updates_existing(mock_client_cls, sample_agent):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    # Simulate existing prompt
    mock_client.search_prompts.return_value = [MagicMock()]

    sync_agent(sample_agent)

    # Should not create, just create a new version
    mock_client.create_prompt.assert_not_called()
    mock_client.create_prompt_version.assert_called_once()

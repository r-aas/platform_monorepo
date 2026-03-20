"""Tests for skills registry (MLflow model backend)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_gateway.models import MCPServerRef, SkillDefinition, TaskDefinition
from agent_gateway.skills_registry import create_skill, delete_skill, get_skill, list_skills


@pytest.fixture
def sample_skill():
    return SkillDefinition(
        name="k8s-ops",
        description="Kubernetes operations",
        version="1.0.0",
        tags=["infrastructure"],
        mcp_servers=[MCPServerRef(url="http://metamcp/genai/mcp", tool_filter=["kubectl_get"])],
        prompt_fragment="When performing k8s ops, check state first.",
        tasks=[TaskDefinition(name="deploy-model", description="Deploy a model")],
    )


@patch("agent_gateway.skills_registry.mlflow.MlflowClient")
def test_create_skill(mock_client_cls, sample_skill):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.search_registered_models.return_value = []

    create_skill(sample_skill)

    mock_client.create_registered_model.assert_called_once()
    call_name = mock_client.create_registered_model.call_args[1]["name"]
    assert call_name == "skill:k8s-ops"


@patch("agent_gateway.skills_registry.mlflow.MlflowClient")
def test_create_skill_conflict(mock_client_cls, sample_skill):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.search_registered_models.return_value = [MagicMock()]

    with pytest.raises(ValueError, match="already exists"):
        create_skill(sample_skill)


@patch("agent_gateway.skills_registry.mlflow.MlflowClient")
def test_get_skill(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_model = MagicMock()
    mock_model.name = "skill:k8s-ops"
    mock_model.tags = {
        "description": "Kubernetes operations",
        "version": "1.0.0",
        "tags_json": json.dumps(["infrastructure"]),
        "mcp_servers_json": json.dumps([{"url": "http://metamcp/genai/mcp", "tool_filter": ["kubectl_get"]}]),
        "prompt_fragment": "Check state first.",
        "tasks_json": json.dumps([{"name": "deploy-model", "description": "Deploy a model"}]),
    }
    mock_client.get_registered_model.return_value = mock_model

    skill = get_skill("k8s-ops")
    assert skill.name == "k8s-ops"
    assert skill.description == "Kubernetes operations"
    assert len(skill.mcp_servers) == 1
    assert skill.mcp_servers[0].tool_filter == ["kubectl_get"]


@patch("agent_gateway.skills_registry.mlflow.MlflowClient")
def test_list_skills(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_model = MagicMock()
    mock_model.name = "skill:k8s-ops"
    mock_model.tags = {
        "description": "K8s ops",
        "version": "1.0.0",
        "tags_json": "[]",
        "mcp_servers_json": "[]",
        "prompt_fragment": "",
        "tasks_json": "[]",
    }
    mock_client.search_registered_models.return_value = [mock_model]

    skills = list_skills()
    assert len(skills) == 1
    assert skills[0].name == "k8s-ops"


@patch("agent_gateway.skills_registry.mlflow.MlflowClient")
def test_delete_skill_no_references(mock_client_cls):
    """delete_skill succeeds when no agents reference the skill."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.search_prompts.return_value = []

    delete_skill("k8s-ops")

    mock_client.delete_registered_model.assert_called_once_with("skill:k8s-ops")


@patch("agent_gateway.skills_registry.mlflow.MlflowClient")
def test_delete_skill_blocks_when_referenced(mock_client_cls):
    """delete_skill raises ValueError when an agent references the skill and force=False."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_version = MagicMock()
    mock_version.tags = {"skills_json": json.dumps(["k8s-ops", "other-skill"])}
    mock_prompt = MagicMock()
    mock_prompt.name = "agent:platform-admin"
    mock_prompt.latest_versions = [mock_version]
    mock_client.search_prompts.return_value = [mock_prompt]

    with pytest.raises(ValueError, match="platform-admin"):
        delete_skill("k8s-ops", force=False)

    mock_client.delete_registered_model.assert_not_called()


@patch("agent_gateway.skills_registry.mlflow.MlflowClient")
def test_delete_skill_force_ignores_references(mock_client_cls):
    """delete_skill with force=True deletes even when agents reference the skill."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_version = MagicMock()
    mock_version.tags = {"skills_json": json.dumps(["k8s-ops"])}
    mock_prompt = MagicMock()
    mock_prompt.name = "agent:platform-admin"
    mock_prompt.latest_versions = [mock_version]
    mock_client.search_prompts.return_value = [mock_prompt]

    delete_skill("k8s-ops", force=True)

    mock_client.delete_registered_model.assert_called_once_with("skill:k8s-ops")

"""Tests for factory health endpoint — F.01."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_gateway.mcp_discovery import DiscoveredTool, ToolIndex
from agent_gateway.models import AgentDefinition
from agent_gateway.routers.factory import _scan_eval_datasets, compute_health_status
from agent_gateway.skills_registry import SkillDefinition


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


def test_scan_eval_datasets_empty(tmp_path: Path) -> None:
    result = _scan_eval_datasets(tmp_path / "nonexistent")
    assert result == {}


def test_scan_eval_datasets_finds_files(tmp_path: Path) -> None:
    skill_dir = tmp_path / "kubernetes-ops"
    skill_dir.mkdir()
    (skill_dir / "deploy-model.json").write_text("{}")
    (skill_dir / "check-status.json").write_text("{}")

    result = _scan_eval_datasets(tmp_path)
    assert "kubernetes-ops" in result
    assert sorted(result["kubernetes-ops"]) == ["check-status", "deploy-model"]


def test_scan_eval_datasets_ignores_non_json(tmp_path: Path) -> None:
    skill_dir = tmp_path / "mlflow-tracking"
    skill_dir.mkdir()
    (skill_dir / "log-metrics.json").write_text("{}")
    (skill_dir / "README.md").write_text("docs")

    result = _scan_eval_datasets(tmp_path)
    assert result["mlflow-tracking"] == ["log-metrics"]


def test_compute_health_status_healthy() -> None:
    assert compute_health_status(agents=3, skills=6, mcp_tools=10) == "healthy"


def test_compute_health_status_degraded() -> None:
    assert compute_health_status(agents=0, skills=0, mcp_tools=0) == "degraded"


def test_compute_health_status_partial() -> None:
    assert compute_health_status(agents=2, skills=0, mcp_tools=0) == "partial"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_health_endpoint_returns_structure(client) -> None:
    mock_agents = [MagicMock(spec=AgentDefinition)]
    mock_skills = [MagicMock(spec=SkillDefinition), MagicMock(spec=SkillDefinition)]
    mock_index = ToolIndex(namespaces=["genai"], tools=[DiscoveredTool("t1", "tool 1", "genai")])

    with (
        patch("agent_gateway.routers.factory.list_agents", new_callable=AsyncMock, return_value=mock_agents),
        patch("agent_gateway.routers.factory.list_skills", return_value=mock_skills),
        patch("agent_gateway.routers.factory.get_tool_index", return_value=mock_index),
        patch("agent_gateway.routers.factory._scan_eval_datasets", return_value={"kubernetes-ops": ["deploy-model"]}),
    ):
        response = await client.get("/factory/health")

    assert response.status_code == 200
    body = response.json()
    assert body["agents_loaded"] == 1
    assert body["skills_loaded"] == 2
    assert body["mcp_tools_indexed"] == 1
    assert body["eval_datasets_found"] == 1
    assert body["status"] == "healthy"
    assert "eval_datasets" in body


@pytest.mark.asyncio
async def test_factory_health_endpoint_degraded_when_empty(client) -> None:
    with (
        patch("agent_gateway.routers.factory.list_agents", new_callable=AsyncMock, return_value=[]),
        patch("agent_gateway.routers.factory.list_skills", return_value=[]),
        patch("agent_gateway.routers.factory.get_tool_index", return_value=None),
        patch("agent_gateway.routers.factory._scan_eval_datasets", return_value={}),
    ):
        response = await client.get("/factory/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["agents_loaded"] == 0
    assert body["skills_loaded"] == 0
    assert body["mcp_tools_indexed"] == 0


@pytest.mark.asyncio
async def test_factory_health_endpoint_survives_exceptions(client) -> None:
    """Health endpoint must return 200 even if registries throw."""
    with (
        patch("agent_gateway.routers.factory.list_agents", new_callable=AsyncMock, side_effect=Exception("mlflow down")),
        patch("agent_gateway.routers.factory.list_skills", side_effect=Exception("mlflow down")),
        patch("agent_gateway.routers.factory.get_tool_index", return_value=None),
        patch("agent_gateway.routers.factory._scan_eval_datasets", return_value={}),
    ):
        response = await client.get("/factory/health")

    assert response.status_code == 200
    body = response.json()
    assert body["agents_loaded"] == 0
    assert body["skills_loaded"] == 0

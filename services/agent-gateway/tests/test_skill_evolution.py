"""Tests for auto-skill-evolution endpoint — F.04."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_evolve_returns_list(client, tmp_path: Path) -> None:
    """GET /factory/evolve returns list of skills with improvement scores."""
    # Create a minimal skill YAML with no eval datasets
    skill_yaml = tmp_path / "dummy-skill.yaml"
    skill_yaml.write_text(
        yaml.dump(
            {
                "name": "dummy-skill",
                "prompt_fragment": "Handle kubernetes operations.",
                "tasks": [],
            }
        )
    )

    with (
        patch("agent_gateway.routers.factory.Path") as MockPath,
    ):
        # Point skills_dir to our tmp_path
        mock_skills_dir = tmp_path
        MockPath.return_value = mock_skills_dir
        MockPath.side_effect = lambda x: Path(x) if x != "evolve_skills_dir" else mock_skills_dir

        # Easier: just mock the scan and optimize functions directly
        pass

    # Use a simpler approach: mock scan_skill_yamls and optimize_skill_prompt
    dummy_result = {
        "skill": "dummy-skill",
        "before_score": 0.5,
        "after_score": 0.8,
        "uncovered_terms": ["kubectl", "namespace"],
        "improved_prompt": "Handle kubernetes operations.\n  - When relevant, include: kubectl",
        "improvement": 0.3,
    }

    with patch("agent_gateway.routers.factory.scan_skill_yamls", return_value=[tmp_path / "dummy-skill.yaml"]):
        with patch("agent_gateway.routers.factory.optimize_skill_prompt", return_value=dummy_result):
            response = await client.get("/factory/evolve")

    assert response.status_code == 200
    body = response.json()
    assert "skills_analyzed" in body
    assert "results" in body
    assert body["skills_analyzed"] == 1
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["skill"] == "dummy-skill"
    assert result["before_score"] == pytest.approx(0.5)
    assert result["after_score"] == pytest.approx(0.8)
    assert result["improvement"] == pytest.approx(0.3)
    assert "uncovered_terms" in result


@pytest.mark.asyncio
async def test_factory_evolve_sorts_by_improvement_desc(client, tmp_path: Path) -> None:
    """Results are sorted by improvement descending (highest first)."""
    results = [
        {"skill": "skill-a", "before_score": 0.9, "after_score": 0.9, "improvement": 0.0, "uncovered_terms": [], "improved_prompt": ""},
        {"skill": "skill-b", "before_score": 0.3, "after_score": 0.8, "improvement": 0.5, "uncovered_terms": ["x"], "improved_prompt": ""},
        {"skill": "skill-c", "before_score": 0.5, "after_score": 0.7, "improvement": 0.2, "uncovered_terms": ["y"], "improved_prompt": ""},
    ]

    with patch("agent_gateway.routers.factory.scan_skill_yamls", return_value=[Path("a"), Path("b"), Path("c")]):
        with patch("agent_gateway.routers.factory.optimize_skill_prompt", side_effect=results):
            response = await client.get("/factory/evolve")

    assert response.status_code == 200
    body = response.json()
    improvements = [r["improvement"] for r in body["results"]]
    assert improvements == sorted(improvements, reverse=True)
    assert body["results"][0]["skill"] == "skill-b"


@pytest.mark.asyncio
async def test_factory_evolve_no_skills(client) -> None:
    """Returns empty results when no skill YAMLs found."""
    with patch("agent_gateway.routers.factory.scan_skill_yamls", return_value=[]):
        response = await client.get("/factory/evolve")

    assert response.status_code == 200
    body = response.json()
    assert body["skills_analyzed"] == 0
    assert body["results"] == []


@pytest.mark.asyncio
async def test_factory_evolve_skips_erroring_skills(client) -> None:
    """Skills that raise during optimization are skipped, not fatal."""
    with patch("agent_gateway.routers.factory.scan_skill_yamls", return_value=[Path("bad.yaml")]):
        with patch("agent_gateway.routers.factory.optimize_skill_prompt", side_effect=Exception("parse error")):
            response = await client.get("/factory/evolve")

    assert response.status_code == 200
    body = response.json()
    assert body["skills_analyzed"] == 0
    assert body["results"] == []


# ---------------------------------------------------------------------------
# Pure function test — scan_skill_yamls
# ---------------------------------------------------------------------------


def test_scan_skill_yamls_finds_yaml_files(tmp_path: Path) -> None:
    from agent_gateway.routers.factory import scan_skill_yamls

    (tmp_path / "skill-a.yaml").write_text("name: skill-a")
    (tmp_path / "skill-b.yaml").write_text("name: skill-b")
    (tmp_path / "README.md").write_text("docs")

    result = scan_skill_yamls(tmp_path)
    names = {p.name for p in result}
    assert names == {"skill-a.yaml", "skill-b.yaml"}


def test_scan_skill_yamls_missing_dir(tmp_path: Path) -> None:
    from agent_gateway.routers.factory import scan_skill_yamls

    result = scan_skill_yamls(tmp_path / "nonexistent")
    assert result == []

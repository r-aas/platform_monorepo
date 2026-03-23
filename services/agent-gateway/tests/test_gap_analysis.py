"""Tests for skill gap analysis — F.03."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent_gateway.benchmark.gap_analysis import (
    GapAnalysisResult,
    analyze_skill_gaps,
    find_defined_skills,
    find_referenced_skills,
)
from agent_gateway.models import AgentDefinition, SkillDefinition


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


def _make_agent(name: str, skills: list[str]) -> AgentDefinition:
    return AgentDefinition(name=name, skills=skills)


def _make_skill(name: str) -> SkillDefinition:
    return SkillDefinition(name=name)


def test_find_referenced_skills_collects_all_agent_skill_refs() -> None:
    agents = [
        _make_agent("mlops", ["kubernetes-ops", "mlflow-tracking"]),
        _make_agent("developer", ["code-generation", "documentation"]),
    ]
    result = find_referenced_skills(agents)
    assert result == {"kubernetes-ops", "mlflow-tracking", "code-generation", "documentation"}


def test_find_referenced_skills_deduplicates() -> None:
    agents = [
        _make_agent("a", ["kubernetes-ops"]),
        _make_agent("b", ["kubernetes-ops", "mlflow-tracking"]),
    ]
    result = find_referenced_skills(agents)
    assert result == {"kubernetes-ops", "mlflow-tracking"}


def test_find_referenced_skills_empty() -> None:
    assert find_referenced_skills([]) == set()
    assert find_referenced_skills([_make_agent("a", [])]) == set()


def test_find_defined_skills_returns_names() -> None:
    skills = [_make_skill("kubernetes-ops"), _make_skill("mlflow-tracking")]
    result = find_defined_skills(skills)
    assert result == {"kubernetes-ops", "mlflow-tracking"}


def test_find_defined_skills_empty() -> None:
    assert find_defined_skills([]) == set()


def test_analyze_skill_gaps_identifies_missing() -> None:
    referenced = {"kubernetes-ops", "mlflow-tracking", "missing-skill"}
    defined = {"kubernetes-ops", "mlflow-tracking"}
    result = analyze_skill_gaps(referenced, defined)
    assert isinstance(result, GapAnalysisResult)
    assert result.missing_skills == {"missing-skill"}
    assert result.unused_skills == set()
    assert result.covered_skills == {"kubernetes-ops", "mlflow-tracking"}


def test_analyze_skill_gaps_identifies_unused() -> None:
    referenced = {"kubernetes-ops"}
    defined = {"kubernetes-ops", "orphan-skill"}
    result = analyze_skill_gaps(referenced, defined)
    assert result.missing_skills == set()
    assert result.unused_skills == {"orphan-skill"}
    assert result.covered_skills == {"kubernetes-ops"}


def test_analyze_skill_gaps_all_covered() -> None:
    skills = {"kubernetes-ops", "mlflow-tracking"}
    result = analyze_skill_gaps(skills, skills)
    assert result.missing_skills == set()
    assert result.unused_skills == set()
    assert result.covered_skills == skills


def test_analyze_skill_gaps_empty() -> None:
    result = analyze_skill_gaps(set(), set())
    assert result.missing_skills == set()
    assert result.unused_skills == set()
    assert result.covered_skills == set()


def test_gap_analysis_result_coverage_ratio() -> None:
    referenced = {"a", "b", "c", "d"}
    defined = {"a", "b", "x"}  # a,b covered; c,d missing; x unused
    result = analyze_skill_gaps(referenced, defined)
    # coverage = |covered| / |referenced| = 2/4 = 0.5
    assert result.coverage_ratio == pytest.approx(0.5)


def test_gap_analysis_result_coverage_ratio_zero_referenced() -> None:
    result = analyze_skill_gaps(set(), {"unused-skill"})
    # No skills referenced → coverage undefined → 1.0 (nothing is missing)
    assert result.coverage_ratio == 1.0


# ---------------------------------------------------------------------------
# Endpoint test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_gaps_endpoint_returns_structure(client) -> None:
    # Use real model objects — MagicMock intercepts `name` as a special parameter
    real_agent = AgentDefinition(name="mlops", skills=["kubernetes-ops", "missing-skill"])
    real_skill = SkillDefinition(name="kubernetes-ops")

    with (
        patch("agent_gateway.routers.factory.list_agents", new_callable=AsyncMock, return_value=[real_agent]),
        patch("agent_gateway.routers.factory.list_skills", return_value=[real_skill]),
    ):
        response = await client.get("/factory/gaps")

    assert response.status_code == 200
    body = response.json()
    assert "missing_skills" in body
    assert "unused_skills" in body
    assert "covered_skills" in body
    assert "coverage_ratio" in body
    assert "missing-skill" in body["missing_skills"]
    assert "kubernetes-ops" in body["covered_skills"]

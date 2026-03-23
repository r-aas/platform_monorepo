"""Tests for MCP tool recommendation engine (C.03)."""

import pytest  # noqa: F401

from agent_gateway.mcp_discovery import DiscoveredTool, ToolIndex, set_tool_index
from agent_gateway.mcp_recommender import ToolRecommendation, score_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TOOLS = [
    DiscoveredTool(name="kubectl_get", description="Get kubernetes resources", namespace="platform"),
    DiscoveredTool(name="kubectl_apply", description="Apply kubernetes manifests", namespace="platform"),
    DiscoveredTool(name="n8n_trigger", description="Trigger n8n workflow", namespace="genai"),
    DiscoveredTool(name="mlflow_log", description="Log metrics to MLflow experiment", namespace="genai"),
    DiscoveredTool(name="gitlab_push", description="Push code to GitLab repository", namespace="platform"),
]


# ---------------------------------------------------------------------------
# Pure function tests (no async, no HTTP)
# ---------------------------------------------------------------------------


def test_score_tools_empty_tools_returns_empty():
    result = score_tools("deploy kubernetes", [], top_n=5, min_score=0.0)
    assert result == []


def test_score_tools_keyword_match_name():
    result = score_tools("kubectl", TOOLS, top_n=5, min_score=0.0)
    names = [r.name for r in result]
    assert "kubectl_get" in names
    assert "kubectl_apply" in names


def test_score_tools_keyword_match_description():
    result = score_tools("metrics experiment", TOOLS, top_n=5, min_score=0.0)
    names = [r.name for r in result]
    assert "mlflow_log" in names


def test_score_tools_min_score_filter():
    # "unrelated" doesn't match any tool name/description
    result = score_tools("unrelated query xyz", TOOLS, top_n=5, min_score=1.0)
    assert result == []


def test_score_tools_top_n_limit():
    result = score_tools("kubernetes", TOOLS, top_n=1, min_score=0.0)
    assert len(result) <= 1


def test_score_tools_returns_sorted_descending():
    result = score_tools("kubectl kubernetes", TOOLS, top_n=5, min_score=0.0)
    scores = [r.score for r in result]
    assert scores == sorted(scores, reverse=True)


def test_score_tools_match_hints_name():
    result = score_tools("kubectl", TOOLS, top_n=5, min_score=0.0)
    kubectl_rec = next(r for r in result if r.name == "kubectl_get")
    assert any("name" in h for h in kubectl_rec.match_hints)


def test_score_tools_match_hints_description():
    result = score_tools("workflow", TOOLS, top_n=5, min_score=0.0)
    n8n_rec = next((r for r in result if r.name == "n8n_trigger"), None)
    assert n8n_rec is not None
    assert any("description" in h for h in n8n_rec.match_hints)


def test_score_tools_result_is_tool_recommendation():
    result = score_tools("kubernetes", TOOLS, top_n=5, min_score=0.0)
    assert len(result) > 0
    rec = result[0]
    assert isinstance(rec, ToolRecommendation)
    assert rec.name
    assert rec.namespace
    assert isinstance(rec.score, float)
    assert isinstance(rec.match_hints, list)


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


async def test_recommend_endpoint_returns_correct_shape(client):
    # Seed index with known tools
    set_tool_index(ToolIndex(namespaces=["platform", "genai"], tools=TOOLS))
    resp = await client.get("/mcp/recommend?task=deploy+kubernetes")
    assert resp.status_code == 200
    data = resp.json()
    assert "task" in data
    assert "recommendations" in data
    assert isinstance(data["recommendations"], list)


async def test_recommend_endpoint_uses_cached_index(client):
    set_tool_index(ToolIndex(namespaces=["platform"], tools=[TOOLS[0], TOOLS[1]]))
    resp = await client.get("/mcp/recommend?task=kubectl")
    assert resp.status_code == 200
    data = resp.json()
    names = [r["name"] for r in data["recommendations"]]
    assert any("kubectl" in n for n in names)


async def test_recommend_endpoint_top_n_param(client):
    set_tool_index(ToolIndex(namespaces=["platform", "genai"], tools=TOOLS))
    resp = await client.get("/mcp/recommend?task=kubernetes&top_n=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["recommendations"]) <= 2


async def test_recommend_endpoint_includes_match_hints(client):
    set_tool_index(ToolIndex(namespaces=["platform"], tools=TOOLS))
    resp = await client.get("/mcp/recommend?task=kubectl")
    assert resp.status_code == 200
    data = resp.json()
    if data["recommendations"]:
        rec = data["recommendations"][0]
        assert "match_hints" in rec
        assert isinstance(rec["match_hints"], list)

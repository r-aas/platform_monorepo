"""Tests for MCP tool search endpoint — D.04 MCP tool search with semantic similarity."""

from unittest.mock import patch

from agent_gateway.mcp_discovery import DiscoveredTool, ToolIndex


def _idx(*tools: DiscoveredTool) -> ToolIndex:
    namespaces = list({t.namespace for t in tools})
    return ToolIndex(namespaces=namespaces, tools=list(tools))


@patch("agent_gateway.routers.mcp.get_embedding", return_value=None)
@patch("agent_gateway.routers.mcp.get_tool_index")
async def test_search_mcp_keyword_match(mock_idx, mock_emb, client):
    mock_idx.return_value = _idx(
        DiscoveredTool(name="kubectl_get", description="Get kubernetes resources", namespace="platform"),
        DiscoveredTool(name="mlflow_log", description="Log metrics to MLflow experiment", namespace="genai"),
    )

    resp = await client.get("/mcp/search?q=kubernetes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "kubernetes"
    assert len(data["results"]) >= 1
    assert data["results"][0]["name"] == "kubectl_get"


@patch("agent_gateway.routers.mcp.get_embedding", return_value=None)
@patch("agent_gateway.routers.mcp.get_tool_index")
async def test_search_mcp_no_match_returns_empty(mock_idx, mock_emb, client):
    mock_idx.return_value = _idx(
        DiscoveredTool(name="kubectl_get", description="Get kubernetes resources", namespace="platform"),
    )

    resp = await client.get("/mcp/search?q=totally-unrelated-xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []


@patch("agent_gateway.routers.mcp.cosine_similarity", return_value=0.85)
@patch("agent_gateway.routers.mcp.get_embedding", return_value=[0.1, 0.2, 0.3])
@patch("agent_gateway.routers.mcp.get_tool_index")
async def test_search_mcp_with_embedding_scores(mock_idx, mock_emb, mock_cos, client):
    mock_idx.return_value = _idx(
        DiscoveredTool(name="n8n_trigger", description="Trigger n8n workflow execution", namespace="genai"),
    )

    resp = await client.get("/mcp/search?q=trigger workflow")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    result = data["results"][0]
    assert result["name"] == "n8n_trigger"
    assert result["score"] > 0
    assert "namespace" in result


@patch("agent_gateway.routers.mcp.get_embedding", return_value=None)
@patch("agent_gateway.routers.mcp.get_tool_index")
async def test_search_mcp_embedding_fallback_keyword_only(mock_idx, mock_emb, client):
    """When Ollama is unavailable (embedding=None), keyword scoring still returns results."""
    mock_idx.return_value = _idx(
        DiscoveredTool(name="gitlab_push", description="Push code to GitLab repository", namespace="platform"),
        DiscoveredTool(name="kubectl_apply", description="Apply kubernetes manifests", namespace="platform"),
    )

    resp = await client.get("/mcp/search?q=gitlab")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["name"] == "gitlab_push"

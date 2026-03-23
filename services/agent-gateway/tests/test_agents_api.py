"""Tests for agent search API endpoints — D.03 agent search with semantic similarity."""

from unittest.mock import patch

from agent_gateway.models import AgentDefinition


def _agent(name: str, description: str, skills: list[str] | None = None) -> AgentDefinition:
    return AgentDefinition(
        name=name,
        description=description,
        system_prompt=f"You are the {name} agent.",
        runtime="n8n",
        skills=skills or [],
    )


@patch("agent_gateway.routers.agents.get_embedding", return_value=None)
@patch("agent_gateway.routers.agents.list_agents")
async def test_search_agents_keyword_match(mock_list, mock_emb, client):
    mock_list.return_value = [
        _agent("mlops", "Deploy and monitor ML models", ["kubernetes-ops", "mlflow-tracking"]),
        _agent("developer", "Write and review code", ["code-generation"]),
    ]

    resp = await client.get("/agents/search?q=deploy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "deploy"
    assert len(data["results"]) >= 1
    assert data["results"][0]["name"] == "mlops"


@patch("agent_gateway.routers.agents.get_embedding", return_value=None)
@patch("agent_gateway.routers.agents.list_agents")
async def test_search_agents_no_match_returns_empty(mock_list, mock_emb, client):
    mock_list.return_value = [
        _agent("mlops", "Deploy and monitor ML models", []),
    ]

    resp = await client.get("/agents/search?q=totally-unrelated-xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []


@patch("agent_gateway.routers.agents.cosine_similarity", return_value=0.85)
@patch("agent_gateway.routers.agents.get_embedding", return_value=[0.1, 0.2, 0.3])
@patch("agent_gateway.routers.agents.list_agents")
async def test_search_agents_with_embedding_scores(mock_list, mock_emb, mock_cos, client):
    mock_list.return_value = [
        _agent("mlops", "Deploy ML models to kubernetes", ["kubernetes-ops"]),
    ]

    resp = await client.get("/agents/search?q=deploy model")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["score"] > 0
    assert "skills" in data["results"][0]


@patch("agent_gateway.routers.agents.get_embedding", return_value=None)
@patch("agent_gateway.routers.agents.list_agents")
async def test_search_agents_embedding_fallback_keyword_only(mock_list, mock_emb, client):
    """When embedding unavailable, keyword-only scoring returns correct results."""
    mock_list.return_value = [
        _agent("platform-admin", "Manage cluster and platform", ["kubernetes-ops"]),
    ]

    resp = await client.get("/agents/search?q=cluster")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["name"] == "platform-admin"

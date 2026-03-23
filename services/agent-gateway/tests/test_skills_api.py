"""Tests for skills CRUD API endpoints."""

from unittest.mock import patch


from agent_gateway.models import MCPServerRef, SkillDefinition, TaskDefinition


@patch("agent_gateway.routers.skills.create_skill")
async def test_create_skill_endpoint(mock_create, client):
    mock_create.return_value = None

    resp = await client.post(
        "/skills",
        json={
            "name": "k8s-ops",
            "description": "K8s operations",
            "version": "1.0.0",
            "tags": ["infrastructure"],
            "mcp_servers": [{"url": "http://metamcp/genai/mcp", "tool_filter": ["kubectl_get"]}],
            "prompt_fragment": "Check state first.",
            "tasks": [{"name": "deploy-model", "description": "Deploy a model"}],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "k8s-ops"


@patch("agent_gateway.routers.skills.create_skill")
async def test_create_skill_conflict(mock_create, client):
    mock_create.side_effect = ValueError("Skill 'k8s-ops' already exists")

    resp = await client.post("/skills", json={"name": "k8s-ops"})
    assert resp.status_code == 409


@patch("agent_gateway.routers.skills.list_skills")
async def test_list_skills_endpoint(mock_list, client):
    mock_list.return_value = [
        SkillDefinition(name="k8s-ops", description="K8s", version="1.0.0"),
    ]

    resp = await client.get("/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["skills"]) == 1


@patch("agent_gateway.routers.skills.get_skill")
async def test_get_skill_endpoint(mock_get, client):
    mock_get.return_value = SkillDefinition(
        name="k8s-ops",
        description="K8s",
        version="1.0.0",
        mcp_servers=[MCPServerRef(url="http://metamcp/genai/mcp")],
        tasks=[TaskDefinition(name="deploy-model", description="Deploy")],
    )

    resp = await client.get("/skills/k8s-ops")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "k8s-ops"
    assert len(data["mcp_servers"]) == 1


@patch("agent_gateway.routers.skills.get_skill")
async def test_get_skill_not_found(mock_get, client):
    mock_get.side_effect = KeyError("not found")

    resp = await client.get("/skills/nonexistent")
    assert resp.status_code == 404


@patch("agent_gateway.routers.skills.delete_skill")
async def test_delete_skill_endpoint(mock_delete, client):
    mock_delete.return_value = None

    resp = await client.delete("/skills/k8s-ops")
    assert resp.status_code == 200


# --- Semantic search endpoint tests (D.02) ---


@patch("agent_gateway.routers.skills.get_embedding", return_value=None)
@patch("agent_gateway.routers.skills.list_skills")
async def test_search_skills_keyword_match(mock_list, mock_emb, client):
    mock_list.return_value = [
        SkillDefinition(name="kubernetes-ops", description="Manage k8s clusters", tags=["infra", "k8s"], version="1.0.0"),
        SkillDefinition(name="code-generation", description="Generate code from specs", tags=["dev"], version="1.0.0"),
    ]

    resp = await client.get("/skills/search?q=kubernetes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "kubernetes"
    assert len(data["results"]) >= 1
    assert data["results"][0]["name"] == "kubernetes-ops"


@patch("agent_gateway.routers.skills.get_embedding", return_value=None)
@patch("agent_gateway.routers.skills.list_skills")
async def test_search_skills_no_match_returns_empty(mock_list, mock_emb, client):
    mock_list.return_value = [
        SkillDefinition(name="kubernetes-ops", description="Manage k8s clusters", tags=["infra"], version="1.0.0"),
    ]

    resp = await client.get("/skills/search?q=totally-unrelated-xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []


@patch("agent_gateway.routers.skills.cosine_similarity", return_value=0.9)
@patch("agent_gateway.routers.skills.get_embedding", return_value=[0.1, 0.2, 0.3])
@patch("agent_gateway.routers.skills.list_skills")
async def test_search_skills_with_embedding_boosts_score(mock_list, mock_emb, mock_cos, client):
    mock_list.return_value = [
        SkillDefinition(name="kubernetes-ops", description="Manage k8s clusters", tags=["infra"], version="1.0.0"),
    ]

    resp = await client.get("/skills/search?q=kubernetes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    # With embedding enabled, score includes both keyword and similarity components
    assert data["results"][0]["score"] > 0


@patch("agent_gateway.routers.skills.get_embedding", return_value=None)
@patch("agent_gateway.routers.skills.list_skills")
async def test_search_skills_embedding_fallback_keyword_only(mock_list, mock_emb, client):
    """When get_embedding returns None, keyword-only scoring still works."""
    mock_list.return_value = [
        SkillDefinition(name="security-audit", description="Scan code for vulnerabilities", tags=["security"], version="1.0.0"),
    ]

    resp = await client.get("/skills/search?q=security")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["name"] == "security-audit"

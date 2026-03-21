"""Tests for gateway MCP server — exposes gateway REST API as MCP tools."""

from unittest.mock import patch

from agent_gateway.models import AgentDefinition, SkillDefinition


# ---------------------------------------------------------------------------
# tools/list — returns all exposed tools with descriptions + input schemas
# ---------------------------------------------------------------------------


async def test_mcp_tools_list(client):
    resp = await client.post(
        "/gateway-mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    tools = data["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    # Core agent + skill management tools must be present
    assert "list_agents" in tool_names
    assert "get_agent" in tool_names
    assert "list_skills" in tool_names
    assert "get_skill" in tool_names
    assert "create_skill" in tool_names
    assert "delete_skill" in tool_names


async def test_mcp_tools_list_schema(client):
    """Each tool must have a name, description, and inputSchema."""
    resp = await client.post(
        "/gateway-mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
    )
    data = resp.json()
    for tool in data["result"]["tools"]:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool


# ---------------------------------------------------------------------------
# tools/call — dispatches to gateway services
# ---------------------------------------------------------------------------


@patch("agent_gateway.mcp_server.list_agents")
async def test_call_list_agents(mock_list, client):
    mock_list.return_value = [
        AgentDefinition(name="mlops", description="MLops agent", runtime="n8n"),
    ]
    resp = await client.post(
        "/gateway-mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 3,
            "params": {"name": "list_agents", "arguments": {}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
    content = data["result"]["content"]
    assert len(content) > 0
    assert "mlops" in content[0]["text"]


@patch("agent_gateway.mcp_server.get_agent")
async def test_call_get_agent(mock_get, client):
    mock_get.return_value = AgentDefinition(name="mlops", description="MLops agent", runtime="n8n")
    resp = await client.post(
        "/gateway-mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 4,
            "params": {"name": "get_agent", "arguments": {"name": "mlops"}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
    content = data["result"]["content"]
    assert "mlops" in content[0]["text"]


@patch("agent_gateway.mcp_server.get_agent")
async def test_call_get_agent_not_found(mock_get, client):
    mock_get.side_effect = KeyError("nonexistent")
    resp = await client.post(
        "/gateway-mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 5,
            "params": {"name": "get_agent", "arguments": {"name": "nonexistent"}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # MCP errors come back in result.isError, not HTTP status
    assert data["result"]["isError"] is True


@patch("agent_gateway.mcp_server.list_skills")
async def test_call_list_skills(mock_list, client):
    mock_list.return_value = [
        SkillDefinition(name="kubernetes-ops", description="K8s operations"),
    ]
    resp = await client.post(
        "/gateway-mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 6,
            "params": {"name": "list_skills", "arguments": {}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "kubernetes-ops" in data["result"]["content"][0]["text"]


@patch("agent_gateway.mcp_server.get_skill")
async def test_call_get_skill(mock_get, client):
    mock_get.return_value = SkillDefinition(name="kubernetes-ops")
    resp = await client.post(
        "/gateway-mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 7,
            "params": {"name": "get_skill", "arguments": {"name": "kubernetes-ops"}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "kubernetes-ops" in data["result"]["content"][0]["text"]


@patch("agent_gateway.mcp_server.create_skill")
async def test_call_create_skill(mock_create, client):
    mock_create.return_value = None
    resp = await client.post(
        "/gateway-mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 8,
            "params": {
                "name": "create_skill",
                "arguments": {
                    "name": "new-skill",
                    "description": "A new skill",
                    "version": "1.0.0",
                    "tags": ["test"],
                    "prompt_fragment": "Do the thing.",
                },
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert not data["result"].get("isError")
    assert "new-skill" in data["result"]["content"][0]["text"]


@patch("agent_gateway.mcp_server.delete_skill")
async def test_call_delete_skill(mock_delete, client):
    mock_delete.return_value = None
    resp = await client.post(
        "/gateway-mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 9,
            "params": {"name": "delete_skill", "arguments": {"name": "old-skill"}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert not data["result"].get("isError")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_unknown_method(client):
    resp = await client.post(
        "/gateway-mcp",
        json={"jsonrpc": "2.0", "method": "unknown/method", "id": 99},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32601  # Method not found


async def test_unknown_tool(client):
    resp = await client.post(
        "/gateway-mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 10,
            "params": {"name": "nonexistent_tool", "arguments": {}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["isError"] is True


async def test_initialize(client):
    """MCP initialize handshake."""
    resp = await client.post(
        "/gateway-mcp",
        json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 0,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
    assert "protocolVersion" in data["result"]
    assert "capabilities" in data["result"]

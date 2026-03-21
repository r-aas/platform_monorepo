"""Tests for MCP tool auto-discovery.

C.02: Auto-discover namespaces from MetaMCP and index all tools.
Uses pytest-httpx to intercept httpx calls without real network.
"""

from unittest.mock import patch

import pytest
from pytest_httpx import HTTPXMock

ADMIN_URL = "http://genai-metamcp.genai.svc.cluster.local:12009"
PROXY_URL = "http://genai-metamcp.genai.svc.cluster.local:12008"
_AUTH_COOKIE = "better-auth.session_token=test-token-abc123"

_NAMESPACES_RESP = {
    "result": {
        "data": {
            "data": [
                {"name": "genai", "uuid": "ns-uuid-genai", "mcpServers": []},
                {"name": "platform", "uuid": "ns-uuid-platform", "mcpServers": []},
                {"name": "data", "uuid": "ns-uuid-data", "mcpServers": []},
            ]
        }
    }
}

_TOOLS_GENAI = {
    "result": {
        "tools": [
            {"name": "n8n_run_workflow", "description": "Execute an n8n workflow"},
            {"name": "mlflow_log_metric", "description": "Log a metric to MLflow"},
        ]
    }
}

_TOOLS_PLATFORM = {
    "result": {
        "tools": [
            {"name": "kubectl_get", "description": "Get k8s resources"},
        ]
    }
}

_TOOLS_DATA = {
    "result": {
        "tools": [
            {"name": "postgres_query", "description": "Run a SQL query"},
        ]
    }
}


@pytest.fixture(autouse=True)
def patch_discovery_settings():
    """Set credentials so discovery doesn't skip."""
    with (
        patch("agent_gateway.mcp_discovery.settings.metamcp_admin_url", ADMIN_URL),
        patch("agent_gateway.mcp_discovery.settings.metamcp_user_email", "admin@test.local"),
        patch("agent_gateway.mcp_discovery.settings.metamcp_user_password", "testpassword"),
    ):
        yield


# ---------------------------------------------------------------------------
# discover_namespaces()
# ---------------------------------------------------------------------------


async def test_discover_namespaces_from_metamcp(httpx_mock: HTTPXMock):
    """Fetches namespace names from MetaMCP admin tRPC API."""
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/api/auth/sign-in/email",
        method="POST",
        status_code=200,
        json={"token": "ok"},
        headers={"set-cookie": _AUTH_COOKIE},
    )
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/trpc/frontend/frontend.namespaces.list",
        method="GET",
        json=_NAMESPACES_RESP,
    )

    from agent_gateway.mcp_discovery import discover_namespaces

    namespaces = await discover_namespaces()

    assert namespaces == ["genai", "platform", "data"]


async def test_discover_namespaces_falls_back_when_no_credentials(httpx_mock: HTTPXMock):
    """Returns static fallback list when credentials not configured."""
    with patch("agent_gateway.mcp_discovery.settings.metamcp_user_email", ""):
        from agent_gateway.mcp_discovery import discover_namespaces

        namespaces = await discover_namespaces()

    assert namespaces == ["genai", "platform"]
    assert httpx_mock.get_requests() == []


async def test_discover_namespaces_falls_back_on_http_error(httpx_mock: HTTPXMock):
    """Returns static fallback list when MetaMCP is unreachable."""
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/api/auth/sign-in/email",
        method="POST",
        status_code=503,
        json={"error": "unavailable"},
    )

    from agent_gateway.mcp_discovery import discover_namespaces

    namespaces = await discover_namespaces()

    assert namespaces == ["genai", "platform"]


# ---------------------------------------------------------------------------
# fetch_tools_for_namespace()
# ---------------------------------------------------------------------------


async def test_fetch_tools_returns_tool_list(httpx_mock: HTTPXMock):
    """Fetches tools from MCP proxy for a given namespace."""
    httpx_mock.add_response(
        url=f"{PROXY_URL}/metamcp/genai/mcp",
        method="POST",
        json=_TOOLS_GENAI,
    )

    from agent_gateway.mcp_discovery import fetch_tools_for_namespace

    tools = await fetch_tools_for_namespace("genai")

    assert len(tools) == 2
    names = [t.name for t in tools]
    assert "n8n_run_workflow" in names
    assert "mlflow_log_metric" in names
    assert all(t.namespace == "genai" for t in tools)


async def test_fetch_tools_returns_empty_on_error(httpx_mock: HTTPXMock):
    """Returns empty list when MCP proxy is unreachable."""
    httpx_mock.add_response(
        url=f"{PROXY_URL}/metamcp/broken/mcp",
        method="POST",
        status_code=503,
        json={},
    )

    from agent_gateway.mcp_discovery import fetch_tools_for_namespace

    tools = await fetch_tools_for_namespace("broken")

    assert tools == []


# ---------------------------------------------------------------------------
# index_all_tools() + ToolIndex
# ---------------------------------------------------------------------------


async def test_index_all_tools_combines_namespaces_and_tools(httpx_mock: HTTPXMock):
    """Discovers namespaces then fetches tools from all of them."""
    # Auth + namespace discovery
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/api/auth/sign-in/email",
        method="POST",
        status_code=200,
        json={"token": "ok"},
        headers={"set-cookie": _AUTH_COOKIE},
    )
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/trpc/frontend/frontend.namespaces.list",
        method="GET",
        json={"result": {"data": {"data": [
            {"name": "genai", "uuid": "ns-genai"},
            {"name": "platform", "uuid": "ns-platform"},
        ]}}},
    )
    # Tool fetches per namespace
    httpx_mock.add_response(
        url=f"{PROXY_URL}/metamcp/genai/mcp",
        method="POST",
        json=_TOOLS_GENAI,
    )
    httpx_mock.add_response(
        url=f"{PROXY_URL}/metamcp/platform/mcp",
        method="POST",
        json=_TOOLS_PLATFORM,
    )

    from agent_gateway.mcp_discovery import index_all_tools

    idx = await index_all_tools()

    assert len(idx.tools) == 3  # 2 genai + 1 platform
    assert idx.namespaces == ["genai", "platform"]
    tool_names = [t.name for t in idx.tools]
    assert "n8n_run_workflow" in tool_names
    assert "kubectl_get" in tool_names


async def test_tool_index_is_non_fatal_on_discovery_error(httpx_mock: HTTPXMock):
    """index_all_tools() returns empty index when MetaMCP is down."""
    # Credentials present but MetaMCP auth fails → falls back to static namespaces
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/api/auth/sign-in/email",
        method="POST",
        status_code=503,
    )
    # Static fallback namespaces are ["genai", "platform"] — proxy also down
    httpx_mock.add_response(
        url=f"{PROXY_URL}/metamcp/genai/mcp",
        method="POST",
        status_code=503,
    )
    httpx_mock.add_response(
        url=f"{PROXY_URL}/metamcp/platform/mcp",
        method="POST",
        status_code=503,
    )

    from agent_gateway.mcp_discovery import index_all_tools

    idx = await index_all_tools()

    # Falls back to static namespaces + empty tool lists (proxy also down)
    assert isinstance(idx.namespaces, list)
    assert idx.tools == []


# ---------------------------------------------------------------------------
# Global state: get/set_tool_index
# ---------------------------------------------------------------------------


def test_get_tool_index_returns_none_initially():
    """Index is None until index_all_tools() has run."""
    import agent_gateway.mcp_discovery as disc

    # Reset to ensure clean state
    disc._tool_index = None

    from agent_gateway.mcp_discovery import get_tool_index

    assert get_tool_index() is None


async def test_set_and_get_tool_index(httpx_mock: HTTPXMock):
    """set_tool_index and get_tool_index round-trip the index."""
    import agent_gateway.mcp_discovery as disc
    from agent_gateway.mcp_discovery import DiscoveredTool, ToolIndex, get_tool_index, set_tool_index

    idx = ToolIndex(
        namespaces=["genai"],
        tools=[DiscoveredTool(name="test_tool", description="A test tool", namespace="genai")],
    )
    set_tool_index(idx)

    result = get_tool_index()
    assert result is idx
    assert len(result.tools) == 1
    assert result.tools[0].name == "test_tool"

    # Cleanup
    disc._tool_index = None

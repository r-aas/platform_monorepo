"""Tests for MCP tool auto-discovery via LiteLLM.

C.02: Discover MCP servers from LiteLLM and index all tools.
Uses pytest-httpx to intercept httpx calls without real network.
"""

import pytest
from pytest_httpx import HTTPXMock

LITELLM_URL = "http://genai-litellm.genai.svc.cluster.local:4000"

_SERVERS_RESP = [
    {"server_name": "kubernetes_ops", "url": "http://genai-mcp-kubernetes:3000/mcp"},
    {"server_name": "gitlab_ops", "url": "http://genai-mcp-gitlab:3000/mcp"},
    {"server_name": "n8n_workflow_ops", "url": "http://genai-mcp-n8n:3000/mcp"},
    {"server_name": "agent_gateway", "url": "http://genai-agent-gateway:8000/gateway-mcp"},
]

_TOOLS_RESP = {
    "tools": [
        {"name": "kubectl_get", "description": "Get k8s resources"},
        {"name": "kubectl_logs", "description": "Get pod logs"},
        {"name": "browse_projects", "description": "Browse GitLab projects"},
        {"name": "list_workflows", "description": "List n8n workflows"},
    ]
}


# ---------------------------------------------------------------------------
# discover_namespaces()
# ---------------------------------------------------------------------------


async def test_discover_namespaces_from_litellm(httpx_mock: HTTPXMock):
    """Fetches MCP server names from LiteLLM /v1/mcp/server."""
    httpx_mock.add_response(
        url=f"{LITELLM_URL}/v1/mcp/server",
        method="GET",
        json=_SERVERS_RESP,
    )

    from agent_gateway.mcp_discovery import discover_namespaces

    namespaces = await discover_namespaces()

    assert namespaces == ["kubernetes_ops", "gitlab_ops", "n8n_workflow_ops", "agent_gateway"]


async def test_discover_namespaces_falls_back_on_http_error(httpx_mock: HTTPXMock):
    """Returns empty list when LiteLLM is unreachable."""
    httpx_mock.add_response(
        url=f"{LITELLM_URL}/v1/mcp/server",
        method="GET",
        status_code=503,
    )

    from agent_gateway.mcp_discovery import discover_namespaces

    namespaces = await discover_namespaces()

    assert namespaces == []


# ---------------------------------------------------------------------------
# fetch_all_tools()
# ---------------------------------------------------------------------------


async def test_fetch_all_tools_returns_tool_list(httpx_mock: HTTPXMock):
    """Fetches all tools from LiteLLM /mcp-rest/tools/list."""
    httpx_mock.add_response(
        url=f"{LITELLM_URL}/mcp-rest/tools/list",
        method="GET",
        json=_TOOLS_RESP,
    )

    from agent_gateway.mcp_discovery import fetch_all_tools

    tools = await fetch_all_tools()

    assert len(tools) == 4
    names = [t.name for t in tools]
    assert "kubectl_get" in names
    assert "browse_projects" in names
    assert all(t.namespace == "litellm" for t in tools)


async def test_fetch_all_tools_returns_empty_on_error(httpx_mock: HTTPXMock):
    """Returns empty list when LiteLLM MCP endpoint is unreachable."""
    httpx_mock.add_response(
        url=f"{LITELLM_URL}/mcp-rest/tools/list",
        method="GET",
        status_code=503,
    )

    from agent_gateway.mcp_discovery import fetch_all_tools

    tools = await fetch_all_tools()

    assert tools == []


# ---------------------------------------------------------------------------
# index_all_tools() + ToolIndex
# ---------------------------------------------------------------------------


async def test_index_all_tools_combines_servers_and_tools(httpx_mock: HTTPXMock):
    """Discovers servers then fetches all tools, builds ToolIndex."""
    httpx_mock.add_response(
        url=f"{LITELLM_URL}/v1/mcp/server",
        method="GET",
        json=_SERVERS_RESP,
    )
    httpx_mock.add_response(
        url=f"{LITELLM_URL}/mcp-rest/tools/list",
        method="GET",
        json=_TOOLS_RESP,
    )

    from agent_gateway.mcp_discovery import index_all_tools

    idx = await index_all_tools()

    assert len(idx.tools) == 4
    assert len(idx.namespaces) == 4
    tool_names = [t.name for t in idx.tools]
    assert "kubectl_get" in tool_names
    assert "browse_projects" in tool_names


async def test_index_all_tools_non_fatal_on_error(httpx_mock: HTTPXMock):
    """index_all_tools() returns empty index when LiteLLM is down."""
    httpx_mock.add_response(
        url=f"{LITELLM_URL}/v1/mcp/server",
        method="GET",
        status_code=503,
    )
    httpx_mock.add_response(
        url=f"{LITELLM_URL}/mcp-rest/tools/list",
        method="GET",
        status_code=503,
    )

    from agent_gateway.mcp_discovery import index_all_tools

    idx = await index_all_tools()

    assert isinstance(idx.namespaces, list)
    assert idx.tools == []


# ---------------------------------------------------------------------------
# Global state: get/set_tool_index
# ---------------------------------------------------------------------------


def test_get_tool_index_returns_none_initially():
    """Index is None until index_all_tools() has run."""
    import agent_gateway.mcp_discovery as disc

    disc._tool_index = None

    from agent_gateway.mcp_discovery import get_tool_index

    assert get_tool_index() is None


def test_set_and_get_tool_index():
    """set_tool_index and get_tool_index round-trip the index."""
    import agent_gateway.mcp_discovery as disc
    from agent_gateway.mcp_discovery import DiscoveredTool, ToolIndex, get_tool_index, set_tool_index

    idx = ToolIndex(
        namespaces=["kubernetes_ops"],
        tools=[DiscoveredTool(name="kubectl_get", description="Get k8s resources", namespace="litellm")],
    )
    set_tool_index(idx)

    result = get_tool_index()
    assert result is idx
    assert len(result.tools) == 1
    assert result.tools[0].name == "kubectl_get"

    disc._tool_index = None

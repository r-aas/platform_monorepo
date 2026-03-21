"""Tests for MetaMCP registration client.

C.01: Gateway MCP server registration in MetaMCP.
Uses pytest-httpx to intercept httpx calls without real network.
"""

from unittest.mock import patch

import pytest
from pytest_httpx import HTTPXMock

# tRPC response shape from MetaMCP seed.py
_AUTH_COOKIE = "better-auth.session_token=test-token-abc123"

_SERVERS_EMPTY = {"result": {"data": {"data": []}}}
_SERVERS_WITH_GATEWAY = {
    "result": {"data": {"data": [{"name": "agent-gateway", "uuid": "srv-uuid-123"}]}}
}
_SERVER_CREATED = {"result": {"data": {"data": {"uuid": "srv-uuid-new"}}}}
_SERVER_UPDATED = {"result": {"data": {"data": {"uuid": "srv-uuid-123"}}}}
_NAMESPACES = {
    "result": {
        "data": {
            "data": [
                {"name": "genai", "uuid": "ns-uuid-genai", "mcpServers": []},
                {"name": "platform", "uuid": "ns-uuid-platform", "mcpServers": []},
            ]
        }
    }
}
_NS_UPDATED = {"result": {"data": {"data": {"uuid": "ns-uuid-genai"}}}}

ADMIN_URL = "http://genai-metamcp.genai.svc.cluster.local:12009"


@pytest.fixture(autouse=True)
def patch_settings():
    """Set credentials so tests don't skip registration."""
    with (
        patch("agent_gateway.metamcp_client.settings.metamcp_admin_url", ADMIN_URL),
        patch("agent_gateway.metamcp_client.settings.metamcp_user_email", "admin@test.local"),
        patch("agent_gateway.metamcp_client.settings.metamcp_user_password", "testpassword"),
        patch("agent_gateway.metamcp_client.settings.metamcp_namespace", "genai"),
        patch("agent_gateway.metamcp_client.settings.gateway_mcp_name", "agent-gateway"),
        patch(
            "agent_gateway.metamcp_client.settings.gateway_mcp_url",
            "http://genai-agent-gateway.genai.svc.cluster.local:8000/gateway-mcp",
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Skip when not configured
# ---------------------------------------------------------------------------


async def test_register_skips_when_no_email(httpx_mock: HTTPXMock):
    """Returns False immediately when credentials not configured."""
    with patch("agent_gateway.metamcp_client.settings.metamcp_user_email", ""):
        from agent_gateway.metamcp_client import register_gateway_server

        result = await register_gateway_server()

    assert result is False
    # No HTTP calls should have been made
    assert httpx_mock.get_requests() == []


async def test_register_skips_when_no_password(httpx_mock: HTTPXMock):
    """Returns False immediately when password not configured."""
    with patch("agent_gateway.metamcp_client.settings.metamcp_user_password", ""):
        from agent_gateway.metamcp_client import register_gateway_server

        result = await register_gateway_server()

    assert result is False
    assert httpx_mock.get_requests() == []


# ---------------------------------------------------------------------------
# Happy path — new server
# ---------------------------------------------------------------------------


async def test_register_creates_new_server(httpx_mock: HTTPXMock):
    """Creates server + assigns to namespace when gateway not registered yet."""
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/api/auth/sign-in/email",
        method="POST",
        status_code=200,
        json={"token": "ok"},
        headers={"set-cookie": _AUTH_COOKIE},
    )
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/trpc/frontend/frontend.mcpServers.list",
        method="GET",
        json=_SERVERS_EMPTY,
    )
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/trpc/frontend/frontend.mcpServers.create",
        method="POST",
        json=_SERVER_CREATED,
    )
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/trpc/frontend/frontend.namespaces.list",
        method="GET",
        json=_NAMESPACES,
    )
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/trpc/frontend/frontend.namespaces.update",
        method="POST",
        json=_NS_UPDATED,
    )

    from agent_gateway.metamcp_client import register_gateway_server

    result = await register_gateway_server()

    assert result is True
    requests = httpx_mock.get_requests()
    assert len(requests) == 5  # sign-in, list servers, create, list ns, update ns


# ---------------------------------------------------------------------------
# Happy path — existing server (update)
# ---------------------------------------------------------------------------


async def test_register_updates_existing_server(httpx_mock: HTTPXMock):
    """Updates server config when gateway is already registered."""
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/api/auth/sign-in/email",
        method="POST",
        status_code=200,
        json={"token": "ok"},
        headers={"set-cookie": _AUTH_COOKIE},
    )
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/trpc/frontend/frontend.mcpServers.list",
        method="GET",
        json=_SERVERS_WITH_GATEWAY,
    )
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/trpc/frontend/frontend.mcpServers.update",
        method="POST",
        json=_SERVER_UPDATED,
    )
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/trpc/frontend/frontend.namespaces.list",
        method="GET",
        json=_NAMESPACES,
    )
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/trpc/frontend/frontend.namespaces.update",
        method="POST",
        json=_NS_UPDATED,
    )

    from agent_gateway.metamcp_client import register_gateway_server

    result = await register_gateway_server()

    assert result is True
    requests = httpx_mock.get_requests()
    assert len(requests) == 5  # sign-in, list servers, update, list ns, update ns


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_register_returns_false_on_auth_error(httpx_mock: HTTPXMock):
    """Returns False when MetaMCP auth fails."""
    httpx_mock.add_response(
        url=f"{ADMIN_URL}/api/auth/sign-in/email",
        method="POST",
        status_code=401,
        json={"error": "Invalid credentials"},
    )

    from agent_gateway.metamcp_client import register_gateway_server

    result = await register_gateway_server()

    assert result is False

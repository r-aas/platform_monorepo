"""Tests for MetaMCP namespace registry — C.04 data namespace registration."""

from pathlib import Path

import pytest
import yaml

from agent_gateway.namespace_registry import NamespaceMCPServer, load_namespace_config, register_namespace_servers

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "namespace": "data",
    "servers": [
        {
            "name": "postgres-mcp",
            "description": "PostgreSQL operations",
            "url": "http://genai-postgres-mcp.genai.svc.cluster.local:8080/mcp",
            "type": "streamable-http",
        },
        {
            "name": "files-mcp",
            "description": "File read/write for data pipelines",
            "url": "http://genai-files-mcp.genai.svc.cluster.local:8080/mcp",
            "type": "streamable-http",
        },
    ],
}


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "data.yaml"
    path.write_text(yaml.dump(SAMPLE_CONFIG))
    return path


# ---------------------------------------------------------------------------
# load_namespace_config tests (pure, no I/O beyond file read)
# ---------------------------------------------------------------------------


def test_load_namespace_config_returns_servers(config_file: Path):
    servers = load_namespace_config(config_file)
    assert len(servers) == 2


def test_load_namespace_config_parses_name(config_file: Path):
    servers = load_namespace_config(config_file)
    assert servers[0].name == "postgres-mcp"


def test_load_namespace_config_parses_url(config_file: Path):
    servers = load_namespace_config(config_file)
    assert "postgres-mcp" in servers[0].url


def test_load_namespace_config_parses_type(config_file: Path):
    servers = load_namespace_config(config_file)
    assert servers[0].type == "streamable-http"


def test_load_namespace_config_missing_file_returns_empty():
    servers = load_namespace_config(Path("/nonexistent/data.yaml"))
    assert servers == []


def test_load_namespace_config_default_type(tmp_path: Path):
    """type field is optional — defaults to streamable-http."""
    cfg = {"namespace": "test", "servers": [{"name": "s1", "description": "d", "url": "http://x"}]}
    path = tmp_path / "test.yaml"
    path.write_text(yaml.dump(cfg))
    servers = load_namespace_config(path)
    assert servers[0].type == "streamable-http"


# ---------------------------------------------------------------------------
# data.yaml existence test
# ---------------------------------------------------------------------------


def test_data_namespace_config_exists():
    """Verify the committed data.yaml config exists in the service directory."""
    # namespaces/ directory is one level above src/ in the service root
    config_path = Path(__file__).parents[1] / "namespaces" / "data.yaml"
    assert config_path.exists(), f"Missing {config_path}"
    servers = load_namespace_config(config_path)
    assert len(servers) >= 1


# ---------------------------------------------------------------------------
# register_namespace_servers tests (async, uses httpx_mock)
# ---------------------------------------------------------------------------


async def test_register_returns_false_without_credentials(monkeypatch):
    """No MetaMCP credentials → skip, return False."""
    monkeypatch.setattr("agent_gateway.namespace_registry.settings.metamcp_user_email", "")
    servers = [NamespaceMCPServer(name="s", description="d", url="http://x")]
    result = await register_namespace_servers("data", servers)
    assert result is False


async def test_register_returns_false_on_http_error(monkeypatch, httpx_mock):
    """HTTP error → non-fatal, return False."""
    monkeypatch.setattr("agent_gateway.namespace_registry.settings.metamcp_user_email", "admin@example.com")
    monkeypatch.setattr("agent_gateway.namespace_registry.settings.metamcp_user_password", "pass")
    monkeypatch.setattr(
        "agent_gateway.namespace_registry.settings.metamcp_admin_url",
        "http://metamcp-test:12009",
    )
    httpx_mock.add_response(
        url="http://metamcp-test:12009/api/auth/sign-in/email",
        status_code=500,
    )
    servers = [NamespaceMCPServer(name="s", description="d", url="http://x")]
    result = await register_namespace_servers("data", servers)
    assert result is False


async def test_register_creates_servers_and_assigns_namespace(monkeypatch, httpx_mock):
    """Full happy path: sign-in → create server → assign to namespace."""
    monkeypatch.setattr("agent_gateway.namespace_registry.settings.metamcp_user_email", "admin@example.com")
    monkeypatch.setattr("agent_gateway.namespace_registry.settings.metamcp_user_password", "pass")
    monkeypatch.setattr(
        "agent_gateway.namespace_registry.settings.metamcp_admin_url",
        "http://metamcp-test:12009",
    )

    # Auth
    httpx_mock.add_response(
        url="http://metamcp-test:12009/api/auth/sign-in/email",
        status_code=200,
        json={},
        headers={"set-cookie": "better-auth.session_token=tok123; Path=/"},
    )
    # List servers — none exist
    httpx_mock.add_response(
        url="http://metamcp-test:12009/trpc/frontend/frontend.mcpServers.list",
        method="GET",
        json={"result": {"data": {"data": []}}},
    )
    # Create server
    httpx_mock.add_response(
        url="http://metamcp-test:12009/trpc/frontend/frontend.mcpServers.create",
        method="POST",
        json={"result": {"data": {"data": {"uuid": "uuid-001"}}}},
    )
    # List namespaces — data namespace exists
    httpx_mock.add_response(
        url="http://metamcp-test:12009/trpc/frontend/frontend.namespaces.list",
        method="GET",
        json={"result": {"data": {"data": [{"name": "data", "uuid": "ns-001", "mcpServers": []}]}}},
    )
    # Update namespace
    httpx_mock.add_response(
        url="http://metamcp-test:12009/trpc/frontend/frontend.namespaces.update",
        method="POST",
        json={"result": {"data": {"data": {}}}},
    )

    servers = [NamespaceMCPServer(name="postgres-mcp", description="PG ops", url="http://pg/mcp")]
    result = await register_namespace_servers("data", servers)
    assert result is True

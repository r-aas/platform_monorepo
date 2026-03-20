"""MetaMCP Admin MCP Server — CRUD servers, manage namespaces/endpoints, pod ops."""

import json
import os
import subprocess
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("metamcp-admin")

METAMCP_URL = os.environ.get("METAMCP_URL", "http://metamcp.genai.127.0.0.1.nip.io")
METAMCP_EMAIL = os.environ.get("METAMCP_EMAIL", "admin@metamcp.local")
METAMCP_PASSWORD = os.environ.get("METAMCP_PASSWORD", "changeme")
METAMCP_NAMESPACE = os.environ.get("METAMCP_K8S_NAMESPACE", "genai")
METAMCP_LABEL = os.environ.get("METAMCP_LABEL", "app.kubernetes.io/name=metamcp")

_session_cookie: str | None = None


async def _get_client() -> httpx.AsyncClient:
    global _session_cookie
    client = httpx.AsyncClient(base_url=METAMCP_URL, timeout=15)
    if not _session_cookie:
        # Try sign-in first, fall back to sign-up
        r = await client.post(
            "/api/auth/sign-in/email",
            json={"email": METAMCP_EMAIL, "password": METAMCP_PASSWORD},
        )
        if r.status_code != 200:
            r = await client.post(
                "/api/auth/sign-up/email",
                json={"email": METAMCP_EMAIL, "password": METAMCP_PASSWORD, "name": "admin"},
            )
        cookie = r.cookies.get("better-auth.session_token")
        if not cookie:
            for h in r.headers.get_list("set-cookie"):
                if "better-auth.session_token=" in h:
                    cookie = h.split("better-auth.session_token=")[1].split(";")[0]
                    break
        if not cookie:
            raise RuntimeError(f"Auth failed: {r.status_code} {r.text[:200]}")
        _session_cookie = cookie
    client.cookies.set("better-auth.session_token", _session_cookie)
    return client


async def _trpc(method: str, input_data: dict | None = None) -> Any:
    client = await _get_client()
    path = f"/trpc/frontend/frontend.{method}"
    if input_data is not None:
        r = await client.post(path, json=input_data)
    else:
        r = await client.get(path)
    await client.aclose()
    if r.status_code != 200:
        return {"error": r.status_code, "detail": r.text[:500]}
    data = r.json()
    return data.get("result", {}).get("data", data)


def _kubectl(*args: str) -> str:
    try:
        result = subprocess.run(
            ["kubectl", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout or result.stderr
    except Exception as e:
        return f"Error: {e}"


# ── Server CRUD ──────────────────────────────────────────────


@mcp.tool()
async def list_servers() -> str:
    """List all MCP servers configured in MetaMCP."""
    data = await _trpc("mcpServers.list")
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data)
    servers = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(servers, list):
        rows = []
        for s in servers:
            rows.append(
                {
                    "uuid": s.get("uuid"),
                    "name": s.get("name"),
                    "type": s.get("type"),
                    "command": s.get("command"),
                    "args": s.get("args"),
                    "url": s.get("url"),
                    "description": s.get("description", ""),
                }
            )
        return json.dumps(rows, indent=2)
    return json.dumps(servers, indent=2, default=str)


@mcp.tool()
async def create_server(
    name: str,
    type: str,
    description: str = "",
    command: str = "",
    args: str = "",
    url: str = "",
    env: str = "{}",
    headers: str = "{}",
) -> str:
    """Create a new MCP server in MetaMCP.

    Args:
        name: Server name (e.g. 'github', 'slack')
        type: STDIO, SSE, or STREAMABLE_HTTP
        description: Human-readable description
        command: For STDIO: command to run (e.g. 'uvx', 'npx')
        args: For STDIO: comma-separated args (e.g. 'mcp-server-github')
        url: For SSE/HTTP: server URL
        env: JSON string of env vars (e.g. '{"GITHUB_TOKEN": "xxx"}')
        headers: JSON string of HTTP headers
    """
    payload = {
        "name": name,
        "type": type,
        "description": description,
        "command": command if type == "STDIO" else "",
        "args": args.split(",") if args and type == "STDIO" else [],
        "url": url if type != "STDIO" else "",
        "env": json.loads(env) if env else {},
        "headers": json.loads(headers) if headers else {},
        "bearerToken": "",
    }
    result = await _trpc("mcpServers.create", payload)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def update_server(
    uuid: str,
    name: str = "",
    description: str = "",
    command: str = "",
    args: str = "",
    url: str = "",
    env: str = "",
    type: str = "",
) -> str:
    """Update an existing MCP server. Only provided fields are changed.

    Args:
        uuid: Server UUID (from list_servers)
        name: New name
        description: New description
        command: New command (STDIO)
        args: New comma-separated args (STDIO)
        url: New URL (SSE/HTTP)
        env: JSON string of new env vars
        type: New type (STDIO, SSE, STREAMABLE_HTTP)
    """
    payload: dict[str, Any] = {"uuid": uuid}
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description
    if command:
        payload["command"] = command
    if args:
        payload["args"] = args.split(",")
    if url:
        payload["url"] = url
    if env:
        payload["env"] = json.loads(env)
    if type:
        payload["type"] = type
    result = await _trpc("mcpServers.update", payload)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def delete_server(uuid: str) -> str:
    """Delete an MCP server by UUID.

    Args:
        uuid: Server UUID (from list_servers)
    """
    result = await _trpc("mcpServers.delete", {"uuid": uuid})
    return json.dumps(result, indent=2, default=str)


# ── Namespaces & Endpoints ───────────────────────────────────


@mcp.tool()
async def list_namespaces() -> str:
    """List all MetaMCP namespaces and their assigned servers."""
    data = await _trpc("namespaces.list")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def list_endpoints() -> str:
    """List all MetaMCP endpoints (MCP protocol entry points)."""
    data = await _trpc("endpoints.list")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def update_namespace_servers(
    namespace_uuid: str, namespace_name: str, server_uuids: str
) -> str:
    """Set which MCP servers are assigned to a namespace (replaces all current assignments).

    Args:
        namespace_uuid: Namespace UUID (from list_namespaces)
        namespace_name: Namespace name (required by API)
        server_uuids: Comma-separated server UUIDs to assign
    """
    uuids = [u.strip() for u in server_uuids.split(",") if u.strip()]
    result = await _trpc(
        "namespaces.update",
        {"uuid": namespace_uuid, "name": namespace_name, "mcpServerUuids": uuids},
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def assign_server_to_namespace(server_uuid: str, namespace_uuid: str) -> str:
    """Assign an MCP server to a namespace so it appears on that namespace's endpoint.

    Args:
        server_uuid: Server UUID (from list_servers)
        namespace_uuid: Namespace UUID (from list_namespaces)
    """
    # Get current namespace to find name and existing server assignments
    ns_data = await _trpc("namespaces.list")
    ns_list = ns_data.get("data", ns_data) if isinstance(ns_data, dict) else ns_data
    target = None
    if isinstance(ns_list, list):
        target = next((n for n in ns_list if n.get("uuid") == namespace_uuid), None)
    if not target:
        return json.dumps({"error": f"Namespace {namespace_uuid} not found"})

    current_uuids = [s.get("uuid") for s in target.get("mcpServers", [])]
    if server_uuid in current_uuids:
        return json.dumps({"status": "already_assigned"})
    current_uuids.append(server_uuid)

    result = await _trpc(
        "namespaces.update",
        {"uuid": namespace_uuid, "name": target["name"], "mcpServerUuids": current_uuids},
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def unassign_server_from_namespace(server_uuid: str, namespace_uuid: str) -> str:
    """Remove an MCP server from a namespace.

    Args:
        server_uuid: Server UUID (from list_servers)
        namespace_uuid: Namespace UUID (from list_namespaces)
    """
    ns_data = await _trpc("namespaces.list")
    ns_list = ns_data.get("data", ns_data) if isinstance(ns_data, dict) else ns_data
    target = None
    if isinstance(ns_list, list):
        target = next((n for n in ns_list if n.get("uuid") == namespace_uuid), None)
    if not target:
        return json.dumps({"error": f"Namespace {namespace_uuid} not found"})

    current_uuids = [s.get("uuid") for s in target.get("mcpServers", []) if s.get("uuid") != server_uuid]

    result = await _trpc(
        "namespaces.update",
        {"uuid": namespace_uuid, "name": target["name"], "mcpServerUuids": current_uuids},
    )
    return json.dumps(result, indent=2, default=str)


# ── Pod Operations ───────────────────────────────────────────


@mcp.tool()
async def pod_status() -> str:
    """Get MetaMCP pod status in k8s."""
    return _kubectl(
        "get", "pods", "-n", METAMCP_NAMESPACE,
        "-l", METAMCP_LABEL,
        "-o", "wide",
    )


@mcp.tool()
async def pod_logs(lines: int = 100, previous: bool = False) -> str:
    """Get MetaMCP pod logs.

    Args:
        lines: Number of log lines to return (default 100)
        previous: If True, get logs from previous (crashed) container
    """
    cmd = [
        "logs", "-n", METAMCP_NAMESPACE,
        "-l", METAMCP_LABEL,
        f"--tail={lines}",
    ]
    if previous:
        cmd.append("--previous")
    return _kubectl(*cmd)


@mcp.tool()
async def pod_restart() -> str:
    """Restart MetaMCP by rolling restart of the deployment."""
    return _kubectl(
        "rollout", "restart", "deployment",
        "-n", METAMCP_NAMESPACE,
        "-l", METAMCP_LABEL,
    )


@mcp.tool()
async def pod_events() -> str:
    """Get recent k8s events for MetaMCP in the genai namespace."""
    return _kubectl(
        "get", "events", "-n", METAMCP_NAMESPACE,
        "--sort-by=.lastTimestamp",
    )


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

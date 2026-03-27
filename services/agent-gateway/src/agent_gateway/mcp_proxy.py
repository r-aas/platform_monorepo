"""MCP proxy — aggregates tools from registered backend MCP servers.

Reads MCP server endpoints from the DB, fetches tools/list from each,
caches results, and routes tools/call to the correct backend by tool name.

Handles Streamable HTTP backends that return SSE-wrapped JSON-RPC responses,
per-server auth tokens, and session management.

Tool names are prefixed as {server}.{tool} to avoid collisions.
Namespace-scoped filtering is supported — clients can request tools from
a specific namespace (e.g., "platform" → kubernetes + gitlab tools only).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

import httpx

from agent_gateway.store.mcp_servers import list_mcp_servers, update_server_health

logger = logging.getLogger(__name__)

# Tool name separator — {server}{SEP}{tool}
TOOL_SEP = "."


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class CachedTool:
    name: str  # original tool name from backend
    prefixed_name: str  # {server}.{name}
    description: str
    input_schema: dict
    server_name: str
    server_url: str
    namespace: str


@dataclass
class ServerSession:
    """Tracks session state for a backend MCP server."""

    session_id: str = ""
    initialized: bool = False


@dataclass
class ServerMeta:
    """Cached server metadata for auth/namespace lookups."""

    name: str
    url: str
    namespace: str
    auth_token: str


@dataclass
class ProxyState:
    """In-memory cache of aggregated tools from all backend MCP servers."""

    tools: list[CachedTool] = field(default_factory=list)
    # Maps prefixed name → CachedTool
    tool_map: dict[str, CachedTool] = field(default_factory=dict)
    # Maps namespace → list of server names
    namespace_map: dict[str, list[str]] = field(default_factory=dict)
    # Server metadata cache
    server_meta: dict[str, ServerMeta] = field(default_factory=dict)
    sessions: dict[str, ServerSession] = field(default_factory=dict)
    last_refresh: float = 0.0
    refresh_interval: float = 300.0  # 5 minutes


_state = ProxyState()

# Persistent HTTP client — reuses connections across requests
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return a persistent httpx.AsyncClient, creating it on first use."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _http_client


async def close_http_client() -> None:
    """Close the persistent HTTP client (call on shutdown)."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def get_proxy_state() -> ProxyState:
    return _state


def get_namespaces() -> dict[str, list[str]]:
    """Return namespace → server names mapping."""
    return dict(_state.namespace_map)


# ---------------------------------------------------------------------------
# SSE response parsing
# ---------------------------------------------------------------------------


def _parse_sse_response(text: str) -> dict | None:
    """Parse SSE-wrapped JSON-RPC response.

    Backends return responses like:
        event: message
        data: {"result": {...}, "jsonrpc": "2.0", "id": 1}
    """
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                continue
    return None


def _parse_response(resp: httpx.Response) -> dict:
    """Parse a response that may be plain JSON or SSE-wrapped."""
    content_type = resp.headers.get("content-type", "")
    text = resp.text

    if "text/event-stream" in content_type:
        parsed = _parse_sse_response(text)
        if parsed is not None:
            return parsed
        logger.warning("Failed to parse SSE response: %s", text[:200])
        return {}

    try:
        return resp.json()
    except Exception:
        parsed = _parse_sse_response(text)
        if parsed is not None:
            return parsed
        return {}


# ---------------------------------------------------------------------------
# Backend communication
# ---------------------------------------------------------------------------


def _build_headers(auth_token: str = "", session_id: str = "") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


async def _initialize_server(
    name: str, url: str, auth_token: str = "", timeout: float = 10.0
) -> ServerSession:
    """Send initialize request to a backend and capture session ID."""
    payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agent-gateway-proxy", "version": "0.1.0"},
        },
    }
    headers = _build_headers(auth_token=auth_token)
    session = ServerSession()

    try:
        client = _get_http_client()
        resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        sid = resp.headers.get("mcp-session-id", "")
        if sid:
            session.session_id = sid
        session.initialized = True
        logger.info("Initialized MCP session with %s (session_id=%s)", name, sid or "none")
    except Exception as e:
        logger.warning("Failed to initialize session with %s: %s", name, e)

    _state.sessions[name] = session
    return session


async def _fetch_tools_from_server(
    name: str, url: str, auth_token: str = "", timeout: float = 10.0
) -> list[dict]:
    """Send initialize (if needed) + tools/list to a backend MCP server."""
    session = _state.sessions.get(name)
    if session is None or not session.initialized:
        session = await _initialize_server(name, url, auth_token, timeout)

    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    headers = _build_headers(auth_token=auth_token, session_id=session.session_id)

    try:
        client = _get_http_client()
        resp = await client.post(url, json=payload, headers=headers, timeout=timeout)

        # Session expired or invalid — re-initialize and retry
        if resp.status_code in (400, 401, 404):
            logger.info("Got %d from %s — re-initializing session", resp.status_code, name)
            session = await _initialize_server(name, url, auth_token, timeout)
            headers = _build_headers(auth_token=auth_token, session_id=session.session_id)
            resp = await client.post(url, json=payload, headers=headers, timeout=timeout)

        resp.raise_for_status()
        data = _parse_response(resp)

        if "error" in data and "session" in str(data.get("error", {}).get("message", "")).lower():
            session = await _initialize_server(name, url, auth_token, timeout)
            headers = _build_headers(auth_token=auth_token, session_id=session.session_id)
            resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = _parse_response(resp)

        result = data.get("result", {})
        tools = result.get("tools", [])
        await update_server_health(name, "healthy", [t.get("name", "") for t in tools])
        return tools
    except Exception as e:
        logger.warning("Failed to fetch tools from %s (%s): %s", name, url, e)
        try:
            await update_server_health(name, "unhealthy", [])
        except Exception:
            pass
        return []


async def _call_backend_tool(
    server_name: str, server_url: str, tool_name: str, arguments: dict,
    auth_token: str = "", req_id: int | str = 1
) -> dict:
    """Forward a tools/call JSON-RPC request to a backend MCP server."""
    session = _state.sessions.get(server_name, ServerSession())
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    headers = _build_headers(auth_token=auth_token, session_id=session.session_id)

    client = _get_http_client()
    resp = await client.post(server_url, json=payload, headers=headers, timeout=60.0)

    # Session expired — re-initialize and retry
    if resp.status_code in (400, 401, 404):
        session = await _initialize_server(server_name, server_url, auth_token)
        headers = _build_headers(auth_token=auth_token, session_id=session.session_id)
        resp = await client.post(server_url, json=payload, headers=headers, timeout=60.0)

    resp.raise_for_status()
    data = _parse_response(resp)
    if "error" in data:
        return {"content": [{"type": "text", "text": data["error"].get("message", "Backend error")}], "isError": True}
    return data.get("result", {})


# ---------------------------------------------------------------------------
# Refresh / cache
# ---------------------------------------------------------------------------


async def refresh_tools(force: bool = False) -> int:
    """Refresh the aggregated tool cache from all registered MCP servers."""
    now = time.monotonic()
    if not force and _state.last_refresh > 0 and (now - _state.last_refresh) < _state.refresh_interval:
        return len(_state.tools)

    rows = await list_mcp_servers()
    all_tools: list[CachedTool] = []
    tool_map: dict[str, CachedTool] = {}
    namespace_map: dict[str, list[str]] = {}
    server_meta: dict[str, ServerMeta] = {}

    # Build namespace map and server metadata
    for row in rows:
        ns = row.namespace or "default"
        namespace_map.setdefault(ns, []).append(row.name)
        server_meta[row.name] = ServerMeta(
            name=row.name, url=row.url, namespace=ns, auth_token=row.auth_token or "",
        )

    tasks = [
        _fetch_tools_from_server(row.name, row.url, auth_token=row.auth_token or "")
        for row in rows
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for row, result in zip(rows, results):
        if isinstance(result, Exception):
            logger.warning("Exception fetching tools from %s: %s", row.name, result)
            continue
        ns = row.namespace or "default"
        for t in result:
            name = t.get("name", "")
            if not name:
                continue
            if t.get("inputSchema") is None:
                logger.debug("Skipping tool %s from %s — nil inputSchema", name, row.name)
                continue
            prefixed = f"{row.name}{TOOL_SEP}{name}"
            cached = CachedTool(
                name=name,
                prefixed_name=prefixed,
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=row.name,
                server_url=row.url,
                namespace=ns,
            )
            # Prefixed names are unique by construction
            tool_map[prefixed] = cached
            all_tools.append(cached)

    _state.tools = all_tools
    _state.tool_map = tool_map
    _state.namespace_map = namespace_map
    _state.server_meta = server_meta
    _state.last_refresh = now

    ns_summary = {ns: len(srvs) for ns, srvs in namespace_map.items()}
    logger.info("MCP proxy refreshed: %d tools from %d servers, namespaces=%s",
                len(all_tools), len(rows), ns_summary)
    return len(all_tools)


async def refresh_single_server(server_name: str) -> int:
    """Re-fetch tools from a single backend and update the cache."""
    rows = await list_mcp_servers()
    target = next((r for r in rows if r.name == server_name), None)
    if target is None:
        raise KeyError(f"MCP server '{server_name}' not found")

    _state.sessions.pop(server_name, None)
    tools = await _fetch_tools_from_server(target.name, target.url, auth_token=target.auth_token or "")

    ns = target.namespace or "default"
    _state.tools = [t for t in _state.tools if t.server_name != server_name]
    _state.tool_map = {k: v for k, v in _state.tool_map.items() if v.server_name != server_name}

    for t in tools:
        name = t.get("name", "")
        if not name or t.get("inputSchema") is None:
            continue
        prefixed = f"{target.name}{TOOL_SEP}{name}"
        cached = CachedTool(
            name=name,
            prefixed_name=prefixed,
            description=t.get("description", ""),
            input_schema=t.get("inputSchema", {}),
            server_name=target.name,
            server_url=target.url,
            namespace=ns,
        )
        _state.tool_map[prefixed] = cached
        _state.tools.append(cached)

    return len(tools)


# ---------------------------------------------------------------------------
# Dispatch — namespace and server scoped
# ---------------------------------------------------------------------------


def _filter_tools(
    namespace: str | None = None,
    server: str | None = None,
) -> list[CachedTool]:
    """Filter cached tools by namespace and/or server."""
    tools = _state.tools
    if namespace:
        servers_in_ns = set(_state.namespace_map.get(namespace, []))
        tools = [t for t in tools if t.server_name in servers_in_ns]
    if server:
        tools = [t for t in tools if t.server_name == server]
    return tools


async def proxy_tools_list(
    namespace: str | None = None,
    server: str | None = None,
) -> list[dict]:
    """Return tools list in MCP format, optionally filtered."""
    await refresh_tools()
    tools = _filter_tools(namespace=namespace, server=server)
    return [
        {
            "name": t.prefixed_name,
            "description": f"[{t.server_name}] {t.description}",
            "inputSchema": t.input_schema,
        }
        for t in tools
    ]


async def proxy_tools_call(tool_name: str, arguments: dict, req_id: int | str = 1) -> dict:
    """Route a tools/call to the correct backend server.

    Accepts both prefixed (kubernetes.kubectl_get) and unprefixed (kubectl_get) names.
    Prefixed names are unambiguous; unprefixed uses first match.
    """
    await refresh_tools()

    # Try prefixed name first (exact match)
    cached = _state.tool_map.get(tool_name)

    # Fallback: try unprefixed name (first match)
    if cached is None:
        for t in _state.tools:
            if t.name == tool_name:
                cached = t
                break

    if cached is None:
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            "isError": True,
        }

    meta = _state.server_meta.get(cached.server_name)
    auth_token = meta.auth_token if meta else ""
    return await _call_backend_tool(
        cached.server_name, cached.server_url, cached.name, arguments,
        auth_token=auth_token, req_id=req_id,
    )

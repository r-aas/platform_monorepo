"""MCP proxy transport endpoints — Streamable HTTP and SSE.

Unscoped (all tools):
  POST /mcp/proxy                    Streamable HTTP
  GET  /mcp/proxy/sse                SSE connect
  POST /mcp/proxy/sse                SSE POST fallback
  POST /mcp/proxy/sse/message        SSE message endpoint

Namespace-scoped (filtered tools):
  POST /mcp/proxy/ns/{namespace}             Streamable HTTP
  GET  /mcp/proxy/ns/{namespace}/sse         SSE connect
  POST /mcp/proxy/ns/{namespace}/sse         SSE POST fallback
  POST /mcp/proxy/ns/{namespace}/sse/message SSE message endpoint

Server-scoped (single server tools):
  POST /mcp/proxy/server/{server}             Streamable HTTP
  GET  /mcp/proxy/server/{server}/sse         SSE connect

Server management:
  GET    /mcp/servers
  POST   /mcp/servers
  DELETE /mcp/servers/{name}
  GET    /mcp/namespaces
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agent_gateway.mcp_proxy import (
    get_namespaces,
    get_proxy_state,
    proxy_tools_call,
    proxy_tools_list,
    refresh_single_server,
    refresh_tools,
)
from agent_gateway.store.mcp_servers import (
    delete_mcp_server,
    get_mcp_server,
    list_mcp_servers,
    upsert_mcp_server,
)

router = APIRouter(prefix="/mcp", tags=["mcp-proxy"])

_PROTOCOL_VERSION = "2024-11-05"


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _jsonrpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _handle_jsonrpc(
    body: dict,
    namespace: str | None = None,
    server: str | None = None,
) -> dict:
    """Process a single JSON-RPC request, optionally scoped to a namespace or server."""
    req_id = body.get("id")
    method = body.get("method", "")

    if method == "initialize":
        scope = namespace or server or "all"
        return _jsonrpc_result(req_id, {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": f"agent-gateway-proxy/{scope}", "version": "0.1.0"},
        })

    if method == "notifications/initialized":
        return _jsonrpc_result(req_id, {})

    if method == "tools/list":
        tools = await proxy_tools_list(namespace=namespace, server=server)
        return _jsonrpc_result(req_id, {"tools": tools})

    if method == "tools/call":
        params = body.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = await proxy_tools_call(tool_name, arguments, req_id)
        return _jsonrpc_result(req_id, result)

    return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")


def _sse_generator(message_url: str):
    """Create an SSE event generator that sends the endpoint URL then heartbeats."""
    async def generate():
        yield {"event": "endpoint", "data": message_url}
        while True:
            await asyncio.sleep(30)
            yield {"event": "ping", "data": ""}
    return generate


# ---------------------------------------------------------------------------
# Unscoped — all tools
# ---------------------------------------------------------------------------


@router.post("/proxy")
async def mcp_proxy_streamable(request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse(await _handle_jsonrpc(body))


@router.get("/proxy/sse")
async def mcp_proxy_sse_connect(request: Request):
    session_id = str(uuid.uuid4())
    base_url = str(request.base_url).rstrip("/")
    message_url = f"{base_url}/mcp/proxy/sse/message?session_id={session_id}"
    return EventSourceResponse(_sse_generator(message_url)())


@router.post("/proxy/sse/message")
async def mcp_proxy_sse_message(request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse(await _handle_jsonrpc(body))


@router.post("/proxy/sse")
async def mcp_proxy_sse_post(request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse(await _handle_jsonrpc(body))


# ---------------------------------------------------------------------------
# Namespace-scoped — /mcp/proxy/ns/{namespace}
# ---------------------------------------------------------------------------


@router.post("/proxy/ns/{namespace}")
async def mcp_proxy_ns_streamable(namespace: str, request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse(await _handle_jsonrpc(body, namespace=namespace))


@router.get("/proxy/ns/{namespace}/sse")
async def mcp_proxy_ns_sse_connect(namespace: str, request: Request):
    session_id = str(uuid.uuid4())
    base_url = str(request.base_url).rstrip("/")
    message_url = f"{base_url}/mcp/proxy/ns/{namespace}/sse/message?session_id={session_id}"
    return EventSourceResponse(_sse_generator(message_url)())


@router.post("/proxy/ns/{namespace}/sse/message")
async def mcp_proxy_ns_sse_message(namespace: str, request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse(await _handle_jsonrpc(body, namespace=namespace))


@router.post("/proxy/ns/{namespace}/sse")
async def mcp_proxy_ns_sse_post(namespace: str, request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse(await _handle_jsonrpc(body, namespace=namespace))


# ---------------------------------------------------------------------------
# Server-scoped — /mcp/proxy/server/{server}
# ---------------------------------------------------------------------------


@router.post("/proxy/server/{server}")
async def mcp_proxy_server_streamable(server: str, request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse(await _handle_jsonrpc(body, server=server))


@router.get("/proxy/server/{server}/sse")
async def mcp_proxy_server_sse_connect(server: str, request: Request):
    session_id = str(uuid.uuid4())
    base_url = str(request.base_url).rstrip("/")
    message_url = f"{base_url}/mcp/proxy/server/{server}/sse/message?session_id={session_id}"
    return EventSourceResponse(_sse_generator(message_url)())


@router.post("/proxy/server/{server}/sse/message")
async def mcp_proxy_server_sse_message(server: str, request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse(await _handle_jsonrpc(body, server=server))


@router.post("/proxy/server/{server}/sse")
async def mcp_proxy_server_sse_post(server: str, request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse(await _handle_jsonrpc(body, server=server))


# ---------------------------------------------------------------------------
# Server management REST endpoints
# ---------------------------------------------------------------------------


@router.get("/namespaces")
async def list_ns():
    """List namespaces with their servers and tool counts."""
    await refresh_tools()
    ns_map = get_namespaces()
    state = get_proxy_state()
    result = []
    for ns, servers in sorted(ns_map.items()):
        tool_count = len([t for t in state.tools if t.namespace == ns])
        result.append({"namespace": ns, "servers": servers, "tool_count": tool_count})
    return result


@router.get("/servers")
async def list_servers():
    """List all registered MCP backend servers."""
    rows = await list_mcp_servers()
    state = get_proxy_state()
    return [
        {
            "name": r.name,
            "url": r.url,
            "transport": r.transport,
            "namespace": r.namespace,
            "description": r.description,
            "status": r.health_status,
            "tool_count": len([t for t in state.tools if t.server_name == r.name]),
        }
        for r in rows
    ]


@router.post("/servers")
async def register_server(data: dict[str, Any]):
    """Register or update an MCP backend server."""
    name = data.get("name")
    url = data.get("url")
    if not name or not url:
        raise HTTPException(400, "name and url are required")
    row = await upsert_mcp_server(
        name=name,
        url=url,
        transport=data.get("transport", "streamable-http"),
        namespace=data.get("namespace", ""),
        description=data.get("description", ""),
        auth_token=data.get("auth_token", ""),
    )
    try:
        count = await refresh_single_server(name)
    except Exception:
        count = 0
    return {"name": row.name, "namespace": row.namespace, "status": "ok", "tools_discovered": count}


@router.delete("/servers/{name}")
async def remove_server(name: str):
    """Remove an MCP backend server."""
    try:
        await get_mcp_server(name)
    except KeyError:
        raise HTTPException(404, f"MCP server '{name}' not found")
    await delete_mcp_server(name)
    state = get_proxy_state()
    state.tools = [t for t in state.tools if t.server_name != name]
    state.tool_map = {k: v for k, v in state.tool_map.items() if v.server_name != name}
    return {"name": name, "status": "deleted"}


@router.post("/servers/{name}/refresh")
async def refresh_server_tools(name: str):
    """Re-fetch tools from a specific backend server."""
    try:
        count = await refresh_single_server(name)
    except KeyError:
        raise HTTPException(404, f"MCP server '{name}' not found")
    return {"name": name, "tools_discovered": count}


@router.post("/refresh")
async def refresh_all_tools():
    """Force refresh tools from all backend servers."""
    count = await refresh_tools(force=True)
    return {"total_tools": count}

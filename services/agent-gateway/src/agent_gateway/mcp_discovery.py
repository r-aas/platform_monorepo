"""MCP tool auto-discovery.

C.02: Scan MetaMCP namespaces and index all available tools.

Discovery flow:
  1. Authenticate to MetaMCP admin (port 12009) — same as metamcp_client
  2. List namespaces via tRPC (dynamic, not hardcoded)
  3. Fetch tools from MCP proxy (port 12008) for each namespace
  4. Store result in module-level ToolIndex for fast in-process lookup

Falls back gracefully at every step — MetaMCP being down must not break the gateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from agent_gateway.config import settings

_STATIC_NAMESPACES = ["genai", "platform"]
_PROXY_BASE = "http://genai-metamcp.genai.svc.cluster.local:12008"

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredTool:
    name: str
    description: str
    namespace: str


@dataclass
class ToolIndex:
    namespaces: list[str] = field(default_factory=list)
    tools: list[DiscoveredTool] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Module-level index (populated on startup via lifespan)
# ---------------------------------------------------------------------------

_tool_index: ToolIndex | None = None


def get_tool_index() -> ToolIndex | None:
    return _tool_index


def set_tool_index(idx: ToolIndex) -> None:
    global _tool_index
    _tool_index = idx


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


async def discover_namespaces() -> list[str]:
    """Return namespace names from MetaMCP admin API.

    Falls back to _STATIC_NAMESPACES when credentials absent or MetaMCP unreachable.
    Never raises.
    """
    if not settings.metamcp_user_email or not settings.metamcp_user_password:
        return list(_STATIC_NAMESPACES)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.metamcp_admin_url}/api/auth/sign-in/email",
                json={"email": settings.metamcp_user_email, "password": settings.metamcp_user_password},
            )
            resp.raise_for_status()
            cookie_header = resp.headers.get("set-cookie", "")
            token = next(
                (p.split("=", 1)[1] for p in cookie_header.split(";") if "better-auth.session_token=" in p),
                "",
            )
            cookie = f"better-auth.session_token={token}"

            ns_resp = await client.get(
                f"{settings.metamcp_admin_url}/trpc/frontend/frontend.namespaces.list",
                headers={"Cookie": cookie},
            )
            ns_resp.raise_for_status()
            data = ns_resp.json()
            return [ns["name"] for ns in data["result"]["data"]["data"]]

    except Exception:
        return list(_STATIC_NAMESPACES)


async def fetch_tools_for_namespace(namespace: str) -> list[DiscoveredTool]:
    """Fetch tools from MCP proxy for a single namespace.

    Returns empty list on any error — graceful fallback.
    """
    url = f"{_PROXY_BASE}/metamcp/{namespace}/mcp"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})
            resp.raise_for_status()
            data = resp.json()
            tools = data.get("result", {}).get("tools", [])
            return [
                DiscoveredTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    namespace=namespace,
                )
                for t in tools
            ]
    except Exception:
        return []


async def index_all_tools() -> ToolIndex:
    """Discover all namespaces and fetch their tools.

    Always returns a ToolIndex (may be empty). Never raises.
    Updates the module-level index as a side effect.
    """
    namespaces = await discover_namespaces()

    all_tools: list[DiscoveredTool] = []
    for ns in namespaces:
        all_tools.extend(await fetch_tools_for_namespace(ns))

    idx = ToolIndex(namespaces=namespaces, tools=all_tools)
    set_tool_index(idx)
    return idx

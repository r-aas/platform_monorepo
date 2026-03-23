"""MCP tool auto-discovery via LiteLLM MCP gateway.

C.02: Index all available tools from LiteLLM's aggregated MCP servers.

Discovery flow:
  1. GET /v1/mcp/server  — list registered MCP server names (used as "namespaces")
  2. GET /mcp-rest/tools/list — fetch all tools in one call
  3. Store result in module-level ToolIndex for fast in-process lookup

Falls back gracefully — LiteLLM being unreachable must not break the gateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from agent_gateway.config import settings

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
    """Return MCP server names from LiteLLM as namespace identifiers.

    Falls back to empty list when LiteLLM is unreachable. Never raises.
    """
    url = f"{settings.litellm_base_url}/v1/mcp/server"
    headers = {"Authorization": f"Bearer {settings.litellm_api_key}"} if settings.litellm_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [s["server_name"] for s in data]
    except Exception:
        return []


async def fetch_all_tools() -> list[DiscoveredTool]:
    """Fetch all tools from LiteLLM's aggregated MCP gateway.

    Returns empty list on any error — graceful fallback.
    """
    url = f"{settings.litellm_base_url}/mcp-rest/tools/list"
    headers = {"Authorization": f"Bearer {settings.litellm_api_key}"} if settings.litellm_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            tools = data.get("tools", [])
            # LiteLLM doesn't expose server_name per tool; use "litellm" as namespace
            return [
                DiscoveredTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    namespace="litellm",
                )
                for t in tools
            ]
    except Exception:
        return []


async def index_all_tools() -> ToolIndex:
    """Discover namespaces and fetch all tools from LiteLLM.

    Always returns a ToolIndex (may be empty). Never raises.
    Updates the module-level index as a side effect.
    """
    namespaces = await discover_namespaces()
    tools = await fetch_all_tools()
    idx = ToolIndex(namespaces=namespaces, tools=tools)
    set_tool_index(idx)
    return idx

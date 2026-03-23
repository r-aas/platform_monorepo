"""Gateway MCP server — exposes agent-gateway REST API as MCP tools.

Implements MCP Streamable HTTP transport (JSON-RPC 2.0 over HTTP POST).
Endpoint: POST /gateway-mcp

Tools exposed:
- list_agents      — list all registered agents
- get_agent        — get agent definition by name
- list_skills      — list all registered skills
- get_skill        — get skill definition by name
- create_skill     — register a new skill
- delete_skill     — delete a skill by name
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agent_gateway.models import SkillDefinition
from agent_gateway.registry import get_agent, list_agents
from agent_gateway.skills_registry import create_skill, delete_skill, get_skill, list_skills

router = APIRouter(prefix="/gateway-mcp", tags=["gateway-mcp"])

_PROTOCOL_VERSION = "2024-11-05"

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

_TOOLS: list[dict] = [
    {
        "name": "list_agents",
        "description": "List all registered agents in the gateway.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_agent",
        "description": "Get a specific agent definition by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_skills",
        "description": "List all registered skills in the gateway.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_skill",
        "description": "Get a specific skill definition by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_skill",
        "description": "Register a new skill in the gateway.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "version": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "prompt_fragment": {"type": "string"},
                "mcp_servers": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of MCP server refs {url, tool_filter}",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_skill",
        "description": "Delete a skill by name. Use force=true to delete even if referenced by agents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "force": {"type": "boolean", "default": False},
            },
            "required": ["name"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


async def _dispatch(tool_name: str, arguments: dict) -> dict:
    """Dispatch a tool call and return MCP result content."""
    try:
        if tool_name == "list_agents":
            agents = await list_agents()
            return _ok(json.dumps([{"name": a.name, "description": a.description, "runtime": a.runtime} for a in agents], indent=2))

        if tool_name == "get_agent":
            agent = await get_agent(arguments["name"])
            return _ok(json.dumps({"name": agent.name, "description": agent.description, "runtime": agent.runtime, "skills": agent.skills}, indent=2))

        if tool_name == "list_skills":
            skills = await asyncio.to_thread(list_skills)
            return _ok(json.dumps([{"name": s.name, "description": s.description, "version": s.version, "tags": s.tags} for s in skills], indent=2))

        if tool_name == "get_skill":
            skill = await asyncio.to_thread(get_skill, arguments["name"])
            return _ok(json.dumps({"name": skill.name, "description": skill.description, "version": skill.version, "tags": skill.tags, "task_count": len(skill.tasks)}, indent=2))

        if tool_name == "create_skill":
            skill = SkillDefinition(**arguments)
            await asyncio.to_thread(create_skill, skill)
            return _ok(f"Skill '{skill.name}' created successfully.")

        if tool_name == "delete_skill":
            force = arguments.get("force", False)
            await asyncio.to_thread(delete_skill, arguments["name"], force)
            return _ok(f"Skill '{arguments['name']}' deleted.")

        return _error(f"Unknown tool: {tool_name}")

    except KeyError as e:
        return _error(f"Not found: {e}")
    except ValueError as e:
        return _error(str(e))
    except Exception as e:
        return _error(f"Tool error: {e}")


def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


# ---------------------------------------------------------------------------
# JSON-RPC router
# ---------------------------------------------------------------------------


@router.post("")
async def handle_mcp(request: Request) -> JSONResponse:
    body = await request.json()
    req_id = body.get("id")
    method = body.get("method", "")

    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "agent-gateway", "version": "0.1.0"},
            },
        })

    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOLS}})

    if method == "tools/call":
        params = body.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = await _dispatch(tool_name, arguments)
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

    # Method not found
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    })

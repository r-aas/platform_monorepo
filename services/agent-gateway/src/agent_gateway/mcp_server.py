"""Gateway MCP server — exposes agent-gateway REST API as MCP tools.

Implements MCP Streamable HTTP transport (JSON-RPC 2.0 over HTTP POST).
Endpoint: POST /gateway-mcp

Tools exposed:
- list_agents            — list all registered agents
- get_agent              — get agent definition by name
- list_skills            — list all registered skills
- get_skill              — get skill definition by name
- create_skill           — register a new skill
- delete_skill           — delete a skill by name
- list_mcp_servers       — list registered MCP backend servers
- register_mcp_server    — register a new MCP backend server
- remove_mcp_server      — remove an MCP backend server
- list_mcp_tools         — list all aggregated MCP tools
- call_mcp_tool          — call a tool on a backend MCP server
- health_check_mcp_server — check health of a specific MCP server
"""

from __future__ import annotations

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
    # MCP management tools
    {
        "name": "list_mcp_servers",
        "description": "List all registered MCP backend servers with their status and tool counts.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "register_mcp_server",
        "description": "Register a new MCP backend server endpoint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Server name (unique identifier)"},
                "url": {"type": "string", "description": "MCP server endpoint URL"},
                "transport": {
                    "type": "string",
                    "description": "Transport type (streamable-http or sse)",
                    "default": "streamable-http",
                },
                "namespace": {"type": "string", "description": "Logical namespace for grouping"},
                "description": {"type": "string", "description": "Human-readable description"},
                "auth_token": {"type": "string", "description": "Bearer token for authentication"},
            },
            "required": ["name", "url"],
        },
    },
    {
        "name": "remove_mcp_server",
        "description": "Remove a registered MCP backend server.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Server name to remove"}},
            "required": ["name"],
        },
    },
    {
        "name": "list_mcp_tools",
        "description": "List aggregated MCP tools. Optionally filter by namespace or server.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Filter by namespace (e.g., platform, orchestration, data)",
                },
                "server": {"type": "string", "description": "Filter by server name (e.g., kubernetes, gitlab, n8n)"},
            },
            "required": [],
        },
    },
    {
        "name": "call_mcp_tool",
        "description": "Call a specific tool on a backend MCP server by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "Name of the tool to call"},
                "arguments": {"type": "object", "description": "Arguments to pass to the tool"},
            },
            "required": ["tool_name"],
        },
    },
    {
        "name": "health_check_mcp_server",
        "description": "Check health of a specific MCP backend server by re-fetching its tools.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Server name to health-check"}},
            "required": ["name"],
        },
    },
    # Dev sandbox tools
    {
        "name": "init_dev_sandbox",
        "description": "Create an isolated development sandbox from a git repo and branch. Clones the repo, optionally runs setup (e.g. 'uv sync'), and assigns a task to the agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Git repo URL or short name (e.g. 'genai-mlops', 'platform_monorepo')",
                },
                "branch": {"type": "string", "description": "Git branch to clone (default: main)", "default": "main"},
                "setup_command": {
                    "type": "string",
                    "description": "Setup command to run after clone (e.g. 'uv sync', 'npm install')",
                    "default": "",
                },
                "message": {
                    "type": "string",
                    "description": "Task description for the agent to perform in the sandbox",
                    "default": "",
                },
            },
            "required": ["repo"],
        },
    },
    {
        "name": "sandbox_status",
        "description": "Get the status and logs of a sandbox job by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string", "description": "Sandbox job name (e.g. sandbox-a1b2c3d4)"},
            },
            "required": ["job_name"],
        },
    },
    {
        "name": "list_sandboxes",
        "description": "List all active and recent sandbox jobs.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "sandbox_files",
        "description": "List or read files in a sandbox's workspace. Use path='.' to list root, or provide a file path to read its content.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string", "description": "Sandbox job name"},
                "path": {
                    "type": "string",
                    "description": "Path relative to workspace root (default: '.' for listing)",
                    "default": ".",
                },
                "read": {
                    "type": "boolean",
                    "description": "If true, read file content instead of listing",
                    "default": False,
                },
            },
            "required": ["job_name"],
        },
    },
    {
        "name": "sandbox_teardown",
        "description": "Delete a sandbox job and clean up all its resources (Job, PVC, ConfigMap, NetworkPolicy).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string", "description": "Sandbox job name to delete"},
            },
            "required": ["job_name"],
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
            return _ok(
                json.dumps(
                    [{"name": a.name, "description": a.description, "runtime": a.runtime} for a in agents], indent=2
                )
            )

        if tool_name == "get_agent":
            agent = await get_agent(arguments["name"])
            return _ok(
                json.dumps(
                    {
                        "name": agent.name,
                        "description": agent.description,
                        "runtime": agent.runtime,
                        "skills": agent.skills,
                    },
                    indent=2,
                )
            )

        if tool_name == "list_skills":
            skills = await list_skills()
            return _ok(
                json.dumps(
                    [
                        {"name": s.name, "description": s.description, "version": s.version, "tags": s.tags}
                        for s in skills
                    ],
                    indent=2,
                )
            )

        if tool_name == "get_skill":
            skill = await get_skill(arguments["name"])
            return _ok(
                json.dumps(
                    {
                        "name": skill.name,
                        "description": skill.description,
                        "version": skill.version,
                        "tags": skill.tags,
                        "task_count": len(skill.tasks),
                    },
                    indent=2,
                )
            )

        if tool_name == "create_skill":
            skill = SkillDefinition(**arguments)
            await create_skill(skill)
            return _ok(f"Skill '{skill.name}' created successfully.")

        if tool_name == "delete_skill":
            force = arguments.get("force", False)
            await delete_skill(arguments["name"], force)
            return _ok(f"Skill '{arguments['name']}' deleted.")

        # MCP management tools
        if tool_name == "list_mcp_servers":
            from agent_gateway.store.mcp_servers import list_mcp_servers as _list_servers
            from agent_gateway.mcp_proxy import get_proxy_state

            rows = await _list_servers()
            state = get_proxy_state()
            servers = [
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
            return _ok(json.dumps(servers, indent=2))

        if tool_name == "register_mcp_server":
            from agent_gateway.store.mcp_servers import upsert_mcp_server
            from agent_gateway.mcp_proxy import refresh_single_server

            row = await upsert_mcp_server(
                name=arguments["name"],
                url=arguments["url"],
                transport=arguments.get("transport", "streamable-http"),
                namespace=arguments.get("namespace", ""),
                description=arguments.get("description", ""),
                auth_token=arguments.get("auth_token", ""),
            )
            try:
                count = await refresh_single_server(arguments["name"])
            except Exception:
                count = 0
            return _ok(f"MCP server '{row.name}' registered. {count} tools discovered.")

        if tool_name == "remove_mcp_server":
            from agent_gateway.store.mcp_servers import delete_mcp_server as _del_server
            from agent_gateway.mcp_proxy import get_proxy_state

            await _del_server(arguments["name"])
            state = get_proxy_state()
            state.tools = [t for t in state.tools if t.server_name != arguments["name"]]
            state.tool_map = {k: v for k, v in state.tool_map.items() if v.server_name != arguments["name"]}
            return _ok(f"MCP server '{arguments['name']}' removed.")

        if tool_name == "list_mcp_tools":
            from agent_gateway.mcp_proxy import proxy_tools_list, get_namespaces

            ns = arguments.get("namespace")
            srv = arguments.get("server")
            tools = await proxy_tools_list(namespace=ns, server=srv)
            scope = ns or srv or "all"
            summary = {
                "scope": scope,
                "count": len(tools),
                "tools": [{"name": t["name"], "description": t["description"][:120]} for t in tools],
            }
            if not ns and not srv:
                summary["namespaces"] = {k: len(v) for k, v in get_namespaces().items()}
            return _ok(json.dumps(summary, indent=2))

        if tool_name == "call_mcp_tool":
            from agent_gateway.mcp_proxy import proxy_tools_call

            result = await proxy_tools_call(arguments["tool_name"], arguments.get("arguments", {}))
            return _ok(json.dumps(result, indent=2))

        if tool_name == "health_check_mcp_server":
            from agent_gateway.mcp_proxy import refresh_single_server

            count = await refresh_single_server(arguments["name"])
            return _ok(f"MCP server '{arguments['name']}' healthy. {count} tools available.")

        # Dev sandbox tools
        if tool_name == "init_dev_sandbox":
            from agent_gateway.runtimes.sandbox import DevSandboxRequest, create_dev_sandbox

            req = DevSandboxRequest(
                repo=arguments["repo"],
                branch=arguments.get("branch", "main"),
                setup_command=arguments.get("setup_command", ""),
                message=arguments.get("message", ""),
            )
            job_name = await create_dev_sandbox(req)
            return _ok(
                json.dumps(
                    {"job_name": job_name, "repo": req.repo, "branch": req.branch, "status": "created"}, indent=2
                )
            )

        if tool_name == "sandbox_status":
            from agent_gateway.runtimes.sandbox import get_sandbox_status, get_sandbox_logs

            status = await get_sandbox_status(arguments["job_name"])
            logs = await get_sandbox_logs(arguments["job_name"])
            # Truncate logs for MCP response
            log_tail = logs[-3000:] if len(logs) > 3000 else logs
            return _ok(json.dumps({**status, "logs_tail": log_tail}, indent=2))

        if tool_name == "list_sandboxes":
            from agent_gateway.runtimes.sandbox import list_sandbox_jobs

            jobs = await list_sandbox_jobs()
            return _ok(json.dumps({"sandboxes": jobs, "count": len(jobs)}, indent=2))

        if tool_name == "sandbox_files":
            from agent_gateway.runtimes.sandbox import get_sandbox_artifacts, read_sandbox_artifact

            job = arguments["job_name"]
            path = arguments.get("path", ".")
            if arguments.get("read"):
                content = await read_sandbox_artifact(job, path)
                return _ok(content or f"File not found: {path}")
            artifacts = await get_sandbox_artifacts(job, path)
            return _ok(json.dumps({"job_name": job, "path": path, "files": artifacts}, indent=2))

        if tool_name == "sandbox_teardown":
            from agent_gateway.runtimes.sandbox import delete_sandbox_job

            await delete_sandbox_job(arguments["job_name"])
            return _ok(f"Sandbox '{arguments['job_name']}' deleted.")

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
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "agent-gateway", "version": "0.1.0"},
                },
            }
        )

    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOLS}})

    if method == "tools/call":
        params = body.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = await _dispatch(tool_name, arguments)
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

    # Method not found
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    )

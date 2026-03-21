"""Agent discovery and export API router."""

import asyncio

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from agent_gateway.registry import get_agent, list_agents
from agent_gateway.skills_registry import get_skill

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/search")
async def search_agents(q: str = Query(..., description="Search query for hybrid RAG over agent definitions")):
    """Hybrid search: keyword + semantic similarity over agent names, descriptions, skills, system prompts."""
    agents = await list_agents()
    query_lower = q.lower()

    # Keyword scoring — matches on name, description, skills, system prompt
    scored = []
    for agent in agents:
        score = 0
        searchable = f"{agent.name} {agent.description} {' '.join(agent.skills)} {agent.system_prompt}".lower()
        for term in query_lower.split():
            if term in searchable:
                score += 1
            if term in agent.name.lower():
                score += 3  # name match weighted higher
            if term in agent.description.lower():
                score += 2
        if score > 0:
            scored.append((score, agent))

    scored.sort(key=lambda x: x[0], reverse=True)

    # TODO: add embedding-based semantic similarity via Ollama /v1/embeddings
    # For now, keyword-only. Hybrid = keyword + embeddings when embeddings are wired.

    return {
        "query": q,
        "results": [
            {
                "name": a.name,
                "description": a.description,
                "runtime": a.runtime,
                "skills": a.skills,
                "score": s,
            }
            for s, a in scored
        ],
    }


@router.get("")
async def list_agents_endpoint():
    agents = await list_agents()
    return {
        "agents": [
            {
                "name": a.name,
                "description": a.description,
                "runtime": a.runtime,
                "workflow": a.workflow,
                "skills": a.skills,
                "input_parameters": a.inputs,
            }
            for a in agents
        ]
    }


@router.get("/{name}")
async def get_agent_endpoint(name: str):
    try:
        agent = await get_agent(name)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent '{name}' not found", "code": "agent_not_found"}},
        )

    # Resolve skills for detail view
    resolved_skills = []
    for skill_name in agent.skills:
        try:
            skill = await asyncio.to_thread(get_skill, skill_name)
            resolved_skills.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "tasks": [t.name for t in skill.tasks],
                    "tool_count": sum(len(ms.tool_filter or []) for ms in skill.mcp_servers),
                }
            )
        except KeyError:
            resolved_skills.append({"name": skill_name, "description": "(not found)", "tasks": [], "tool_count": 0})

    return {
        "name": agent.name,
        "description": agent.description,
        "runtime": agent.runtime,
        "workflow": agent.workflow,
        "agentspec_version": agent.agentspec_version,
        "llm": {"model": agent.llm_config.model_id, "url": agent.llm_config.url},
        "skills": resolved_skills,
        "input_parameters": agent.inputs,
        "system_prompt_preview": agent.system_prompt[:100] + "..."
        if len(agent.system_prompt) > 100
        else agent.system_prompt,
    }


@router.get("/{name}/spec")
async def export_agent_spec(name: str):
    """Export agent as valid Agent Spec JSON — MCP servers translated to MCPToolBox format."""
    try:
        agent = await get_agent(name)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent '{name}' not found", "code": "agent_not_found"}},
        )

    # Resolve skills and merge MCP servers
    all_mcp_servers = list(agent.mcp_servers)
    for skill_name in agent.skills:
        try:
            skill = await asyncio.to_thread(get_skill, skill_name)
            all_mcp_servers.extend(skill.mcp_servers)
        except KeyError:
            pass

    # Deduplicate by URL
    seen = set()
    unique_servers = []
    for ms in all_mcp_servers:
        if ms.url not in seen:
            seen.add(ms.url)
            unique_servers.append(ms)

    # Translate to Agent Spec MCPToolBox format
    toolboxes = []
    for ms in unique_servers:
        tb = {
            "component_type": "MCPToolBox",
            "name": f"mcp-{len(toolboxes)}",
            "client_transport": {
                "component_type": "StreamableHTTPTransport",
                "name": f"transport-{len(toolboxes)}",
                "url": ms.url,
            },
        }
        if ms.tool_filter:
            tb["tool_filter"] = ms.tool_filter
        toolboxes.append(tb)

    spec = {
        "component_type": "Agent",
        "name": agent.name,
        "description": agent.description,
        "metadata": {"runtime": agent.runtime, "workflow": agent.workflow},
        "inputs": agent.inputs,
        "outputs": [],
        "llm_config": {
            "component_type": "OllamaConfig",
            "name": "ollama-litellm",
            "url": agent.llm_config.url,
            "model_id": agent.llm_config.model_id,
        },
        "system_prompt": agent.system_prompt,
        "tools": [],
        "toolboxes": toolboxes,
        "agentspec_version": agent.agentspec_version,
    }

    return JSONResponse(content=spec)

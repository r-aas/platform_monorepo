"""Registry CRUD router — agents, skills, envs, deployments, A2A cards, evals."""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Query

from agent_gateway.config import settings
from agent_gateway.store import async_session
from agent_gateway.store.agents import get_agent, list_agents, upsert_agent
from agent_gateway.store.deployments import list_deployments, list_eval_runs, upsert_deployment
from agent_gateway.store.environments import get_environment, list_environments, upsert_environment
from agent_gateway.store.db import AgentRow, CapabilityRow
from sqlalchemy import select, text

router = APIRouter(tags=["registry"])


# ── Agents ──────────────────────────────────────────────────


@router.post("/agents")
async def upsert_agent_endpoint(spec: dict[str, Any]):
    """Create or update an agent from AgentSpec dict."""
    from agent_platform.models.agent import AgentSpec
    agent = AgentSpec.model_validate(spec)
    row = await upsert_agent(
        name=agent.name,
        version=agent.agentspec_version,
        spec=agent.model_dump(),
        system_prompt=agent.system_prompt,
        capabilities=agent.capabilities,
        skills=agent.skills,
        runtime=agent.runtime,
        tags=agent.tags,
    )
    return {"name": row.name, "status": "ok"}


@router.get("/agents/{name}/spec")
async def get_agent_spec(name: str, env: str | None = None):
    """Export portable Agent Spec YAML. Optionally resolve for an environment."""
    try:
        row = await get_agent(name)
    except KeyError:
        raise HTTPException(404, f"Agent '{name}' not found")

    from agent_platform.models.agent import AgentSpec
    agent = AgentSpec.model_validate(row.spec)

    if env:
        try:
            env_row = await get_environment(env)
        except KeyError:
            raise HTTPException(404, f"Environment '{env}' not found")
        from agent_platform.models.environment import EnvironmentBinding
        binding = EnvironmentBinding.model_validate(env_row.config)
        agent = agent.resolve(binding.resolve_bindings())

    return yaml.dump(agent.model_dump(exclude_none=True), default_flow_style=False, sort_keys=False)


# ── Environments ────────────────────────────────────────────


@router.get("/envs")
async def list_envs_endpoint():
    rows = await list_environments()
    return [{"environment": r.environment, "capabilities": list(r.capabilities.keys()) if isinstance(r.capabilities, dict) else []} for r in rows]


@router.get("/envs/{env}")
async def get_env_endpoint(env: str):
    try:
        row = await get_environment(env)
    except KeyError:
        raise HTTPException(404, f"Environment '{env}' not found")
    return row.config


@router.post("/envs")
async def upsert_env_endpoint(data: dict[str, Any]):
    from agent_platform.models.environment import EnvironmentBinding
    binding = EnvironmentBinding.model_validate(data)
    cap_dict = {k: v.model_dump() for k, v in binding.capabilities.items()}
    runtime_dict = {k: v.model_dump() for k, v in binding.runtimes.items()}
    row = await upsert_environment(
        environment=binding.environment,
        config=binding.model_dump(),
        capabilities=cap_dict,
        llm_config=binding.llm.model_dump(),
        runtimes=runtime_dict,
    )
    return {"environment": row.environment, "status": "ok"}


@router.get("/envs/{env}/resolve/{agent_name}")
async def resolve_agent_for_env(env: str, agent_name: str):
    """Return a fully resolved agent spec for a specific environment."""
    try:
        agent_row = await get_agent(agent_name)
    except KeyError:
        raise HTTPException(404, f"Agent '{agent_name}' not found")
    try:
        env_row = await get_environment(env)
    except KeyError:
        raise HTTPException(404, f"Environment '{env}' not found")

    from agent_platform.models.agent import AgentSpec
    from agent_platform.models.environment import EnvironmentBinding
    agent = AgentSpec.model_validate(agent_row.spec)
    binding = EnvironmentBinding.model_validate(env_row.config)
    resolved = agent.resolve(binding.resolve_bindings())
    return resolved.model_dump(exclude_none=True)


# ── Capabilities ────────────────────────────────────────────


@router.get("/capabilities")
async def list_capabilities():
    async with async_session() as session:
        result = await session.execute(select(CapabilityRow))
        rows = result.scalars().all()
    return [{"name": r.name, "description": r.description, "providers": r.providers} for r in rows]


# ── Deployments ─────────────────────────────────────────────


@router.post("/deployments/heartbeat")
async def deployment_heartbeat(data: dict[str, Any]):
    row = await upsert_deployment(
        agent_name=data["agent_name"],
        environment=data["environment"],
        gateway_url=data["gateway_url"],
        agent_version=data.get("agent_version", ""),
        status=data.get("status", "unknown"),
        error_count_1h=data.get("error_count_1h", 0),
    )
    return {"status": "ok"}


@router.get("/deployments")
async def list_deployments_endpoint(env: str | None = None):
    rows = await list_deployments(env)
    return [
        {
            "agent_name": r.agent_name,
            "environment": r.environment,
            "gateway_url": r.gateway_url,
            "agent_version": r.agent_version,
            "status": r.status,
            "last_heartbeat": r.last_heartbeat.isoformat() if r.last_heartbeat else None,
        }
        for r in rows
    ]


# ── A2A Agent Cards ─────────────────────────────────────────


def _build_agent_card(name: str, spec: dict) -> dict:
    return {
        "name": name,
        "description": spec.get("description", ""),
        "url": f"{settings.gateway_external_url}/v1/agents/{name}",
        "protocolVersion": settings.a2a_protocol_version,
        "capabilities": {"streaming": True, "pushNotifications": False, "stateTransitionHistory": False},
        "skills": [
            {"id": f"{name}.{skill}", "name": skill, "tags": []}
            for skill in spec.get("skills", [])
        ],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    }


@router.get("/.well-known/agent-card.json")
async def all_agent_cards():
    rows = await list_agents()
    return [_build_agent_card(r.name, r.spec) for r in rows]


@router.get("/.well-known/agent-card/{name}.json")
async def agent_card(name: str):
    try:
        row = await get_agent(name)
    except KeyError:
        raise HTTPException(404, f"Agent '{name}' not found")
    return _build_agent_card(row.name, row.spec)


# ── Eval Runs ───────────────────────────────────────────────


@router.get("/agents/{name}/evals")
async def list_evals(name: str, limit: int = Query(20, le=100)):
    rows = await list_eval_runs(name, limit)
    return [
        {
            "agent_name": r.agent_name,
            "agent_version": r.agent_version,
            "environment": r.environment,
            "model": r.model,
            "skill": r.skill,
            "task": r.task,
            "pass_rate": r.pass_rate,
            "avg_latency_ms": r.avg_latency_ms,
            "run_at": r.run_at.isoformat() if r.run_at else None,
        }
        for r in rows
    ]


# ── Health detail (DB-backed) ───────────────────────────────


@router.get("/health/detail")
async def health_detail():
    async with async_session() as session:
        agents = (await session.execute(text("SELECT count(*) FROM agents"))).scalar() or 0
        skills_count = (await session.execute(text("SELECT count(*) FROM skills"))).scalar() or 0
        envs = (await session.execute(text("SELECT count(*) FROM environment_bindings"))).scalar() or 0
        mcp = (await session.execute(text("SELECT count(*) FROM mcp_servers"))).scalar() or 0
    return {
        "status": "healthy",
        "store": "postgresql",
        "agents": agents,
        "skills": skills_count,
        "environments": envs,
        "mcp_servers": mcp,
    }

"""Agent lookup — reads agent definitions from PostgreSQL.

Consolidates registry.py + store/agents.py into a single module.
Long-term: agent definitions migrate to kagent CRDs; this module
will delegate to the kagent API. For now it reads the local DB tables
that store/agents.py previously owned.

Supports promotion-aware agent resolution: when an agent has a canary
variant (named '{name}-canary'), the resolver uses weighted random routing
to direct canary_weight% of traffic to the canary version.
"""

from __future__ import annotations

import logging
import random
import uuid

from sqlalchemy import select

from agent_gateway.models import AgentDefinition, LlmConfig, MCPServerRef
from agent_gateway.store.db import AgentRow, async_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Row → domain model conversion
# ---------------------------------------------------------------------------


def _row_to_agent(row: AgentRow) -> AgentDefinition:
    """Convert an AgentRow ORM object to an AgentDefinition domain model."""
    spec = row.spec or {}

    mcp_servers = []
    for s in spec.get("mcp_servers", []):
        if isinstance(s, dict):
            mcp_servers.append(MCPServerRef(**s))

    llm = spec.get("llm_config", {})
    if isinstance(llm, dict):
        llm_config = LlmConfig(
            url=llm.get("url", llm.get("base_url", "")),
            model_id=llm.get("model_id", llm.get("default_model", "")),
            api_key=llm.get("api_key", llm.get("api_key_ref", "")),
        )
    else:
        llm_config = LlmConfig()

    return AgentDefinition(
        name=row.name,
        description=spec.get("description", ""),
        system_prompt=row.system_prompt or spec.get("system_prompt", ""),
        mcp_servers=mcp_servers,
        skills=row.skills or spec.get("skills", []),
        llm_config=llm_config,
        runtime=row.runtime or spec.get("runtime", "n8n"),
        workflow=spec.get("workflow", spec.get("metadata", {}).get("workflow", "")),
        inputs=spec.get("inputs", []),
        agentspec_version=row.version or spec.get("agentspec_version", "26.2.0"),
    )


# ---------------------------------------------------------------------------
# DB operations (previously in store/agents.py)
# ---------------------------------------------------------------------------


async def _db_list_agents() -> list[AgentRow]:
    async with async_session() as session:
        result = await session.execute(select(AgentRow))
        return list(result.scalars().all())


async def _db_get_agent(name: str) -> AgentRow:
    async with async_session() as session:
        row = (
            await session.execute(select(AgentRow).where(AgentRow.name == name))
        ).scalar_one_or_none()
    if not row:
        raise KeyError(f"Agent '{name}' not found")
    return row


async def _db_get_canary(base_name: str) -> AgentRow | None:
    canary_name = f"{base_name}-canary"
    async with async_session() as session:
        row = (
            await session.execute(
                select(AgentRow).where(
                    AgentRow.name == canary_name,
                    AgentRow.promotion_stage == "canary",
                )
            )
        ).scalar_one_or_none()
    if row and (row.canary_weight or 0) > 0:
        return row
    return None


async def upsert_agent(
    *,
    name: str,
    version: str,
    spec: dict,
    system_prompt: str = "",
    capabilities: list[str] | None = None,
    skills: list[str] | None = None,
    runtime: str = "n8n",
    tags: list[str] | None = None,
) -> AgentRow:
    async with async_session() as session:
        existing = (
            await session.execute(select(AgentRow).where(AgentRow.name == name))
        ).scalar_one_or_none()
        if existing:
            existing.version = version
            existing.spec = spec
            existing.system_prompt = system_prompt
            existing.capabilities = capabilities or []
            existing.skills = skills or []
            existing.runtime = runtime
            existing.tags = tags or []
            row = existing
        else:
            row = AgentRow(
                id=str(uuid.uuid4()),
                name=name,
                version=version,
                spec=spec,
                system_prompt=system_prompt,
                capabilities=capabilities or [],
                skills=skills or [],
                runtime=runtime,
                tags=tags or [],
            )
            session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Public API (previously in registry.py)
# ---------------------------------------------------------------------------


async def get_agent(name: str) -> AgentDefinition:
    """Look up an agent by name with canary-aware weighted routing.

    When a canary variant exists ('{name}-canary' with promotion_stage='canary'),
    routes canary_weight% of requests to the canary version.

    Shadow agents are never returned here — they run in parallel via the
    shadow execution path in the chat router.
    """
    row = await _db_get_agent(name)

    canary_row = await _db_get_canary(name)
    if canary_row:
        weight = canary_row.canary_weight or 0
        if random.randint(1, 100) <= weight:
            logger.info(
                "Canary routing: %s → %s (weight=%d%%)",
                name,
                canary_row.name,
                weight,
            )
            agent = _row_to_agent(canary_row)
            agent.promotion_stage = "canary"
            agent.canary_weight = weight
            return agent

    agent = _row_to_agent(row)
    agent.promotion_stage = getattr(row, "promotion_stage", "primary") or "primary"
    agent.canary_weight = getattr(row, "canary_weight", 0) or 0
    return agent


async def list_agents() -> list[AgentDefinition]:
    """List all agents."""
    rows = await _db_list_agents()
    return [_row_to_agent(r) for r in rows]

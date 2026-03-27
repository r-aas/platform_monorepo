"""Agent CRUD operations backed by PostgreSQL."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from agent_gateway.store.db import AgentRow, async_session


async def list_agents() -> list[AgentRow]:
    async with async_session() as session:
        result = await session.execute(select(AgentRow))
        return list(result.scalars().all())


async def get_agent(name: str) -> AgentRow:
    async with async_session() as session:
        row = (await session.execute(select(AgentRow).where(AgentRow.name == name))).scalar_one_or_none()
    if not row:
        raise KeyError(f"Agent '{name}' not found")
    return row


async def upsert_agent(*, name: str, version: str, spec: dict, system_prompt: str = "",
                       capabilities: list[str] | None = None, skills: list[str] | None = None,
                       runtime: str = "n8n", tags: list[str] | None = None) -> AgentRow:
    async with async_session() as session:
        existing = (await session.execute(select(AgentRow).where(AgentRow.name == name))).scalar_one_or_none()
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

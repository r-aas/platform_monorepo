"""Environment binding CRUD operations."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from agent_gateway.store.db import EnvironmentBindingRow, async_session


async def list_environments() -> list[EnvironmentBindingRow]:
    async with async_session() as session:
        result = await session.execute(select(EnvironmentBindingRow))
        return list(result.scalars().all())


async def get_environment(env: str) -> EnvironmentBindingRow:
    async with async_session() as session:
        row = (await session.execute(
            select(EnvironmentBindingRow).where(EnvironmentBindingRow.environment == env)
        )).scalar_one_or_none()
    if not row:
        raise KeyError(f"Environment '{env}' not found")
    return row


async def upsert_environment(*, environment: str, config: dict, capabilities: dict,
                             llm_config: dict, runtimes: dict | None = None) -> EnvironmentBindingRow:
    async with async_session() as session:
        existing = (await session.execute(
            select(EnvironmentBindingRow).where(EnvironmentBindingRow.environment == environment)
        )).scalar_one_or_none()
        if existing:
            existing.config = config
            existing.capabilities = capabilities
            existing.llm_config = llm_config
            existing.runtimes = runtimes or {}
            row = existing
        else:
            row = EnvironmentBindingRow(
                id=str(uuid.uuid4()),
                environment=environment,
                config=config,
                capabilities=capabilities,
                llm_config=llm_config,
                runtimes=runtimes or {},
            )
            session.add(row)
        await session.commit()
        await session.refresh(row)
    return row

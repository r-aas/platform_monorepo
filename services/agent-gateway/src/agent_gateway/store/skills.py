"""Skill CRUD operations backed by PostgreSQL."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from agent_gateway.store.db import SkillRow, async_session


async def list_skills() -> list[SkillRow]:
    async with async_session() as session:
        result = await session.execute(select(SkillRow))
        return list(result.scalars().all())


async def get_skill(name: str) -> SkillRow:
    async with async_session() as session:
        row = (await session.execute(select(SkillRow).where(SkillRow.name == name))).scalar_one_or_none()
    if not row:
        raise KeyError(f"Skill '{name}' not found")
    return row


async def upsert_skill(*, name: str, version: str = "1.0.0", description: str = "",
                       tags: list[str] | None = None, capabilities: list[str] | None = None,
                       operations: list[str] | None = None, manifest: str = "",
                       advertise: str = "") -> SkillRow:
    async with async_session() as session:
        existing = (await session.execute(select(SkillRow).where(SkillRow.name == name))).scalar_one_or_none()
        if existing:
            existing.version = version
            existing.description = description
            existing.tags = tags or []
            existing.capabilities = capabilities or []
            existing.operations = operations or []
            existing.manifest = manifest
            existing.advertise = advertise or description[:200]
            row = existing
        else:
            row = SkillRow(
                id=str(uuid.uuid4()),
                name=name,
                version=version,
                description=description,
                tags=tags or [],
                capabilities=capabilities or [],
                operations=operations or [],
                manifest=manifest,
                advertise=advertise or description[:200],
            )
            session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def delete_skill(name: str) -> None:
    async with async_session() as session:
        row = (await session.execute(select(SkillRow).where(SkillRow.name == name))).scalar_one_or_none()
        if not row:
            raise KeyError(f"Skill '{name}' not found")
        await session.delete(row)
        await session.commit()

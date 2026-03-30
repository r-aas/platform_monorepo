"""Skill lookup — reads/writes skill definitions backed by PostgreSQL.

Consolidates skills_registry.py + store/skills.py into a single module.
Long-term: skill definitions migrate to agentregistry; this module
will delegate to the agentregistry gRPC/HTTP API. For now it reads the
local DB tables that store/skills.py previously owned.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from agent_gateway.models import EvaluationRef, MCPServerRef, SkillDefinition, TaskDefinition
from agent_gateway.store.db import SkillRow, async_session


# ---------------------------------------------------------------------------
# Row → domain model conversion
# ---------------------------------------------------------------------------


def _row_to_skill(row: SkillRow) -> SkillDefinition:
    """Convert a SkillRow ORM object to a SkillDefinition domain model."""
    mcp_servers = []
    tasks = []

    if row.manifest:
        try:
            data = json.loads(row.manifest)
            if isinstance(data, dict):
                for s in data.get("mcp_servers", []):
                    mcp_servers.append(MCPServerRef(**s))
                for t in data.get("tasks", []):
                    eval_data = t.pop("evaluation", None) if isinstance(t, dict) else None
                    task = TaskDefinition(**t) if isinstance(t, dict) else TaskDefinition(name=str(t))
                    if eval_data:
                        task.evaluation = EvaluationRef(**eval_data)
                    tasks.append(task)
        except (json.JSONDecodeError, TypeError):
            pass

    return SkillDefinition(
        name=row.name,
        description=row.description,
        version=row.version,
        tags=row.tags or [],
        mcp_servers=mcp_servers,
        prompt_fragment=row.manifest if not mcp_servers and not tasks else "",
        tasks=tasks,
    )


# ---------------------------------------------------------------------------
# DB operations (previously in store/skills.py)
# ---------------------------------------------------------------------------


async def _db_list_skills() -> list[SkillRow]:
    async with async_session() as session:
        result = await session.execute(select(SkillRow))
        return list(result.scalars().all())


async def _db_get_skill(name: str) -> SkillRow:
    async with async_session() as session:
        row = (
            await session.execute(select(SkillRow).where(SkillRow.name == name))
        ).scalar_one_or_none()
    if not row:
        raise KeyError(f"Skill '{name}' not found")
    return row


async def _db_upsert_skill(
    *,
    name: str,
    version: str = "1.0.0",
    description: str = "",
    tags: list[str] | None = None,
    capabilities: list[str] | None = None,
    operations: list[str] | None = None,
    manifest: str = "",
    advertise: str = "",
) -> SkillRow:
    async with async_session() as session:
        existing = (
            await session.execute(select(SkillRow).where(SkillRow.name == name))
        ).scalar_one_or_none()
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


async def _db_delete_skill(name: str) -> None:
    async with async_session() as session:
        row = (
            await session.execute(select(SkillRow).where(SkillRow.name == name))
        ).scalar_one_or_none()
        if not row:
            raise KeyError(f"Skill '{name}' not found")
        await session.delete(row)
        await session.commit()


# ---------------------------------------------------------------------------
# Public API (previously in skills_registry.py)
# ---------------------------------------------------------------------------


async def create_skill(skill: SkillDefinition) -> None:
    manifest = json.dumps({
        "mcp_servers": [s.model_dump() for s in skill.mcp_servers],
        "tasks": [t.model_dump() for t in skill.tasks],
        "prompt_fragment": skill.prompt_fragment,
    })
    await _db_upsert_skill(
        name=skill.name,
        version=skill.version,
        description=skill.description,
        tags=skill.tags,
        manifest=manifest,
        advertise=skill.description[:200],
    )


async def get_skill(name: str) -> SkillDefinition:
    row = await _db_get_skill(name)
    return _row_to_skill(row)


async def list_skills() -> list[SkillDefinition]:
    rows = await _db_list_skills()
    return [_row_to_skill(r) for r in rows]


async def update_skill(skill: SkillDefinition) -> None:
    await create_skill(skill)


async def delete_skill(name: str, force: bool = False) -> None:
    await _db_delete_skill(name)

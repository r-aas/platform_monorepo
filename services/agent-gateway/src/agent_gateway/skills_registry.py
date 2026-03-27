"""Skills registry — CRUD operations backed by PostgreSQL."""

from __future__ import annotations

from agent_gateway.models import EvaluationRef, MCPServerRef, SkillDefinition, TaskDefinition
from agent_gateway.store.skills import delete_skill as _db_delete_skill
from agent_gateway.store.skills import get_skill as _db_get_skill
from agent_gateway.store.skills import list_skills as _db_list_skills
from agent_gateway.store.skills import upsert_skill as _db_upsert_skill


def _row_to_skill(row) -> SkillDefinition:
    """Convert a SkillRow to a SkillDefinition."""
    # Try to parse structured data from manifest JSON or fallback to simple fields
    mcp_servers = []
    tasks = []

    # If manifest contains structured JSON, parse it
    if row.manifest:
        import json
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


def create_skill(skill: SkillDefinition) -> None:
    """Create a new skill — sync wrapper for backward compat."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_create_skill_async(skill))


async def _create_skill_async(skill: SkillDefinition) -> None:
    import json
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


def get_skill(name: str) -> SkillDefinition:
    """Get a skill by name — sync wrapper for backward compat."""
    import asyncio
    loop = asyncio.get_event_loop()
    row = loop.run_until_complete(_db_get_skill(name))
    return _row_to_skill(row)


def list_skills() -> list[SkillDefinition]:
    """List all skills — sync wrapper for backward compat."""
    import asyncio
    loop = asyncio.get_event_loop()
    rows = loop.run_until_complete(_db_list_skills())
    return [_row_to_skill(r) for r in rows]


def update_skill(skill: SkillDefinition) -> None:
    """Update a skill — sync wrapper."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_create_skill_async(skill))


def delete_skill(name: str, force: bool = False) -> None:
    """Delete a skill."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_db_delete_skill(name))

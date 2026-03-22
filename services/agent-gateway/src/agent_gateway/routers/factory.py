"""Factory health router — F.01.

Exposes GET /factory/health summarising what the agent-gateway factory has built:
  - agents registered (MLflow prompt registry)
  - skills registered (MLflow model registry)
  - MCP tools indexed (in-process ToolIndex)
  - eval datasets present on disk
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from agent_gateway.mcp_discovery import get_tool_index
from agent_gateway.registry import list_agents
from agent_gateway.skills_registry import list_skills

router = APIRouter(prefix="/factory", tags=["factory"])


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _scan_eval_datasets(skills_eval_dir: Path) -> dict[str, list[str]]:
    """Return {skill_name: [task_name, ...]} for all JSON eval datasets found."""
    datasets: dict[str, list[str]] = {}
    if not skills_eval_dir.is_dir():
        return datasets
    for skill_dir in skills_eval_dir.iterdir():
        if skill_dir.is_dir():
            tasks = sorted(f.stem for f in skill_dir.glob("*.json"))
            if tasks:
                datasets[skill_dir.name] = tasks
    return datasets


def compute_health_status(agents: int, skills: int, mcp_tools: int) -> str:
    if agents > 0 and skills > 0:
        return "healthy"
    if agents == 0 and skills == 0:
        return "degraded"
    return "partial"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/health")
async def factory_health() -> JSONResponse:
    from agent_gateway.config import settings

    agents_loaded = 0
    try:
        agents = await list_agents()
        agents_loaded = len(agents)
    except Exception:
        pass

    skills_loaded = 0
    try:
        skills = await asyncio.to_thread(list_skills)
        skills_loaded = len(skills)
    except Exception:
        pass

    mcp_tools_indexed = 0
    try:
        index = get_tool_index()
        if index:
            mcp_tools_indexed = len(index.tools)
    except Exception:
        pass

    skills_eval_dir = Path(settings.skills_dir) / "eval"
    eval_datasets = _scan_eval_datasets(skills_eval_dir)
    eval_datasets_found = sum(len(v) for v in eval_datasets.values())

    status = compute_health_status(agents_loaded, skills_loaded, mcp_tools_indexed)

    return JSONResponse(
        {
            "status": status,
            "agents_loaded": agents_loaded,
            "skills_loaded": skills_loaded,
            "mcp_tools_indexed": mcp_tools_indexed,
            "eval_datasets_found": eval_datasets_found,
            "eval_datasets": eval_datasets,
        }
    )

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

from agent_gateway.benchmark.gap_analysis import (
    analyze_skill_gaps,
    find_defined_skills,
    find_referenced_skills,
)
from agent_gateway.benchmark.optimizer import optimize_skill_prompt
from agent_gateway.benchmark.regression import detect_regression, get_run_scores
from agent_gateway.mcp_discovery import get_tool_index
from agent_gateway.registry import list_agents
from agent_gateway.skills_registry import list_skills

router = APIRouter(prefix="/factory", tags=["factory"])


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def scan_skill_yamls(skills_dir: Path) -> list[Path]:
    """Return all *.yaml files in skills_dir. Returns [] if dir does not exist."""
    if not skills_dir.is_dir():
        return []
    return sorted(skills_dir.glob("*.yaml"))


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


@router.get("/regression")
async def factory_regression() -> JSONResponse:
    """Check all eval datasets for pass_rate regressions vs. historical MLflow runs."""
    import mlflow

    from agent_gateway.config import settings

    skills_eval_dir = Path(settings.skills_dir) / "eval"
    eval_datasets = _scan_eval_datasets(skills_eval_dir)

    client = mlflow.MlflowClient(settings.mlflow_tracking_uri)
    checks = []
    for skill_name, tasks in sorted(eval_datasets.items()):
        for task_name in tasks:
            experiment_name = f"eval:*:{skill_name}:{task_name}"
            scores = get_run_scores(client, experiment_name)
            result = detect_regression(scores, skill=skill_name, task=task_name)
            if result is None:
                checks.append(
                    {
                        "skill": skill_name,
                        "task": task_name,
                        "status": "insufficient_data",
                        "run_count": len(scores),
                        "is_regressed": False,
                    }
                )
            else:
                checks.append(
                    {
                        "skill": skill_name,
                        "task": task_name,
                        "status": "regressed" if result.is_regressed else "ok",
                        "is_regressed": result.is_regressed,
                        "current_score": result.current_score,
                        "baseline_score": result.baseline_score,
                        "drop_amount": result.drop_amount,
                        "run_count": result.run_count,
                    }
                )

    regressions_found = sum(1 for c in checks if c["is_regressed"])
    return JSONResponse(
        {
            "regressions_found": regressions_found,
            "total_checked": len(checks),
            "checks": checks,
        }
    )


@router.get("/gaps")
async def factory_gaps() -> JSONResponse:
    """Identify skill coverage gaps — missing skills referenced by agents, unused skills."""
    agents: list = []
    try:
        agents = await list_agents()
    except Exception:
        pass

    skills: list = []
    try:
        skills = await asyncio.to_thread(list_skills)
    except Exception:
        pass

    referenced = find_referenced_skills(agents)
    defined = find_defined_skills(skills)
    result = analyze_skill_gaps(referenced, defined)

    return JSONResponse(
        {
            "coverage_ratio": result.coverage_ratio,
            "missing_skills": sorted(result.missing_skills),
            "unused_skills": sorted(result.unused_skills),
            "covered_skills": sorted(result.covered_skills),
        }
    )


@router.get("/evolve")
async def factory_evolve() -> JSONResponse:
    """Run prompt optimizer across all skills; return improvement suggestions sorted by gain."""
    from agent_gateway.config import settings

    skills_dir = Path(settings.skills_dir)
    datasets_root = skills_dir / "eval"
    yaml_paths = scan_skill_yamls(skills_dir)

    results: list[dict] = []
    for skill_path in yaml_paths:
        try:
            result = optimize_skill_prompt(skill_path, datasets_root)
            results.append(result)
        except Exception:
            pass

    results.sort(key=lambda r: r["improvement"], reverse=True)

    return JSONResponse(
        {
            "skills_analyzed": len(results),
            "results": results,
        }
    )

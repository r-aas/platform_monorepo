"""Factory health router — F.01.

Exposes GET /factory/health summarising what the agent-gateway factory has built:
  - agents registered (MLflow prompt registry)
  - skills registered (MLflow model registry)
  - MCP tools indexed (in-process ToolIndex)
  - eval datasets present on disk

Also exposes POST /factory/benchmark/compare for runtime comparison.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from agent_gateway.agent_lookup import list_agents
from agent_gateway.benchmark.gap_analysis import (
    analyze_skill_gaps,
    find_defined_skills,
    find_referenced_skills,
)
from agent_gateway.benchmark.optimizer import optimize_skill_prompt
from agent_gateway.benchmark.regression import detect_regression, get_run_scores
from agent_gateway.mcp_discovery import get_tool_index
from agent_gateway.skill_lookup import list_skills

logger = logging.getLogger(__name__)

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
        skills = await list_skills()
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
        skills = await list_skills()
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


# ---------------------------------------------------------------------------
# Runtime Benchmarking — same task, different runtimes
# ---------------------------------------------------------------------------


async def _benchmark_one_runtime(
    agent_name: str,
    runtime_name: str,
    cases: list[dict],
    gateway_url: str,
) -> dict[str, Any]:
    """Run all eval cases against a specific agent/runtime combination.

    Creates a temporary agent variant '{agent}-bench-{runtime}' with the
    specified runtime, runs cases, then returns aggregate results.
    """
    from agent_gateway.agent_lookup import _db_get_agent, upsert_agent

    # Get the base agent spec
    try:
        base_row = await _db_get_agent(agent_name)
    except KeyError:
        return {"runtime": runtime_name, "error": f"Agent '{agent_name}' not found"}

    # Create temporary benchmark variant with different runtime
    bench_name = f"{agent_name}-bench-{runtime_name}"
    await upsert_agent(
        name=bench_name,
        version=base_row.version or "0.1.0",
        spec=base_row.spec or {},
        system_prompt=base_row.system_prompt or "",
        capabilities=base_row.capabilities or [],
        skills=base_row.skills or [],
        runtime=runtime_name,
        tags=["benchmark", "ephemeral"],
    )

    results: list[dict] = []
    total_latency = 0.0
    passed = 0

    for case in cases:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{gateway_url}/v1/chat/completions",
                    json={
                        "model": f"agent:{bench_name}",
                        "messages": [{"role": "user", "content": case["input"]}],
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                output = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as exc:
            output = f"ERROR: {exc}"

        latency = time.monotonic() - t0
        total_latency += latency

        # Check expected strings
        output_lower = output.lower()
        case_passed = all(
            exp.lower() in output_lower
            for exp in case.get("expected_output_contains", [])
        )
        if case_passed:
            passed += 1

        results.append({
            "id": case["id"],
            "passed": case_passed,
            "latency": round(latency, 2),
        })

    total = len(cases) or 1
    return {
        "runtime": runtime_name,
        "agent_variant": bench_name,
        "total_cases": len(cases),
        "passed": passed,
        "pass_rate": round(passed / total, 3),
        "avg_latency_s": round(total_latency / total, 2),
        "total_latency_s": round(total_latency, 2),
        "cases": results,
    }


@router.post("/benchmark/compare")
async def benchmark_compare(data: dict[str, Any]) -> JSONResponse:
    """Compare agent performance across runtimes using the same eval dataset.

    Request body:
        agent: str — base agent name
        skill: str — skill name (for dataset lookup)
        task: str — task name (for dataset lookup)
        runtimes: list[str] — runtimes to compare (e.g. ["n8n", "http", "claude-code"])

    Returns a comparison table with pass_rate and latency per runtime.
    """
    from agent_gateway.config import settings

    agent_name = data.get("agent", "")
    skill_name = data.get("skill", "")
    task_name = data.get("task", "")
    runtimes = data.get("runtimes", [])

    if not agent_name or not skill_name or not task_name:
        return JSONResponse(
            status_code=400,
            content={"error": "agent, skill, and task are required"},
        )
    if not runtimes:
        return JSONResponse(
            status_code=400,
            content={"error": "runtimes list is required (e.g. ['n8n', 'http'])"},
        )

    # Load eval dataset
    dataset_path = Path(settings.skills_dir) / "eval" / skill_name / f"{task_name}.json"
    if not dataset_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": f"No eval dataset at {skill_name}/{task_name}.json"},
        )

    import json
    cases = json.loads(dataset_path.read_text()).get("cases", [])
    if not cases:
        return JSONResponse(
            status_code=422,
            content={"error": "Dataset has no test cases"},
        )

    gateway_url = getattr(settings, "gateway_external_url", "") or "http://localhost:8000"

    # Run benchmarks concurrently across runtimes
    tasks = [
        _benchmark_one_runtime(agent_name, rt, cases, gateway_url)
        for rt in runtimes
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    comparison = []
    for r in results:
        if isinstance(r, Exception):
            comparison.append({"runtime": "unknown", "error": str(r)})
        else:
            comparison.append(r)

    # Sort by pass_rate desc, then latency asc
    comparison.sort(key=lambda x: (-x.get("pass_rate", 0), x.get("avg_latency_s", 999)))

    return JSONResponse({
        "agent": agent_name,
        "skill": skill_name,
        "task": task_name,
        "runtimes_compared": len(runtimes),
        "comparison": comparison,
    })

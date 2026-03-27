"""Sandbox runtime endpoints — create, monitor, and manage sandbox Jobs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from agent_gateway.models import AgentRunConfig
from agent_gateway.runtimes.sandbox import (
    cleanup_completed_jobs,
    create_sandbox_job,
    delete_sandbox_job,
    ensure_warm_pool,
    get_sandbox_artifacts,
    get_sandbox_logs,
    get_sandbox_result,
    get_sandbox_status,
    list_sandbox_jobs,
    read_sandbox_artifact,
)

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


@router.post("/jobs")
async def launch_sandbox(data: dict[str, Any]):
    """Launch a sandbox Job with a task description."""
    message = data.get("message") or data.get("task", "")
    if not message:
        raise HTTPException(400, "message or task is required")

    system_prompt = data.get("system_prompt", (
        "You are a software engineer working in an isolated sandbox environment. "
        "You have full filesystem access to /home/agent/workspace. "
        "Complete the assigned task and print the result as JSON on the last line of stdout."
    ))

    config = AgentRunConfig(
        system_prompt=system_prompt,
        message=message,
        agent_params=data.get("params", {}),
    )

    workspace_pvc = data.get("workspace_pvc", False)
    job_name = await create_sandbox_job(config, workspace_pvc=workspace_pvc)
    return {"job_name": job_name, "status": "created"}


@router.get("/jobs")
async def list_jobs():
    """List all sandbox Jobs."""
    try:
        jobs = await list_sandbox_jobs()
        return {"jobs": jobs, "count": len(jobs)}
    except Exception as e:
        raise HTTPException(500, f"Failed to list jobs: {e}")


@router.get("/jobs/{job_name}")
async def sandbox_status(job_name: str):
    """Get the status of a sandbox Job."""
    try:
        return await get_sandbox_status(job_name)
    except Exception as e:
        raise HTTPException(404, f"Job not found: {e}")


@router.get("/jobs/{job_name}/logs")
async def sandbox_logs(job_name: str):
    """Get logs from a sandbox Job."""
    try:
        logs = await get_sandbox_logs(job_name)
        return {"job_name": job_name, "logs": logs}
    except Exception as e:
        raise HTTPException(404, f"Job not found: {e}")


@router.get("/jobs/{job_name}/result")
async def sandbox_result(job_name: str):
    """Get the result from a completed sandbox Job."""
    try:
        status = await get_sandbox_status(job_name)
        if status["status"] != "completed":
            raise HTTPException(409, f"Job is {status['status']}, not completed")
        result = await get_sandbox_result(job_name)
        return {"job_name": job_name, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(404, f"Job not found: {e}")


@router.get("/jobs/{job_name}/artifacts")
async def sandbox_artifacts(job_name: str, path: str = "."):
    """List files in a sandbox Job's workspace."""
    try:
        artifacts = await get_sandbox_artifacts(job_name, path)
        return {"job_name": job_name, "path": path, "artifacts": artifacts}
    except Exception as e:
        raise HTTPException(404, f"Job not found: {e}")


@router.get("/jobs/{job_name}/artifacts/{path:path}")
async def sandbox_artifact_content(job_name: str, path: str):
    """Read a file from a sandbox Job's workspace."""
    try:
        content = await read_sandbox_artifact(job_name, path)
        if not content:
            raise HTTPException(404, f"File not found: {path}")
        return {"job_name": job_name, "path": path, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(404, f"Job not found: {e}")


@router.delete("/jobs/{job_name}")
async def cancel_sandbox(job_name: str):
    """Delete/cancel a sandbox Job and its resources."""
    try:
        await delete_sandbox_job(job_name)
        return {"job_name": job_name, "status": "deleted"}
    except Exception as e:
        raise HTTPException(404, f"Job not found: {e}")


@router.post("/pool")
async def manage_warm_pool(data: dict[str, Any] | None = None):
    """Ensure the warm pool exists with the desired replica count."""
    pool_size = (data or {}).get("size")
    ready = await ensure_warm_pool(pool_size)
    return {"pool_size": pool_size, "ready_replicas": ready}


@router.post("/cleanup")
async def cleanup_jobs(data: dict[str, Any] | None = None):
    """Clean up completed sandbox Jobs older than max_age_seconds."""
    max_age = (data or {}).get("max_age_seconds", 3600)
    cleaned = await cleanup_completed_jobs(max_age)
    return {"cleaned": cleaned}

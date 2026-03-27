"""Sandbox runtime endpoints — create, monitor, and manage sandbox Jobs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from agent_gateway.models import AgentRunConfig
from agent_gateway.runtimes.sandbox import (
    create_sandbox_job,
    delete_sandbox_job,
    get_sandbox_logs,
    get_sandbox_result,
    get_sandbox_status,
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

    job_name = await create_sandbox_job(config)
    return {"job_name": job_name, "status": "created"}


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


@router.delete("/jobs/{job_name}")
async def cancel_sandbox(job_name: str):
    """Delete/cancel a sandbox Job and its resources."""
    try:
        await delete_sandbox_job(job_name)
        return {"job_name": job_name, "status": "deleted"}
    except Exception as e:
        raise HTTPException(404, f"Job not found: {e}")

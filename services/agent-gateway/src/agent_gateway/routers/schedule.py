"""Scheduled agent jobs — create k8s CronJobs for recurring agent execution.

Enables agents to run on a schedule (e.g., nightly evals, periodic maintenance,
continuous improvement tasks). Each scheduled job:
1. Resolves agent + skills from the registry
2. Converts to runtime-specific workspace via RuntimeAdapter
3. Creates a k8s CronJob that launches the agent on the schedule
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from agent_gateway.composer import compose
from agent_gateway.config import settings
from agent_gateway.registry import get_agent
from agent_gateway.runtimes.adapter import get_adapter
from agent_gateway.skills_registry import get_skill

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedule", tags=["schedule"])

# Lazy k8s client
_k8s_loaded = False
_batch_v1 = None
_core_v1 = None


def _ensure_k8s():
    global _k8s_loaded, _batch_v1, _core_v1
    if _k8s_loaded:
        return
    from kubernetes import client, config as k8s_config
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    _batch_v1 = client.BatchV1Api()
    _core_v1 = client.CoreV1Api()
    _k8s_loaded = True


@router.post("/jobs")
async def create_scheduled_job(data: dict[str, Any]):
    """Create a scheduled (CronJob) agent execution.

    Body:
        agent: str — agent name from registry
        schedule: str — cron expression (e.g., "0 2 * * *" for 2am daily)
        message: str — task message
        runtime: str — override runtime (default: agent's configured runtime)
        params: dict — agent parameters
    """
    agent_name = data.get("agent", "")
    schedule = data.get("schedule", "")
    message = data.get("message", "")

    if not agent_name:
        raise HTTPException(400, "agent is required")
    if not schedule:
        raise HTTPException(400, "schedule (cron expression) is required")
    if not message:
        raise HTTPException(400, "message is required")

    # Resolve agent from registry
    try:
        agent = await get_agent(agent_name)
    except KeyError:
        raise HTTPException(404, f"Agent '{agent_name}' not found")

    # Resolve skills
    resolved_skills = []
    for skill_name in agent.skills:
        try:
            resolved_skills.append(await get_skill(skill_name))
        except (KeyError, Exception):
            logger.warning("Skill '%s' not found — skipping", skill_name)

    # Compose runtime-agnostic config
    run_config = compose(
        agent=agent,
        skills=resolved_skills,
        message=message,
        params=data.get("params", {}),
    )

    # Override runtime if specified
    runtime_name = data.get("runtime", agent.runtime)

    # Convert to workspace via adapter
    adapter = get_adapter(runtime_name)
    workspace = adapter.from_config(run_config)

    # Create k8s CronJob
    _ensure_k8s()
    job_id = str(uuid.uuid4())[:8]
    cron_name = f"agent-{agent_name}-{job_id}"
    cm_name = f"agent-ws-{agent_name}-{job_id}"
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    # Pack workspace files into ConfigMap
    cm = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": cm_name,
            "namespace": ns,
            "labels": {
                "app.kubernetes.io/managed-by": "agent-gateway",
                "app.kubernetes.io/component": "scheduled-agent",
                "agent-name": agent_name,
            },
        },
        "data": workspace.files,
    }
    await loop.run_in_executor(
        None, _core_v1.create_namespaced_config_map, ns, cm,
    )

    # Determine container image based on runtime
    image_map = {
        "claude-code": settings.claude_code_image,
        "sandbox": settings.sandbox_image,
    }
    image = image_map.get(runtime_name, settings.sandbox_image)

    # Build env vars
    env_vars = [{"name": k, "value": v} for k, v in workspace.env.items()]
    env_vars.append({"name": "TASK_MESSAGE", "value": message})

    # CronJob manifest
    cronjob = {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {
            "name": cron_name,
            "namespace": ns,
            "labels": {
                "app.kubernetes.io/managed-by": "agent-gateway",
                "app.kubernetes.io/component": "scheduled-agent",
                "agent-name": agent_name,
            },
        },
        "spec": {
            "schedule": schedule,
            "concurrencyPolicy": "Forbid",
            "successfulJobsHistoryLimit": 3,
            "failedJobsHistoryLimit": 3,
            "jobTemplate": {
                "spec": {
                    "ttlSecondsAfterFinished": 3600,
                    "backoffLimit": 0,
                    "activeDeadlineSeconds": settings.sandbox_timeout,
                    "template": {
                        "metadata": {
                            "labels": {
                                "app.kubernetes.io/component": "scheduled-agent",
                                "agent-name": agent_name,
                            },
                        },
                        "spec": {
                            "restartPolicy": "Never",
                            "serviceAccountName": settings.sandbox_service_account,
                            "containers": [
                                {
                                    "name": "agent",
                                    "image": image,
                                    "imagePullPolicy": "IfNotPresent",
                                    "env": env_vars,
                                    "volumeMounts": [
                                        {
                                            "name": "workspace",
                                            "mountPath": "/workspace/.claude-config",
                                            "readOnly": True,
                                        },
                                    ],
                                    "resources": {
                                        "requests": {"cpu": "500m", "memory": "512Mi"},
                                        "limits": {
                                            "cpu": settings.sandbox_cpu_limit,
                                            "memory": settings.sandbox_memory_limit,
                                        },
                                    },
                                },
                            ],
                            "volumes": [
                                {
                                    "name": "workspace",
                                    "configMap": {"name": cm_name},
                                },
                            ],
                        },
                    },
                },
            },
        },
    }

    await loop.run_in_executor(
        None, _batch_v1.create_namespaced_cron_job, ns, cronjob,
    )

    logger.info("Created CronJob %s for agent %s: %s", cron_name, agent_name, schedule)
    return {
        "cronjob_name": cron_name,
        "agent": agent_name,
        "runtime": runtime_name,
        "schedule": schedule,
        "message": message,
        "status": "created",
    }


@router.get("/jobs")
async def list_scheduled_jobs():
    """List all scheduled agent jobs."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    cronjobs = await loop.run_in_executor(
        None,
        lambda: _batch_v1.list_namespaced_cron_job(
            ns, label_selector="app.kubernetes.io/component=scheduled-agent",
        ),
    )

    results = []
    for cj in cronjobs.items:
        labels = cj.metadata.labels or {}
        results.append({
            "name": cj.metadata.name,
            "agent": labels.get("agent-name", ""),
            "schedule": cj.spec.schedule,
            "suspended": cj.spec.suspend or False,
            "last_schedule": cj.status.last_schedule_time.isoformat() if cj.status.last_schedule_time else None,
            "active_jobs": len(cj.status.active or []),
        })

    return {"jobs": results, "count": len(results)}


@router.delete("/jobs/{name}")
async def delete_scheduled_job(name: str):
    """Delete a scheduled agent job and its ConfigMap."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    try:
        await loop.run_in_executor(
            None,
            lambda: _batch_v1.delete_namespaced_cron_job(
                name, ns, propagation_policy="Foreground",
            ),
        )
    except Exception as e:
        raise HTTPException(404, f"CronJob not found: {e}")

    # Clean up ConfigMap (best effort)
    try:
        cm_name = name.replace("agent-", "agent-ws-", 1)
        await loop.run_in_executor(
            None, _core_v1.delete_namespaced_config_map, cm_name, ns,
        )
    except Exception:
        pass

    return {"name": name, "status": "deleted"}


@router.post("/jobs/{name}/trigger")
async def trigger_scheduled_job(name: str):
    """Manually trigger a scheduled job (run now, outside schedule)."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    try:
        cj = await loop.run_in_executor(
            None, _batch_v1.read_namespaced_cron_job, name, ns,
        )
    except Exception:
        raise HTTPException(404, f"CronJob '{name}' not found")

    # Create a one-off Job from the CronJob template using the k8s client objects
    from kubernetes import client as k8s_client

    job_name = f"{name}-manual-{str(uuid.uuid4())[:4]}"
    job = k8s_client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=k8s_client.V1ObjectMeta(
            name=job_name,
            namespace=ns,
            labels=cj.spec.job_template.metadata.labels if cj.spec.job_template.metadata else {},
        ),
        spec=cj.spec.job_template.spec,
    )

    await loop.run_in_executor(
        None, _batch_v1.create_namespaced_job, ns, job,
    )

    return {"job_name": job_name, "cronjob": name, "status": "triggered"}


@router.put("/jobs/{name}/suspend")
async def suspend_scheduled_job(name: str, data: dict[str, Any] | None = None):
    """Suspend or resume a scheduled job."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()
    suspend = (data or {}).get("suspend", True)

    try:
        cj = await loop.run_in_executor(
            None, _batch_v1.read_namespaced_cron_job, name, ns,
        )
        cj.spec.suspend = suspend
        await loop.run_in_executor(
            None, _batch_v1.replace_namespaced_cron_job, name, ns, cj,
        )
    except Exception as e:
        raise HTTPException(404, f"CronJob not found: {e}")

    return {"name": name, "suspended": suspend}

"""Sandbox runtime — runs agents in ephemeral k8s Jobs.

Creates a k8s Job with:
- Task ConfigMap (prompt, config)
- Resource limits (CPU, memory)
- NetworkPolicy (allow LiteLLM + MCP only)
- TTL auto-cleanup after completion

Results are read from the Job's logs (JSON on last line).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from agent_gateway.config import settings
from agent_gateway.models import AgentRunConfig
from agent_gateway.runtimes.base import Runtime

logger = logging.getLogger(__name__)

# Lazy k8s client — only imported when sandbox runtime is actually used
_k8s_loaded = False
_core_v1 = None
_batch_v1 = None


def _ensure_k8s():
    """Load kubernetes client on first use."""
    global _k8s_loaded, _core_v1, _batch_v1
    if _k8s_loaded:
        return
    try:
        from kubernetes import client, config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        _core_v1 = client.CoreV1Api()
        _batch_v1 = client.BatchV1Api()
        _k8s_loaded = True
    except Exception as e:
        raise RuntimeError(f"Failed to initialize k8s client: {e}") from e


@dataclass
class SandboxJob:
    """Tracks a running sandbox Job."""

    job_name: str
    namespace: str
    config_map_name: str
    created_at: float = field(default_factory=time.monotonic)


# In-memory registry of active sandbox jobs
_active_jobs: dict[str, SandboxJob] = {}


def _build_job_manifest(
    job_name: str,
    config_map_name: str,
    namespace: str,
) -> dict:
    """Build the k8s Job manifest."""
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "agent-gateway",
                "app.kubernetes.io/component": "sandbox",
            },
        },
        "spec": {
            "ttlSecondsAfterFinished": 300,
            "backoffLimit": 0,
            "activeDeadlineSeconds": settings.sandbox_timeout,
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/component": "sandbox",
                        "sandbox-job": job_name,
                    },
                },
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": settings.sandbox_service_account,
                    "containers": [
                        {
                            "name": "agent",
                            "image": settings.sandbox_image,
                            "imagePullPolicy": "IfNotPresent",
                            "env": [
                                {
                                    "name": "OPENAI_BASE_URL",
                                    "value": f"{settings.litellm_base_url}/v1",
                                },
                                {
                                    "name": "OPENAI_API_KEY",
                                    "value": settings.litellm_api_key or "sk-litellm-mewtwo-local",
                                },
                                {
                                    "name": "OPENAI_MODEL",
                                    "value": "qwen2.5:14b",
                                },
                                {
                                    "name": "MCP_PROXY_URL",
                                    "value": "http://genai-agent-gateway.genai.svc.cluster.local:8000/mcp/proxy",
                                },
                            ],
                            "volumeMounts": [
                                {
                                    "name": "task",
                                    "mountPath": "/task",
                                    "readOnly": True,
                                },
                            ],
                            "resources": {
                                "requests": {
                                    "cpu": "500m",
                                    "memory": "1Gi",
                                },
                                "limits": {
                                    "cpu": settings.sandbox_cpu_limit,
                                    "memory": settings.sandbox_memory_limit,
                                },
                            },
                        },
                    ],
                    "volumes": [
                        {
                            "name": "task",
                            "configMap": {"name": config_map_name},
                        },
                    ],
                },
            },
        },
    }


def _build_config_map(name: str, namespace: str, task_config: dict) -> dict:
    """Build a ConfigMap with the task definition."""
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "agent-gateway",
                "app.kubernetes.io/component": "sandbox",
            },
        },
        "data": {
            "config.json": json.dumps(task_config, indent=2),
        },
    }


def _build_network_policy(job_name: str, namespace: str) -> dict:
    """Build a NetworkPolicy that restricts sandbox egress."""
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"sandbox-{job_name}",
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "agent-gateway",
                "app.kubernetes.io/component": "sandbox",
            },
        },
        "spec": {
            "podSelector": {
                "matchLabels": {"sandbox-job": job_name},
            },
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": namespace},
                            },
                        },
                    ],
                    "ports": [
                        {"protocol": "TCP", "port": 4000},   # LiteLLM
                        {"protocol": "TCP", "port": 8000},   # Agent Gateway / MCP
                        {"protocol": "TCP", "port": 3000},   # MCP servers
                    ],
                },
                {
                    "to": [{}],
                    "ports": [
                        {"protocol": "UDP", "port": 53},     # DNS
                    ],
                },
            ],
        },
    }


async def create_sandbox_job(run_config: AgentRunConfig) -> str:
    """Create a sandbox k8s Job and return its name."""
    _ensure_k8s()

    job_id = str(uuid.uuid4())[:8]
    job_name = f"sandbox-{job_id}"
    cm_name = f"sandbox-task-{job_id}"
    ns = settings.sandbox_namespace

    task_config = {
        "system_prompt": run_config.system_prompt,
        "message": run_config.message,
        "mcp_servers": [
            {"name": s.name, "url": s.url} for s in run_config.mcp_servers
        ],
        "allowed_tools": run_config.allowed_tools,
        "agent_params": run_config.agent_params,
    }

    # Create resources
    cm = _build_config_map(cm_name, ns, task_config)
    job = _build_job_manifest(job_name, cm_name, ns)
    netpol = _build_network_policy(job_name, ns)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, _core_v1.create_namespaced_config_map, ns, cm
    )
    await loop.run_in_executor(
        None,
        lambda: _core_v1.create_namespaced_network_policy(ns, netpol) if hasattr(_core_v1, 'create_namespaced_network_policy') else None,
    )

    from kubernetes import client
    net_v1 = client.NetworkingV1Api()
    try:
        await loop.run_in_executor(
            None, net_v1.create_namespaced_network_policy, ns, netpol
        )
    except Exception as e:
        logger.warning("Failed to create NetworkPolicy (non-fatal): %s", e)

    await loop.run_in_executor(
        None, _batch_v1.create_namespaced_job, ns, job
    )

    _active_jobs[job_name] = SandboxJob(
        job_name=job_name, namespace=ns, config_map_name=cm_name,
    )
    logger.info("Created sandbox job %s in %s", job_name, ns)
    return job_name


async def get_sandbox_status(job_name: str) -> dict:
    """Get the status of a sandbox Job."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()
    job = await loop.run_in_executor(
        None, _batch_v1.read_namespaced_job_status, job_name, ns,
    )

    status = "running"
    if job.status.succeeded and job.status.succeeded > 0:
        status = "completed"
    elif job.status.failed and job.status.failed > 0:
        status = "failed"
    elif job.status.active and job.status.active > 0:
        status = "running"

    return {
        "job_name": job_name,
        "status": status,
        "start_time": job.status.start_time.isoformat() if job.status.start_time else None,
        "completion_time": job.status.completion_time.isoformat() if job.status.completion_time else None,
    }


async def get_sandbox_logs(job_name: str, follow: bool = False) -> str:
    """Get logs from a sandbox Job's pod."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    # Find the pod for this job
    pods = await loop.run_in_executor(
        None,
        lambda: _core_v1.list_namespaced_pod(
            ns, label_selector=f"job-name={job_name}",
        ),
    )
    if not pods.items:
        return ""

    pod_name = pods.items[0].metadata.name
    logs = await loop.run_in_executor(
        None,
        lambda: _core_v1.read_namespaced_pod_log(pod_name, ns),
    )
    return logs


async def get_sandbox_result(job_name: str) -> dict:
    """Extract the result from a completed sandbox Job.

    The entrypoint writes the result as the last JSON line to stdout.
    """
    logs = await get_sandbox_logs(job_name)
    if not logs:
        return {"error": "No logs available"}

    # Find the last JSON line
    for line in reversed(logs.strip().split("\n")):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"output": logs[-2000:] if len(logs) > 2000 else logs}


async def delete_sandbox_job(job_name: str) -> None:
    """Delete a sandbox Job and its resources."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    from kubernetes import client
    net_v1 = client.NetworkingV1Api()

    # Delete job (propagation=Foreground deletes pods too)
    try:
        await loop.run_in_executor(
            None,
            lambda: _batch_v1.delete_namespaced_job(
                job_name, ns, propagation_policy="Foreground",
            ),
        )
    except Exception as e:
        logger.warning("Failed to delete job %s: %s", job_name, e)

    # Delete ConfigMap
    sandbox = _active_jobs.get(job_name)
    if sandbox:
        try:
            await loop.run_in_executor(
                None, _core_v1.delete_namespaced_config_map, sandbox.config_map_name, ns,
            )
        except Exception:
            pass

    # Delete NetworkPolicy
    try:
        await loop.run_in_executor(
            None, net_v1.delete_namespaced_network_policy, f"sandbox-{job_name}", ns,
        )
    except Exception:
        pass

    _active_jobs.pop(job_name, None)


class SandboxRuntime(Runtime):
    """Runtime that executes agents in isolated k8s Jobs."""

    async def invoke(self, config: AgentRunConfig) -> AsyncIterator[str]:
        """Launch sandbox, poll for completion, yield SSE chunks."""
        job_name = await create_sandbox_job(config)

        # Yield initial status
        yield _sse_chunk(f"Sandbox job {job_name} created, waiting for completion...")

        # Poll for completion
        for _ in range(settings.sandbox_timeout // 5):
            await asyncio.sleep(5)
            status = await get_sandbox_status(job_name)

            if status["status"] == "completed":
                result = await get_sandbox_result(job_name)
                content = result.get("output", result.get("error", json.dumps(result)))
                yield _sse_chunk(content)
                yield _sse_done()
                return

            if status["status"] == "failed":
                logs = await get_sandbox_logs(job_name)
                yield _sse_chunk(f"Sandbox job failed. Logs:\n{logs[-1000:]}")
                yield _sse_done()
                return

        yield _sse_chunk("Sandbox job timed out.")
        yield _sse_done()

    async def invoke_sync(self, config: AgentRunConfig) -> str:
        """Launch sandbox and wait for result."""
        job_name = await create_sandbox_job(config)

        for _ in range(settings.sandbox_timeout // 5):
            await asyncio.sleep(5)
            status = await get_sandbox_status(job_name)

            if status["status"] == "completed":
                result = await get_sandbox_result(job_name)
                return result.get("output", json.dumps(result))

            if status["status"] == "failed":
                logs = await get_sandbox_logs(job_name)
                return f"Sandbox job failed. Logs:\n{logs[-2000:]}"

        return "Sandbox job timed out."


def _sse_chunk(content: str) -> str:
    """Format content as an OpenAI-compatible SSE chunk."""
    chunk = {
        "choices": [
            {
                "delta": {"content": content},
                "index": 0,
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def _sse_done() -> str:
    """Format the final SSE done message."""
    chunk = {
        "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
    }
    return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"

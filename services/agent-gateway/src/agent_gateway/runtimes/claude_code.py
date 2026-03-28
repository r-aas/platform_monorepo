"""Claude Code runtime — runs agents via Claude Code CLI in k8s Jobs.

Uses the RuntimeAdapter to convert AgentRunConfig into a Claude Code
workspace (CLAUDE.md, skills, MCP settings), then launches a k8s Job
with the agent-claude image that executes `claude --print` with the
prepared context.

The agent-claude image has:
- Claude Code CLI (claude-agent-sdk)
- Pre-configured for non-interactive execution
- MCP server access via the gateway proxy
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator

from agent_gateway.config import settings
from agent_gateway.models import AgentRunConfig
from agent_gateway.runtimes.adapter import ClaudeCodeAdapter
from agent_gateway.runtimes.base import Runtime

logger = logging.getLogger(__name__)

# Lazy k8s client
_k8s_loaded = False
_core_v1 = None
_batch_v1 = None


def _ensure_k8s():
    global _k8s_loaded, _core_v1, _batch_v1
    if _k8s_loaded:
        return
    from kubernetes import client, config as k8s_config
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    _core_v1 = client.CoreV1Api()
    _batch_v1 = client.BatchV1Api()
    _k8s_loaded = True


class ClaudeCodeRuntime(Runtime):
    """Runtime that executes agents via Claude Code in k8s Jobs.

    Flow:
    1. ClaudeCodeAdapter converts AgentRunConfig → RuntimeWorkspace
    2. Workspace files are packed into a ConfigMap
    3. k8s Job runs agent-claude image with workspace mounted
    4. Entrypoint writes files, configures MCP, runs `claude --print`
    5. Result is read from Job logs
    """

    def __init__(self):
        self._adapter = ClaudeCodeAdapter()

    async def invoke(self, config: AgentRunConfig) -> AsyncIterator[str]:
        """Launch Claude Code Job, poll for completion, yield SSE chunks."""
        job_name = await self._create_job(config)
        yield _sse_chunk(f"Claude Code job {job_name} created, executing...")

        for _ in range(settings.sandbox_timeout // 5):
            await asyncio.sleep(5)
            status = await self._get_status(job_name)

            if status == "completed":
                result = await self._get_result(job_name)
                yield _sse_chunk(result)
                yield _sse_done()
                return

            if status == "failed":
                logs = await self._get_logs(job_name)
                yield _sse_chunk(f"Claude Code job failed:\n{logs[-1000:]}")
                yield _sse_done()
                return

        yield _sse_chunk("Claude Code job timed out.")
        yield _sse_done()

    async def invoke_sync(self, config: AgentRunConfig) -> str:
        """Launch Claude Code Job and wait for result."""
        job_name = await self._create_job(config)

        for _ in range(settings.sandbox_timeout // 5):
            await asyncio.sleep(5)
            status = await self._get_status(job_name)

            if status == "completed":
                return await self._get_result(job_name)
            if status == "failed":
                logs = await self._get_logs(job_name)
                return f"Claude Code job failed:\n{logs[-2000:]}"

        return "Claude Code job timed out."

    async def _create_job(self, config: AgentRunConfig) -> str:
        """Convert config to workspace and launch a k8s Job."""
        _ensure_k8s()
        workspace = self._adapter.from_config(config)

        job_id = str(uuid.uuid4())[:8]
        job_name = f"claude-{job_id}"
        cm_name = f"claude-ws-{job_id}"
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
                    "app.kubernetes.io/component": "claude-code",
                },
            },
            "data": workspace.files,
        }
        await loop.run_in_executor(
            None, _core_v1.create_namespaced_config_map, ns, cm,
        )

        # Build env vars from workspace + defaults
        env_vars = [
            {"name": "AGENT_NAME", "value": config.agent_name},
            {"name": "SESSION_ID", "value": config.session_id},
            {"name": "TASK_MESSAGE", "value": config.message},
            # MCP proxy for tool access
            {"name": "MCP_PROXY_URL", "value": "http://genai-agent-gateway.genai.svc.cluster.local:8000/mcp/proxy"},
        ]
        # Add any extra env from workspace
        for k, v in workspace.env.items():
            if k not in {"AGENT_NAME", "SESSION_ID"}:
                env_vars.append({"name": k, "value": v})

        # Job manifest
        job = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": job_name,
                "namespace": ns,
                "labels": {
                    "app.kubernetes.io/managed-by": "agent-gateway",
                    "app.kubernetes.io/component": "claude-code",
                },
            },
            "spec": {
                "ttlSecondsAfterFinished": 300,
                "backoffLimit": 0,
                "activeDeadlineSeconds": settings.sandbox_timeout,
                "template": {
                    "metadata": {
                        "labels": {
                            "app.kubernetes.io/component": "claude-code",
                            "claude-job": job_name,
                        },
                    },
                    "spec": {
                        "restartPolicy": "Never",
                        "serviceAccountName": settings.sandbox_service_account,
                        "containers": [
                            {
                                "name": "claude",
                                "image": settings.claude_code_image,
                                "imagePullPolicy": "IfNotPresent",
                                "env": env_vars,
                                "volumeMounts": [
                                    {
                                        "name": "workspace",
                                        "mountPath": "/workspace/.claude-config",
                                        "readOnly": True,
                                    },
                                    {
                                        "name": "claude-creds",
                                        "mountPath": "/secrets/claude",
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
                            {
                                "name": "claude-creds",
                                "secret": {
                                    "secretName": settings.claude_credentials_secret,
                                    "optional": True,
                                },
                            },
                        ],
                    },
                },
            },
        }

        await loop.run_in_executor(
            None, _batch_v1.create_namespaced_job, ns, job,
        )
        logger.info("Created Claude Code job %s for agent %s", job_name, config.agent_name)
        return job_name

    async def _get_status(self, job_name: str) -> str:
        ns = settings.sandbox_namespace
        loop = asyncio.get_event_loop()
        job = await loop.run_in_executor(
            None, _batch_v1.read_namespaced_job_status, job_name, ns,
        )
        if job.status.succeeded and job.status.succeeded > 0:
            return "completed"
        if job.status.failed and job.status.failed > 0:
            return "failed"
        return "running"

    async def _get_logs(self, job_name: str) -> str:
        ns = settings.sandbox_namespace
        loop = asyncio.get_event_loop()
        pods = await loop.run_in_executor(
            None,
            lambda: _core_v1.list_namespaced_pod(
                ns, label_selector=f"job-name={job_name}",
            ),
        )
        if not pods.items:
            return ""
        pod_name = pods.items[0].metadata.name
        return await loop.run_in_executor(
            None, lambda: _core_v1.read_namespaced_pod_log(pod_name, ns),
        )

    async def _get_result(self, job_name: str) -> str:
        """Extract Claude Code output from Job logs."""
        logs = await self._get_logs(job_name)
        if not logs:
            return "No output"

        # Claude --print outputs directly to stdout
        # The entrypoint wraps it in JSON on the last line
        for line in reversed(logs.strip().split("\n")):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    return data.get("output", data.get("result", json.dumps(data)))
                except json.JSONDecodeError:
                    continue

        # If no JSON wrapper, return raw output (Claude --print mode)
        return logs.strip()


def _sse_chunk(content: str) -> str:
    chunk = {
        "choices": [{"delta": {"content": content}, "index": 0, "finish_reason": None}],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def _sse_done() -> str:
    chunk = {
        "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
    }
    return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"

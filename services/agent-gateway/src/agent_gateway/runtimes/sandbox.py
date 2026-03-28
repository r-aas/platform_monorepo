"""Sandbox runtime — runs agents in ephemeral k8s Jobs.

Creates a k8s Job with:
- Task ConfigMap (prompt, config)
- Resource limits (CPU, memory)
- NetworkPolicy (allow LiteLLM + MCP only)
- Optional workspace PVC for artifact persistence
- TTL auto-cleanup after completion

Supports a pre-warmed pod pool via a standby Deployment that keeps
warm pods ready for near-instant job starts.

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
_net_v1 = None


def _ensure_k8s():
    """Load kubernetes client on first use."""
    global _k8s_loaded, _core_v1, _batch_v1, _net_v1
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
        _net_v1 = client.NetworkingV1Api()
        _k8s_loaded = True
    except Exception as e:
        raise RuntimeError(f"Failed to initialize k8s client: {e}") from e


@dataclass
class SandboxJob:
    """Tracks a running sandbox Job."""

    job_name: str
    namespace: str
    config_map_name: str
    pvc_name: str | None = None
    created_at: float = field(default_factory=time.monotonic)


# In-memory registry of active sandbox jobs
_active_jobs: dict[str, SandboxJob] = {}


# ---------------------------------------------------------------------------
# Warm pool management
# ---------------------------------------------------------------------------

WARM_POOL_LABEL = "sandbox-warm-pool"
WARM_POOL_DEPLOYMENT = "sandbox-warm-pool"


async def ensure_warm_pool(pool_size: int | None = None) -> int:
    """Ensure the warm pool Deployment exists with the desired replica count.

    Returns the current ready replica count.
    """
    _ensure_k8s()
    ns = settings.sandbox_namespace
    size = pool_size or settings.sandbox_warm_pool_size
    if size <= 0:
        return 0

    from kubernetes import client

    apps_v1 = client.AppsV1Api()
    loop = asyncio.get_event_loop()

    deployment = _build_warm_pool_deployment(size)

    try:
        existing = await loop.run_in_executor(
            None,
            apps_v1.read_namespaced_deployment,
            WARM_POOL_DEPLOYMENT,
            ns,
        )
        # Update replica count if changed
        if existing.spec.replicas != size:
            existing.spec.replicas = size
            await loop.run_in_executor(
                None,
                apps_v1.replace_namespaced_deployment,
                WARM_POOL_DEPLOYMENT,
                ns,
                existing,
            )
        ready = existing.status.ready_replicas or 0
        return ready
    except Exception:
        # Create new deployment
        try:
            await loop.run_in_executor(
                None,
                apps_v1.create_namespaced_deployment,
                ns,
                deployment,
            )
            logger.info("Created warm pool deployment with %d replicas", size)
            return 0
        except Exception as e:
            logger.warning("Failed to create warm pool (non-fatal): %s", e)
            return 0


async def _claim_warm_pod() -> str | None:
    """Try to claim a warm pod from the pool. Returns pod name or None."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    pods = await loop.run_in_executor(
        None,
        lambda: _core_v1.list_namespaced_pod(
            ns,
            label_selector=f"{WARM_POOL_LABEL}=standby",
            field_selector="status.phase=Running",
        ),
    )

    for pod in pods.items:
        pod_name = pod.metadata.name
        # Try to claim by patching labels
        try:
            await loop.run_in_executor(
                None,
                lambda pn=pod_name: _core_v1.patch_namespaced_pod(
                    pn,
                    ns,
                    {"metadata": {"labels": {WARM_POOL_LABEL: "claimed"}}},
                ),
            )
            logger.info("Claimed warm pod %s", pod_name)
            return pod_name
        except Exception:
            continue

    return None


def _build_warm_pool_deployment(replicas: int) -> dict:
    """Build the warm pool Deployment manifest."""
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": WARM_POOL_DEPLOYMENT,
            "namespace": settings.sandbox_namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "agent-gateway",
                "app.kubernetes.io/component": "sandbox-pool",
            },
        },
        "spec": {
            "replicas": replicas,
            "selector": {
                "matchLabels": {WARM_POOL_LABEL: "standby"},
            },
            "template": {
                "metadata": {
                    "labels": {
                        WARM_POOL_LABEL: "standby",
                        "app.kubernetes.io/component": "sandbox-pool",
                    },
                },
                "spec": {
                    "serviceAccountName": settings.sandbox_service_account,
                    "containers": [
                        {
                            "name": "agent",
                            "image": settings.sandbox_image,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["sleep", "infinity"],
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
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {
                                    "cpu": settings.sandbox_cpu_limit,
                                    "memory": settings.sandbox_memory_limit,
                                },
                            },
                        },
                    ],
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Job manifest builders
# ---------------------------------------------------------------------------


@dataclass
class DevSandboxRequest:
    """Request to create a development sandbox from a git repo."""

    repo: str  # full git URL or short ref like "genai-mlops"
    branch: str = "main"
    setup_command: str = ""  # e.g. "uv sync" or "npm install"
    message: str = ""  # task for the agent to perform in the repo
    system_prompt: str = ""


def _resolve_repo_url(repo: str) -> str:
    """Resolve short repo names to full git URLs."""
    if repo.startswith("http://") or repo.startswith("https://") or repo.startswith("git@"):
        return repo
    # Short ref: resolve against default GitLab host
    host = settings.sandbox_default_git_host
    return f"http://{host}/root/{repo}.git"


def _build_job_manifest(
    job_name: str,
    config_map_name: str,
    namespace: str,
    pvc_name: str | None = None,
    git_repo: str | None = None,
    git_branch: str = "main",
    setup_command: str = "",
) -> dict:
    """Build the k8s Job manifest.

    If git_repo is provided, adds an init container that clones the repo
    into /home/agent/workspace before the main container starts.
    """
    volumes = [
        {"name": "task", "configMap": {"name": config_map_name}},
    ]
    volume_mounts = [
        {"name": "task", "mountPath": "/task", "readOnly": True},
    ]

    # Always create a workspace volume (emptyDir if no PVC)
    if pvc_name:
        volumes.append({"name": "workspace", "persistentVolumeClaim": {"claimName": pvc_name}})
    else:
        volumes.append({"name": "workspace", "emptyDir": {}})
    volume_mounts.append({"name": "workspace", "mountPath": "/home/agent/workspace"})

    init_containers = []
    if git_repo:
        # Add git-credentials volume from k8s secret (optional)
        volumes.append(
            {
                "name": "git-credentials",
                "secret": {"secretName": settings.sandbox_git_secret, "optional": True},
            }
        )

        # Build clone + setup script
        clone_script = (
            "set -e; "
            "if [ -f /git-creds/.git-credentials ]; then "
            "  cp /git-creds/.git-credentials /tmp/.git-credentials && "
            "  git config --global credential.helper 'store --file=/tmp/.git-credentials'; "
            "fi; "
            f"git clone --depth 1 --branch {git_branch} {git_repo} /home/agent/workspace; "
            "cd /home/agent/workspace; "
            "echo '=== repo cloned ===';"
        )
        if setup_command:
            clone_script += f" {setup_command}; echo '=== setup done ===';"

        init_containers.append(
            {
                "name": "git-init",
                "image": "alpine/git:latest",
                "imagePullPolicy": "IfNotPresent",
                "command": ["sh", "-c", clone_script],
                "volumeMounts": [
                    {"name": "workspace", "mountPath": "/home/agent/workspace"},
                    {"name": "git-credentials", "mountPath": "/git-creds", "readOnly": True},
                ],
            }
        )

    spec = {
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
                "volumeMounts": volume_mounts,
                "resources": {
                    "requests": {"cpu": "500m", "memory": "1Gi"},
                    "limits": {
                        "cpu": settings.sandbox_cpu_limit,
                        "memory": settings.sandbox_memory_limit,
                    },
                },
            },
        ],
        "volumes": volumes,
    }

    if init_containers:
        spec["initContainers"] = init_containers

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
            "annotations": {
                **({"sandbox.agent-gateway/repo": git_repo} if git_repo else {}),
                **({"sandbox.agent-gateway/branch": git_branch} if git_repo else {}),
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
                "spec": spec,
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


def _build_network_policy(job_name: str, namespace: str, allow_git: bool = False) -> dict:
    """Build a NetworkPolicy that restricts sandbox egress.

    If allow_git=True, adds egress rules for git clone (HTTP/HTTPS to GitLab
    in the platform namespace + HTTPS to external hosts).
    """
    egress_rules = [
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": namespace},
                    },
                },
            ],
            "ports": [
                {"protocol": "TCP", "port": 4000},  # LiteLLM
                {"protocol": "TCP", "port": 8000},  # Agent Gateway / MCP
                {"protocol": "TCP", "port": 3000},  # MCP servers
            ],
        },
        {
            "to": [{}],
            "ports": [
                {"protocol": "UDP", "port": 53},  # DNS
            ],
        },
    ]

    if allow_git:
        egress_rules.append(
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "platform"},
                        },
                    },
                ],
                "ports": [
                    {"protocol": "TCP", "port": 80},  # GitLab HTTP
                    {"protocol": "TCP", "port": 8181},  # GitLab workhorse
                ],
            }
        )
        # Also allow HTTPS to any (for external repos like GitHub)
        egress_rules.append(
            {
                "to": [{}],
                "ports": [
                    {"protocol": "TCP", "port": 443},  # HTTPS (git clone)
                ],
            }
        )

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
            "egress": egress_rules,
        },
    }


def _build_workspace_pvc(name: str, namespace: str) -> dict:
    """Build a PVC for sandbox workspace storage."""
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "agent-gateway",
                "app.kubernetes.io/component": "sandbox",
            },
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {
                "requests": {"storage": settings.sandbox_workspace_size},
            },
        },
    }


# ---------------------------------------------------------------------------
# Job lifecycle
# ---------------------------------------------------------------------------


async def create_sandbox_job(
    run_config: AgentRunConfig,
    workspace_pvc: bool = False,
    git_repo: str | None = None,
    git_branch: str = "main",
    setup_command: str = "",
) -> str:
    """Create a sandbox k8s Job and return its name.

    If workspace_pvc=True, creates a PVC for persistent workspace storage.
    If git_repo is provided, clones the repo into workspace via init container.
    If warm pool is enabled and a warm pod is available, uses exec-based
    fast path instead of creating a new Job.
    """
    _ensure_k8s()

    job_id = str(uuid.uuid4())[:8]
    job_name = f"sandbox-{job_id}"
    cm_name = f"sandbox-task-{job_id}"
    pvc_name = f"sandbox-ws-{job_id}" if workspace_pvc else None
    ns = settings.sandbox_namespace

    task_config = {
        "system_prompt": run_config.system_prompt,
        "message": run_config.message,
        "mcp_servers": [{"name": getattr(s, "name", ""), "url": s.url} for s in run_config.mcp_servers],
        "allowed_tools": run_config.allowed_tools,
        "agent_params": run_config.agent_params,
    }
    if git_repo:
        task_config["repo"] = git_repo
        task_config["branch"] = git_branch

    loop = asyncio.get_event_loop()

    # Try warm pool fast path (only for non-git jobs — git needs init container)
    if settings.sandbox_warm_pool_size > 0 and not git_repo:
        warm_pod = await _claim_warm_pod()
        if warm_pod:
            return await _exec_on_warm_pod(warm_pod, job_name, task_config, ns)

    # Cold path: create ConfigMap + optional PVC + NetworkPolicy + Job
    cm = _build_config_map(cm_name, ns, task_config)
    await loop.run_in_executor(None, _core_v1.create_namespaced_config_map, ns, cm)

    if pvc_name:
        pvc = _build_workspace_pvc(pvc_name, ns)
        await loop.run_in_executor(None, _core_v1.create_namespaced_persistent_volume_claim, ns, pvc)

    needs_git = git_repo is not None
    netpol = _build_network_policy(job_name, ns, allow_git=needs_git)
    try:
        await loop.run_in_executor(None, _net_v1.create_namespaced_network_policy, ns, netpol)
    except Exception as e:
        logger.warning("Failed to create NetworkPolicy (non-fatal): %s", e)

    job = _build_job_manifest(
        job_name,
        cm_name,
        ns,
        pvc_name,
        git_repo=git_repo,
        git_branch=git_branch,
        setup_command=setup_command,
    )
    await loop.run_in_executor(None, _batch_v1.create_namespaced_job, ns, job)

    _active_jobs[job_name] = SandboxJob(
        job_name=job_name,
        namespace=ns,
        config_map_name=cm_name,
        pvc_name=pvc_name,
    )
    logger.info("Created sandbox job %s in %s (repo=%s)", job_name, ns, git_repo or "none")
    return job_name


async def create_dev_sandbox(req: DevSandboxRequest) -> str:
    """Create a development sandbox pre-loaded with a git repo.

    Convenience wrapper around create_sandbox_job that resolves short repo
    names and sets up a dev-friendly system prompt.
    """
    repo_url = _resolve_repo_url(req.repo)

    system_prompt = req.system_prompt or (
        "You are a software engineer working in an isolated sandbox. "
        f"The repository '{req.repo}' (branch: {req.branch}) has been cloned to /home/agent/workspace. "
        "You have full filesystem access. Explore the repo structure, understand the codebase, "
        "and complete the assigned task. Print results as JSON on the last line of stdout."
    )

    config = AgentRunConfig(
        system_prompt=system_prompt,
        message=req.message or f"Explore the {req.repo} repository and summarize its structure.",
        agent_params={"repo": req.repo, "branch": req.branch},
    )

    return await create_sandbox_job(
        config,
        workspace_pvc=True,
        git_repo=repo_url,
        git_branch=req.branch,
        setup_command=req.setup_command,
    )


async def _exec_on_warm_pod(pod_name: str, job_name: str, task_config: dict, ns: str) -> str:
    """Execute a task on a claimed warm pod via kubectl exec.

    Writes config to /task/config.json in the pod, then runs the entrypoint.
    """
    loop = asyncio.get_event_loop()
    from kubernetes.stream import stream as k8s_stream

    config_json = json.dumps(task_config)

    # Write task config into the pod
    try:
        await loop.run_in_executor(
            None,
            lambda: k8s_stream(
                _core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                ns,
                command=[
                    "sh",
                    "-c",
                    f"mkdir -p /task && cat > /task/config.json << 'ENDCONFIG'\n{config_json}\nENDCONFIG",
                ],
                stderr=True,
                stdout=True,
                stdin=False,
                tty=False,
            ),
        )
    except Exception as e:
        logger.warning("Failed to write config to warm pod %s: %s", pod_name, e)
        # Fall through to cold path
        return await _cold_create_job(job_name, task_config, ns)

    # Launch entrypoint in background (detached)
    try:
        await loop.run_in_executor(
            None,
            lambda: k8s_stream(
                _core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                ns,
                command=["sh", "-c", "nohup python /usr/local/bin/entrypoint.py > /tmp/output.log 2>&1 &"],
                stderr=True,
                stdout=True,
                stdin=False,
                tty=False,
            ),
        )
    except Exception as e:
        logger.warning("Failed to exec on warm pod %s: %s", pod_name, e)
        return await _cold_create_job(job_name, task_config, ns)

    _active_jobs[job_name] = SandboxJob(
        job_name=job_name,
        namespace=ns,
        config_map_name=f"warm:{pod_name}",
    )
    logger.info("Launched task on warm pod %s as %s", pod_name, job_name)
    return job_name


async def _cold_create_job(job_name: str, task_config: dict, ns: str) -> str:
    """Fallback cold Job creation when warm pool fails."""
    job_id = job_name.replace("sandbox-", "")
    cm_name = f"sandbox-task-{job_id}"
    loop = asyncio.get_event_loop()

    cm = _build_config_map(cm_name, ns, task_config)
    await loop.run_in_executor(None, _core_v1.create_namespaced_config_map, ns, cm)

    netpol = _build_network_policy(job_name, ns)
    try:
        await loop.run_in_executor(None, _net_v1.create_namespaced_network_policy, ns, netpol)
    except Exception:
        pass

    job = _build_job_manifest(job_name, cm_name, ns)
    await loop.run_in_executor(None, _batch_v1.create_namespaced_job, ns, job)

    _active_jobs[job_name] = SandboxJob(
        job_name=job_name,
        namespace=ns,
        config_map_name=cm_name,
    )
    logger.info("Cold-created sandbox job %s", job_name)
    return job_name


async def get_sandbox_status(job_name: str) -> dict:
    """Get the status of a sandbox Job."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    # Check if this is a warm-pod job
    sandbox = _active_jobs.get(job_name)
    if sandbox and sandbox.config_map_name.startswith("warm:"):
        pod_name = sandbox.config_map_name.replace("warm:", "")
        return await _get_warm_pod_status(pod_name, job_name)

    job = await loop.run_in_executor(
        None,
        _batch_v1.read_namespaced_job_status,
        job_name,
        ns,
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


async def _get_warm_pod_status(pod_name: str, job_name: str) -> dict:
    """Check status of a task running on a warm pod."""
    loop = asyncio.get_event_loop()
    ns = settings.sandbox_namespace
    from kubernetes.stream import stream as k8s_stream

    try:
        output = await loop.run_in_executor(
            None,
            lambda: k8s_stream(
                _core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                ns,
                command=["sh", "-c", "test -f /tmp/output.log && tail -1 /tmp/output.log || echo ''"],
                stderr=False,
                stdout=True,
                stdin=False,
                tty=False,
            ),
        )
        # Check if the last line is valid JSON (entrypoint finished)
        output = output.strip() if output else ""
        if output.startswith("{"):
            try:
                json.loads(output)
                return {"job_name": job_name, "status": "completed", "start_time": None, "completion_time": None}
            except json.JSONDecodeError:
                pass

        # Check if process is still running
        ps_out = await loop.run_in_executor(
            None,
            lambda: k8s_stream(
                _core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                ns,
                command=["sh", "-c", "pgrep -f entrypoint.py || echo 'done'"],
                stderr=False,
                stdout=True,
                stdin=False,
                tty=False,
            ),
        )
        if "done" in (ps_out or ""):
            return {"job_name": job_name, "status": "completed", "start_time": None, "completion_time": None}

        return {"job_name": job_name, "status": "running", "start_time": None, "completion_time": None}
    except Exception:
        return {"job_name": job_name, "status": "unknown", "start_time": None, "completion_time": None}


async def get_sandbox_logs(job_name: str, follow: bool = False) -> str:
    """Get logs from a sandbox Job's pod."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    # Warm-pod path
    sandbox = _active_jobs.get(job_name)
    if sandbox and sandbox.config_map_name.startswith("warm:"):
        pod_name = sandbox.config_map_name.replace("warm:", "")
        from kubernetes.stream import stream as k8s_stream

        try:
            output = await loop.run_in_executor(
                None,
                lambda: k8s_stream(
                    _core_v1.connect_get_namespaced_pod_exec,
                    pod_name,
                    ns,
                    command=["cat", "/tmp/output.log"],
                    stderr=False,
                    stdout=True,
                    stdin=False,
                    tty=False,
                ),
            )
            return output or ""
        except Exception:
            return ""

    # Standard Job path
    pods = await loop.run_in_executor(
        None,
        lambda: _core_v1.list_namespaced_pod(
            ns,
            label_selector=f"job-name={job_name}",
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


async def list_sandbox_jobs() -> list[dict]:
    """List all sandbox Jobs (active + k8s)."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    jobs = await loop.run_in_executor(
        None,
        lambda: _batch_v1.list_namespaced_job(
            ns,
            label_selector="app.kubernetes.io/component=sandbox",
        ),
    )

    results = []
    for job in jobs.items:
        name = job.metadata.name
        status = "running"
        if job.status.succeeded and job.status.succeeded > 0:
            status = "completed"
        elif job.status.failed and job.status.failed > 0:
            status = "failed"

        results.append(
            {
                "job_name": name,
                "status": status,
                "start_time": job.status.start_time.isoformat() if job.status.start_time else None,
                "completion_time": job.status.completion_time.isoformat() if job.status.completion_time else None,
            }
        )

    # Add warm-pod jobs from in-memory registry
    for name, sandbox in _active_jobs.items():
        if sandbox.config_map_name.startswith("warm:") and not any(r["job_name"] == name for r in results):
            results.append(
                {
                    "job_name": name,
                    "status": "running",
                    "start_time": None,
                    "completion_time": None,
                }
            )

    return results


async def get_sandbox_artifacts(job_name: str, path: str = ".") -> list[dict]:
    """List files in a sandbox Job's workspace.

    Returns a list of {name, size, type} dicts for files in the workspace.
    """
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    # Determine pod name
    sandbox = _active_jobs.get(job_name)
    pod_name = None

    if sandbox and sandbox.config_map_name.startswith("warm:"):
        pod_name = sandbox.config_map_name.replace("warm:", "")
    else:
        pods = await loop.run_in_executor(
            None,
            lambda: _core_v1.list_namespaced_pod(
                ns,
                label_selector=f"job-name={job_name}",
            ),
        )
        if pods.items:
            pod_name = pods.items[0].metadata.name

    if not pod_name:
        return []

    from kubernetes.stream import stream as k8s_stream

    workspace = "/home/agent/workspace"
    target = f"{workspace}/{path}" if path != "." else workspace

    try:
        output = await loop.run_in_executor(
            None,
            lambda: k8s_stream(
                _core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                ns,
                command=["find", target, "-maxdepth", "2", "-printf", "%y %s %P\\n"],
                stderr=False,
                stdout=True,
                stdin=False,
                tty=False,
            ),
        )
    except Exception:
        return []

    artifacts = []
    for line in (output or "").strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split(" ", 2)
        if len(parts) >= 3:
            ftype = "directory" if parts[0] == "d" else "file"
            try:
                size = int(parts[1])
            except ValueError:
                size = 0
            artifacts.append({"name": parts[2], "size": size, "type": ftype})

    return artifacts


async def read_sandbox_artifact(job_name: str, path: str) -> str:
    """Read a file from a sandbox Job's workspace."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    sandbox = _active_jobs.get(job_name)
    pod_name = None

    if sandbox and sandbox.config_map_name.startswith("warm:"):
        pod_name = sandbox.config_map_name.replace("warm:", "")
    else:
        pods = await loop.run_in_executor(
            None,
            lambda: _core_v1.list_namespaced_pod(
                ns,
                label_selector=f"job-name={job_name}",
            ),
        )
        if pods.items:
            pod_name = pods.items[0].metadata.name

    if not pod_name:
        return ""

    from kubernetes.stream import stream as k8s_stream

    full_path = f"/home/agent/workspace/{path}"

    try:
        output = await loop.run_in_executor(
            None,
            lambda: k8s_stream(
                _core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                ns,
                command=["cat", full_path],
                stderr=False,
                stdout=True,
                stdin=False,
                tty=False,
            ),
        )
        return output or ""
    except Exception:
        return ""


async def delete_sandbox_job(job_name: str) -> None:
    """Delete a sandbox Job and its resources."""
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    sandbox = _active_jobs.get(job_name)

    # Handle warm-pod cleanup
    if sandbox and sandbox.config_map_name.startswith("warm:"):
        pod_name = sandbox.config_map_name.replace("warm:", "")
        try:
            await loop.run_in_executor(
                None,
                _core_v1.delete_namespaced_pod,
                pod_name,
                ns,
            )
        except Exception:
            pass
        _active_jobs.pop(job_name, None)
        return

    # Delete job (propagation=Foreground deletes pods too)
    try:
        await loop.run_in_executor(
            None,
            lambda: _batch_v1.delete_namespaced_job(
                job_name,
                ns,
                propagation_policy="Foreground",
            ),
        )
    except Exception as e:
        logger.warning("Failed to delete job %s: %s", job_name, e)

    # Delete ConfigMap
    if sandbox:
        try:
            await loop.run_in_executor(
                None,
                _core_v1.delete_namespaced_config_map,
                sandbox.config_map_name,
                ns,
            )
        except Exception:
            pass

        # Delete PVC
        if sandbox.pvc_name:
            try:
                await loop.run_in_executor(
                    None,
                    _core_v1.delete_namespaced_persistent_volume_claim,
                    sandbox.pvc_name,
                    ns,
                )
            except Exception:
                pass

    # Delete NetworkPolicy
    try:
        await loop.run_in_executor(
            None,
            _net_v1.delete_namespaced_network_policy,
            f"sandbox-{job_name}",
            ns,
        )
    except Exception:
        pass

    _active_jobs.pop(job_name, None)


async def cleanup_completed_jobs(max_age_seconds: int = 3600) -> int:
    """Clean up completed sandbox Jobs older than max_age_seconds.

    Returns the number of jobs cleaned up. This supplements the TTL
    controller for jobs where the TTL hasn't fired yet.
    """
    _ensure_k8s()
    ns = settings.sandbox_namespace
    loop = asyncio.get_event_loop()

    jobs = await loop.run_in_executor(
        None,
        lambda: _batch_v1.list_namespaced_job(
            ns,
            label_selector="app.kubernetes.io/component=sandbox",
        ),
    )

    cleaned = 0
    for job in jobs.items:
        if not job.status.completion_time:
            continue

        from datetime import datetime, timezone

        age = (datetime.now(timezone.utc) - job.status.completion_time).total_seconds()
        if age > max_age_seconds:
            try:
                await delete_sandbox_job(job.metadata.name)
                cleaned += 1
            except Exception:
                pass

    return cleaned


# ---------------------------------------------------------------------------
# Runtime class
# ---------------------------------------------------------------------------


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

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["fastapi>=0.115", "uvicorn>=0.34", "httpx>=0.27", "pyyaml>=6.0"]
# ///
"""GenAI MLOps Platform Observatory.

Live web dashboard showing full operational state of the agentic system:
infrastructure health, container resources, webhook status, MCP servers,
Langfuse traces/scores, MLflow experiments, sessions, and drift.

Two polling tiers: fast (5s) for infra, slow (30s) for MLOps metrics.
SSE pushes updates to the browser — no manual refresh needed.

Usage:
    uv run scripts/dashboard.py              # start on port 4020
    uv run scripts/dashboard.py --port 8080  # custom port
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_DIR / "config.yaml"

# Load config.yaml
with open(CONFIG_PATH) as f:
    CFG = yaml.safe_load(f)

SERVICES = CFG.get("services", {})

# Env vars (with fallbacks from config.yaml)
WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY", CFG.get("webhook", {}).get("api_key", ""))
LANGFUSE_HOST = os.getenv(
    "LANGFUSE_HOST", f"http://localhost:{SERVICES.get('langfuse', {}).get('port', 3100)}"
)
LANGFUSE_PK = os.getenv(
    "LANGFUSE_PUBLIC_KEY", SERVICES.get("langfuse", {}).get("public_key", "lf-pk-local")
)
LANGFUSE_SK = os.getenv(
    "LANGFUSE_SECRET_KEY", SERVICES.get("langfuse", {}).get("secret_key", "lf-sk-local")
)
N8N_PORT = int(os.getenv("N8N_PORT", SERVICES.get("n8n", {}).get("port", 5678)))
MLFLOW_PORT = int(os.getenv("MLFLOW_PORT", SERVICES.get("mlflow", {}).get("port", 5050)))
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", 4020))

# k3d mode: use ingress URLs instead of localhost. Auto-detected from kubectl context.
K3D_MODE = os.getenv("DASHBOARD_K3D", "auto")  # "auto", "true", "false"
K3D_DOMAIN = os.getenv("K3D_DOMAIN", "127.0.0.1.nip.io")
K3D_NAMESPACE = os.getenv("K3D_NAMESPACE", "genai")
AGENT_GATEWAY_URL = os.getenv(
    "AGENT_GATEWAY_URL",
    f"http://agent-gateway.genai.{K3D_DOMAIN}",
)

# Ingress-based URLs for k3d mode
K3D_URLS = {
    "n8n": f"http://n8n.platform.{K3D_DOMAIN}",
    "mlflow": f"http://mlflow.genai.{K3D_DOMAIN}",
    "litellm": f"http://litellm.genai.{K3D_DOMAIN}",
    "langfuse": f"http://langfuse.genai.{K3D_DOMAIN}",
    "plane": f"http://plane.genai.{K3D_DOMAIN}",
    "argocd": f"http://argocd.platform.{K3D_DOMAIN}",
    "gitlab": f"http://gitlab.platform.{K3D_DOMAIN}",
}

_k3d_mode_cache: bool | None = None


def _is_k3d_mode() -> bool:
    """Check if we should use k3d/k8s-native mode (no Docker queries)."""
    global _k3d_mode_cache
    if _k3d_mode_cache is not None:
        return _k3d_mode_cache
    mode = os.getenv("DASHBOARD_K3D", K3D_MODE)
    if mode == "true":
        _k3d_mode_cache = True
    elif mode == "false":
        _k3d_mode_cache = False
    else:
        # Auto-detect: check if kubectl context is a k3d cluster
        import subprocess
        try:
            r = subprocess.run(
                ["kubectl", "config", "current-context"],
                capture_output=True, text=True, timeout=3,
            )
            _k3d_mode_cache = r.returncode == 0 and "k3d" in r.stdout
        except Exception:
            _k3d_mode_cache = False
    if _k3d_mode_cache:
        # Override base URLs to use ingress
        global N8N_BASE, MLFLOW_BASE, LANGFUSE_HOST
        N8N_BASE = K3D_URLS["n8n"] + "/webhook"
        MLFLOW_BASE = K3D_URLS["mlflow"]
        LANGFUSE_HOST = K3D_URLS.get("langfuse", LANGFUSE_HOST)
        # Re-map health targets to ingress URLs
        ingress_map = {
            "n8n": (K3D_URLS["n8n"], "/healthz"),
            "mlflow": (K3D_URLS["mlflow"], "/health"),
            "litellm": (K3D_URLS["litellm"], "/health"),
            "langfuse": (K3D_URLS["langfuse"], "/api/public/health"),
        }
        for ht in HEALTH_TARGETS:
            name = ht["name"]
            if name in ingress_map:
                base, path = ingress_map[name]
                ht["url"] = f"{base}{path}"
    return _k3d_mode_cache


N8N_BASE = f"http://localhost:{N8N_PORT}/webhook"
MLFLOW_BASE = f"http://localhost:{MLFLOW_PORT}"


def _n8n_origin() -> str:
    """Return the n8n origin (scheme+host+port), respecting k3d mode."""
    if _is_k3d_mode():
        return K3D_URLS["n8n"]
    return f"http://localhost:{N8N_PORT}"


# n8n API key (for REST API workflow listing)
def _load_n8n_api_key() -> str:
    key = os.getenv("N8N_API_KEY", "")
    if not key:
        secrets_file = PROJECT_DIR / "secrets" / "n8n_api_key"
        if secrets_file.exists():
            key = secrets_file.read_text().strip()
    return key


N8N_API_KEY = _load_n8n_api_key()

# Health check targets built from config.yaml
APP_SERVICES = {
    "n8n",
    "mlflow",
    "litellm",
    "langfuse",
    "minio",
}
DOCKER_ONLY_SERVICES: set[str] = set()  # all services have HTTP health endpoints in k3d
DB_SERVICES = {"pgvector"}
HEALTH_TARGETS: list[dict] = []
for name, svc in SERVICES.items():
    if name in DOCKER_ONLY_SERVICES:
        continue  # checked via docker inspect instead
    port = svc.get("port")
    health = svc.get("health")
    if port and health:
        if name in DB_SERVICES:
            cat = "database"
        elif name in APP_SERVICES:
            cat = "application"
        else:
            cat = "application"
        HEALTH_TARGETS.append(
            {
                "name": name.replace("_", "-"),
                "url": f"http://localhost:{port}{health}",
                "category": cat,
            }
        )

# Add Ollama as host service
HEALTH_TARGETS.append(
    {"name": "ollama", "url": "http://localhost:11434/api/tags", "category": "host"}
)

# Webhook endpoints to probe
WEBHOOK_PROBES = [
    {"path": "/webhook/chat", "method": "POST", "body": {"action": "health"}, "timeout": 10},
    {"path": "/webhook/traces", "method": "POST", "body": {"action": "summary"}},
    {"path": "/webhook/prompts", "method": "POST", "body": {"action": "list"}},
    {
        "path": "/webhook/eval",
        "method": "POST",
        "body": {"prompt_name": "assistant", "model": "test"},
    },
    {"path": "/webhook/sessions", "method": "POST", "body": {"action": "list"}},
    {"path": "/webhook/datasets", "method": "POST", "body": {"action": "list"}},
    {"path": "/webhook/experiments", "method": "POST", "body": {"action": "list"}},
    {"path": "/webhook/v1/models", "method": "GET", "body": None},
    {"path": "/webhook/a2a/agent-card", "method": "GET", "body": None},
]

# MCP server catalog — loaded dynamically from gateway catalog.yaml.
# Maps server name → metadata (title, description, parent stack).
MCP_CATALOG_PATH = PROJECT_DIR / "mcp-servers" / "catalog.yaml"

# Which parent stack each MCP server belongs to (inferred from what it manages)
MCP_PARENT_STACK: dict[str, str] = {
    "kubernetes": "platform",
    "gitlab": "platform",
    "n8n": "orchestration",
    "plane": "dataops",
}

MCP_ICONS: dict[str, str] = {
    "kubernetes": "\u2638\ufe0f",
    "gitlab": "\U0001f98a",
    "n8n": "\U0001f527",
    "plane": "\U0001f4cb",
}

# MCP server → target service(s) it connects to (for topology edges)
MCP_TARGETS: dict[str, list[tuple[str, str]]] = {
    "kubernetes": [("ingress-nginx", "cluster")],
    "gitlab": [("gitlab-ce", "API")],
    "n8n": [("n8n", "API")],
    "plane": [("plane-web", "API")],
}


def _load_mcp_catalog() -> list[dict]:
    """Load MCP server definitions from gateway catalog.yaml.

    The `system:` tag in each catalog entry maps the MCP server to its parent
    subsystem (Helm release). Falls back to MCP_PARENT_STACK if not set.
    """
    try:
        with open(MCP_CATALOG_PATH) as f:
            cat = yaml.safe_load(f)
        registry = cat.get("registry", {})
        servers = []
        for name, info in registry.items():
            # system: tag from catalog is the source of truth
            parent = info.get("system", MCP_PARENT_STACK.get(name, "platform"))
            servers.append({
                "name": name,
                "title": info.get("title", name.title()),
                "description": info.get("description", ""),
                "image": info.get("image", ""),
                "parent_stack": parent,
                "icon": MCP_ICONS.get(name, "\U0001f527"),
            })
        return servers
    except Exception:
        return []


MCP_CATALOG: list[dict] = _load_mcp_catalog()
MCP_SERVERS = [s["name"] for s in MCP_CATALOG]

# Agent definitions — dynamically fetched from MLflow prompt registry.
# Agents are prompts tagged with use_case=agent. The registry is the single
# source of truth; the dashboard discovers agents at runtime.
AGENT_DEFINITIONS: list[dict] = []  # populated by _fetch_agents_from_registry()

# Default agent icons by persona name (fallback when registry has no icon tag)
AGENT_ICONS: dict[str, str] = {
    "analyst": "\U0001f4ca",
    "coder": "\U0001f4bb",
    "devops": "\u2699\ufe0f",
    "mcp": "\U0001f527",
    "mlops": "\U0001f9ea",
    "reasoner": "\U0001f9e0",
    "writer": "\u270d\ufe0f",
    "chat": "\U0001f4ac",
    "a2a": "\U0001f91d",
}
AGENT_WEBHOOK = "/webhook/chat"  # all agents route through the chat webhook

# Known n8n workflow files (fallback if API unavailable)
KNOWN_WORKFLOWS = [
    {"file": "chat.json", "name": "Chat", "has_webhook": True},
    {"file": "trace.json", "name": "Execution Tracing", "has_webhook": True},
    {"file": "sessions.json", "name": "Agent Sessions", "has_webhook": True},
    {"file": "prompt-crud.json", "name": "Prompt Registry CRUD", "has_webhook": True},
    {"file": "prompt-eval.json", "name": "Prompt Evaluation", "has_webhook": True},
    {"file": "a2a-server.json", "name": "A2A Server", "has_webhook": True},
    {"file": "openai-compat.json", "name": "OpenAI-Compatible API", "has_webhook": True, "agent": False},
    {"file": "mlflow-data.json", "name": "Dataset Management", "has_webhook": True},
    {"file": "mlflow-experiments.json", "name": "Experiment Explorer", "has_webhook": True},
]

# Operational groups for dashboard Services tab (by subsystem)
OPS_GROUPS = {
    "agents": {
        "label": "AgenticOps",
        "desc": "AI personas from prompt registry",
        "color": "#f0883e",
        "services": set(),  # dynamic from MLflow
    },
    "inference": {
        "label": "Inference",
        "desc": "LLM routing & streaming",
        "color": "#58a6ff",
        "services": {"ollama", "litellm", "streaming-proxy"},
    },
    "tracing": {
        "label": "Tracing",
        "desc": "LLM observability & scoring",
        "color": "#bc8cff",
        "services": {
            "langfuse",
            "langfuse-worker",
            "langfuse-postgres",
            "langfuse-clickhouse",
            "langfuse-redis",
        },
    },
    "experiments": {
        "label": "Experiments",
        "desc": "ML lifecycle & artifact tracking",
        "color": "#a78bfa",
        "services": {"mlflow", "mlflow-postgres", "minio"},
    },
    "orchestration": {
        "label": "Orchestration",
        "desc": "Workflow automation",
        "color": "#3b82f6",
        "services": {"n8n", "n8n-postgres"},
    },
    "dataops": {
        "label": "DataOps",
        "desc": "Data catalog & pipelines",
        "color": "#22d3ee",
        "services": {
            "airflow",
            "airflow-postgres",
            "openmetadata",
            "openmetadata-postgres",
            "openmetadata-search",
            "pgvector",
            "neo4j",
        },
    },
    "platform": {
        "label": "Platform",
        "desc": "GitOps & cluster infrastructure",
        "color": "#f97316",
        "services": {
            "mcp-gateway",
            "argocd-server",
            "argocd-controller",
            "argocd-appset",
            "argocd-repo",
            "argocd-redis",
            "gitlab-ce",
            "gitlab-runner",
            "ingress-nginx",
        },
    },
}

# ── Deployment Topology ──────────────────────────────────────────────────────
# Base topology defines logical services and their relationships.
# Actual nodes are built at poll time from docker ps + kubectl, so the
# topology reflects what is really running (docker, k8s, or both).

# Logical service definitions — shared across both environments.
BASE_SERVICES = [
    # ── Inference group — LLM routing & streaming ──
    {
        "sid": "ollama",
        "label": "Ollama",
        "category": "host",
        "group": "inference",
        "detail": "Native Mac \u00b7 Metal GPU \u00b7 :11434",
    },
    {
        "sid": "litellm",
        "label": "LiteLLM",
        "category": "application",
        "group": "inference",
        "detail": f"LLM proxy \u00b7 :{SERVICES.get('litellm', {}).get('port', 4000)}",
    },
    # ── Tracing group — LLM observability & scoring ──
    {
        "sid": "langfuse",
        "label": "Langfuse",
        "category": "observability",
        "group": "tracing",
        "detail": f"LLM tracing \u00b7 :3000",
    },
    {
        "sid": "langfuse-clickhouse",
        "label": "ClickHouse",
        "category": "database",
        "group": "tracing",
        "detail": "Trace storage",
    },
    {
        "sid": "langfuse-redis",
        "label": "Redis",
        "category": "database",
        "group": "tracing",
        "detail": "Cache + queue",
    },
    # ── Experiments group — ML lifecycle & artifact tracking ──
    {
        "sid": "mlflow",
        "label": "MLflow",
        "category": "observability",
        "group": "experiments",
        "detail": f"Experiments \u00b7 :{MLFLOW_PORT}",
    },
    {
        "sid": "mlflow-postgres",
        "label": "MLflow PG",
        "category": "database",
        "group": "experiments",
        "detail": "PostgreSQL",
    },
    {
        "sid": "minio",
        "label": "MinIO",
        "category": "storage",
        "group": "experiments",
        "detail": f"S3-compat \u00b7 :{SERVICES.get('minio', {}).get('port', 9000)}",
    },
    # ── Orchestration group ──
    {
        "sid": "n8n",
        "label": "n8n",
        "category": "application",
        "group": "orchestration",
        "detail": f"Workflow engine \u00b7 :{N8N_PORT}",
    },
    {
        "sid": "n8n-postgres",
        "label": "n8n PG",
        "category": "database",
        "group": "orchestration",
        "detail": "PostgreSQL",
    },
    {
        "sid": "agent-gateway",
        "label": "Agent Gateway",
        "category": "application",
        "group": "orchestration",
        "detail": "Registry + MCP proxy + A2A \u00b7 :8000",
    },
    # ── DataOps group ──
    {
        "sid": "pgvector",
        "label": "pgvector",
        "category": "database",
        "group": "dataops",
        "detail": "Vector embeddings",
    },
    {
        "sid": "plane-web",
        "label": "Plane",
        "category": "application",
        "group": "dataops",
        "detail": "Project management \u00b7 :3000",
    },
    # ── Platform group (k3d cluster) ──
    {
        "sid": "argocd-server",
        "label": "ArgoCD",
        "category": "application",
        "group": "platform",
        "detail": "GitOps CD \u00b7 k8s",
    },
    {
        "sid": "argocd-controller",
        "label": "ArgoCD Controller",
        "category": "application",
        "group": "platform",
        "detail": "App sync controller",
    },
    {
        "sid": "argocd-repo",
        "label": "Repo Server",
        "category": "application",
        "group": "platform",
        "detail": "Git manifest renderer",
    },
    {
        "sid": "argocd-redis",
        "label": "ArgoCD Redis",
        "category": "database",
        "group": "platform",
        "detail": "ArgoCD cache",
    },
    {
        "sid": "gitlab-ce",
        "label": "GitLab CE",
        "category": "application",
        "group": "platform",
        "detail": "Source control \u00b7 k8s",
    },
    {
        "sid": "ingress-nginx",
        "label": "Ingress NGINX",
        "category": "application",
        "group": "platform",
        "detail": "k3d ingress controller",
    },
    {
        "sid": "kagent-ui",
        "label": "KAgent",
        "category": "application",
        "group": "platform",
        "detail": "Agent operator \u00b7 k8s",
    },
    # Agent nodes are dynamically generated from agent-gateway
    # at poll time — see _fetch_agents_from_registry()
    # MCP tool server nodes are dynamically generated from k8s services
    # at poll time — slotted into parent stacks
    # Virtual node — benchmarks
    {
        "sid": "benchmarks",
        "label": "Benchmarks",
        "category": "benchmark",
        "group": "benchmark",
        "detail": "Eval datasets",
    },
]
BASE_SERVICES_MAP = {s["sid"]: s for s in BASE_SERVICES}

# Edge types control visual style:
#   inference — thick blue, solid
#   logging   — medium purple, dashed
#   metadata  — thin gray, dotted
#   storage   — medium yellow, dashed
#   cache     — thin cyan, dashed
#   tools     — medium green, solid
BASE_EDGES = [
    # Inference pipeline
    {"source": "n8n", "target": "litellm", "label": "inference", "type": "inference"},
    {"source": "litellm", "target": "ollama", "label": "LLM", "type": "inference"},
    {"source": "agent-gateway", "target": "litellm", "label": "inference", "type": "inference"},
    # Logging / observability
    {"source": "n8n", "target": "langfuse", "label": "traces", "type": "logging"},
    {"source": "n8n", "target": "mlflow", "label": "logging", "type": "logging"},
    # Metadata
    {"source": "n8n", "target": "n8n-postgres", "label": "metadata", "type": "metadata"},
    {"source": "mlflow", "target": "mlflow-postgres", "label": "metadata", "type": "metadata"},
    {"source": "mlflow", "target": "minio", "label": "artifacts", "type": "storage"},
    # Langfuse
    {"source": "langfuse", "target": "langfuse-clickhouse", "label": "traces", "type": "storage"},
    {"source": "langfuse", "target": "langfuse-redis", "label": "cache", "type": "cache"},
    # Agent Gateway
    {"source": "agent-gateway", "target": "pgvector", "label": "registry", "type": "storage"},
    # Plane
    {"source": "n8n", "target": "plane-web", "label": "issues", "type": "tools"},
    # Platform
    {"source": "argocd-controller", "target": "argocd-server", "label": "sync", "type": "tools"},
    {"source": "argocd-repo", "target": "argocd-server", "label": "manifests", "type": "tools"},
    {"source": "argocd-server", "target": "argocd-redis", "label": "cache", "type": "cache"},
    {"source": "argocd-server", "target": "gitlab-ce", "label": "git", "type": "metadata"},
]

# Container name mapping (docker container name → logical service id)
CONTAINER_TO_NODE = {
    "genai-n8n": "n8n",
    "genai-litellm": "litellm",
    "genai-mlflow": "mlflow",
    "genai-langfuse": "langfuse",
    "genai-n8n-postgres": "n8n-postgres",
    "genai-mlflow-postgres": "mlflow-postgres",
    "genai-pgvector": "pgvector",
    "genai-minio": "minio",
    "genai-langfuse-clickhouse": "langfuse-clickhouse",
    "genai-langfuse-redis": "langfuse-redis",
}

# k8s pod name prefix → logical service id
# Covers k3d mewtwo cluster services
K8S_POD_TO_NODE: list[tuple[str, str]] = [
    # genai namespace — individual Helm releases
    ("genai-n8n", "n8n"),
    ("genai-litellm", "litellm"),
    ("genai-mlflow", "mlflow"),
    ("genai-langfuse-web", "langfuse"),
    ("genai-langfuse-clickhouse", "langfuse-clickhouse"),
    ("genai-langfuse-redis", "langfuse-redis"),
    ("genai-minio", "minio"),
    ("genai-pg-n8n", "n8n-postgres"),
    ("genai-pg-mlflow", "mlflow-postgres"),
    ("genai-pgvector", "pgvector"),
    ("genai-agent-gateway", "agent-gateway"),
    ("genai-open-ontologies", "open-ontologies"),
    # Plane
    ("genai-plane-web", "plane-web"),
    ("genai-plane-api", "plane-api"),
    ("genai-pg-plane", "plane-postgres"),
    # KAgent
    ("genai-kagent-ui", "kagent-ui"),
    ("genai-kagent-controller", "kagent-controller"),
    ("genai-kagent-tools", "kagent-tools"),
    # Agent deployments
    ("developer-agent", "developer-agent"),
    ("mlops-agent", "mlops-agent"),
    ("platform-admin-agent", "platform-admin-agent"),
    # MCP servers
    ("genai-mcp-kubernetes", "mcp-kubernetes"),
    ("genai-mcp-gitlab", "mcp-gitlab"),
    ("genai-mcp-n8n", "mcp-n8n"),
    ("genai-mcp-plane", "mcp-plane"),
    # platform namespace
    ("argocd-server", "argocd-server"),
    ("argocd-application-controller", "argocd-controller"),
    ("argocd-applicationset-controller", "argocd-appset"),
    ("argocd-repo-server", "argocd-repo"),
    ("argocd-redis", "argocd-redis"),
    ("gitlab-ce", "gitlab-ce"),
    ("ingress-nginx-controller", "ingress-nginx"),
]
# Extra pods that appear in k8s but aren't in base topology
K8S_EXTRA_PODS = {"zookeeper", "coredns", "local-path-provisioner", "metrics-server"}

K8S_NAMESPACES = os.getenv("K8S_NAMESPACES", "platform,ingress-nginx,dev,genai").split(",")

# Platform paths
PLATFORM_MONOREPO = Path(
    os.getenv("PLATFORM_MONOREPO", str(PROJECT_DIR.parent / "platform_monorepo"))
)
TERRAFORM_DIR = PLATFORM_MONOREPO / "terraform"

# Service stack mapping — architect's view by subsystem.
# Each stack groups a subsystem with its dependencies and associated MCP servers.
# Dynamic entries (agent-*, mcp-*) are added at poll time.
SERVICE_STACK = {
    # Inference — LLM routing & streaming
    "ollama": "inference",
    "litellm": "inference",
    # Tracing — LLM observability & scoring
    "langfuse": "tracing",
    "langfuse-clickhouse": "tracing",
    "langfuse-redis": "tracing",
    # Experiments — ML lifecycle & artifact tracking
    "mlflow": "experiments",
    "mlflow-postgres": "experiments",
    "minio": "experiments",
    "benchmarks": "experiments",
    # Orchestration — Workflow automation + agent gateway
    "n8n": "orchestration",
    "n8n-postgres": "orchestration",
    "agent-gateway": "orchestration",
    # DataOps — Project management, vectors
    "pgvector": "dataops",
    "plane-web": "dataops",
    # Platform — GitOps & cluster infrastructure
    "argocd-server": "platform",
    "argocd-controller": "platform",
    "argocd-repo": "platform",
    "argocd-redis": "platform",
    "gitlab-ce": "platform",
    "ingress-nginx": "platform",
    "kagent-ui": "platform",
}

# Stack descriptions for the architect's view (shown in topology group headers)
STACK_DESCRIPTIONS = {
    "agents": "AI personas from prompt registry",
    "inference": "LLM routing & streaming",
    "tracing": "LLM observability & scoring",
    "experiments": "ML lifecycle & artifact tracking",
    "orchestration": "Workflow automation",
    "dataops": "Data catalog & pipelines",
    "platform": "GitOps & cluster infrastructure",
}


# Integration checks: verify cross-service connectivity
INTEGRATION_CHECKS = [
    {
        "name": "n8n → LiteLLM",
        "desc": "Inference proxy reachable from workflows",
        "url": f"{_n8n_origin()}/webhook/v1/models",
        "method": "GET",
        "auth": True,
    },
    {
        "name": "LiteLLM → Ollama",
        "desc": "LLM backend reachable",
        "url": f"http://localhost:{SERVICES.get('litellm', {}).get('port', 4000)}/health/liveliness",
        "method": "GET",
    },
    {
        "name": "n8n → MLflow",
        "desc": "Prompt registry reachable",
        "url": f"{MLFLOW_BASE}/api/2.0/mlflow/registered-models/search",
        "method": "GET",
    },
    {
        "name": "Agent Gateway",
        "desc": "Agent registry + MCP proxy healthy",
        "url": f"{AGENT_GATEWAY_URL}/health/detail",
        "method": "GET",
    },
]

# ── State ─────────────────────────────────────────────────────────────────────

state: dict = {"infra": {}, "mlops": {}, "platform": {}, "timestamp": ""}


# ── Infra Poller (5s) ─────────────────────────────────────────────────────────


async def _check_health(client: httpx.AsyncClient, target: dict) -> dict:
    """Check a single health endpoint."""
    t0 = time.monotonic()
    try:
        r = await client.get(target["url"], timeout=3)
        ms = (time.monotonic() - t0) * 1000
        return {
            "name": target["name"],
            "category": target["category"],
            "status": "healthy" if r.status_code == 200 else "degraded",
            "code": r.status_code,
            "response_ms": round(ms),
        }
    except Exception:
        ms = (time.monotonic() - t0) * 1000
        return {
            "name": target["name"],
            "category": target["category"],
            "status": "down",
            "code": 0,
            "response_ms": round(ms),
        }


async def _check_webhooks(client: httpx.AsyncClient) -> list[dict]:
    """Probe n8n webhook endpoints."""
    headers = {"Content-Type": "application/json"}
    if WEBHOOK_API_KEY:
        headers["X-API-Key"] = WEBHOOK_API_KEY

    async def probe(ep: dict) -> dict:
        url = f"{_n8n_origin()}{ep['path']}"
        t0 = time.monotonic()
        ep_timeout = ep.get("timeout", 5)
        try:
            if ep["method"] == "GET":
                r = await client.get(url, headers=headers, timeout=ep_timeout)
            else:
                r = await client.post(url, json=ep["body"], headers=headers, timeout=ep_timeout)
            ms = (time.monotonic() - t0) * 1000
            ok = r.status_code in (200, 400, 404, 500)  # any workflow response = alive
            return {"path": ep["path"], "status": r.status_code, "response_ms": round(ms), "ok": ok}
        except httpx.TimeoutException:
            ms = (time.monotonic() - t0) * 1000
            return {
                "path": ep["path"],
                "status": 0,
                "response_ms": round(ms),
                "ok": False,
                "timeout": True,
            }
        except Exception:
            ms = (time.monotonic() - t0) * 1000
            return {"path": ep["path"], "status": 0, "response_ms": round(ms), "ok": False}

    return await asyncio.gather(*[probe(ep) for ep in WEBHOOK_PROBES])


async def _docker_containers() -> list[dict]:
    """Get container stats via docker CLI (legacy docker-compose mode)."""
    if _is_k3d_mode():
        return []  # k8s mode — use kubectl instead
    try:
        fmt = '{"name":"{{.Name}}","cpu":"{{.CPUPerc}}","mem":"{{.MemUsage}}","status":"{{.Container}}"}'
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "stats",
            "--no-stream",
            "--format",
            fmt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        containers = []
        for line in stdout.decode().strip().splitlines():
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return containers
    except Exception:
        return []


async def _docker_ps() -> dict[str, dict]:
    """Get container state and uptime via docker ps (legacy docker-compose mode)."""
    if _is_k3d_mode():
        return {}  # k8s mode — use kubectl instead
    try:
        fmt = '{"name":"{{.Names}}","state":"{{.State}}","status":"{{.Status}}"}'
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=genai-",
            "--format",
            fmt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        result = {}
        for line in stdout.decode().strip().splitlines():
            try:
                c = json.loads(line)
                result[c["name"]] = c
            except (json.JSONDecodeError, KeyError):
                continue
        return result
    except Exception:
        return {}


async def _check_mcp_image(image: str) -> bool:
    """Check if a Docker image exists locally."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "image", "inspect", image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
        return proc.returncode == 0
    except Exception:
        return False


async def _mcp_servers() -> list[dict]:
    """Check MCP server availability.

    In k3d mode: queries agent-gateway /mcp/servers for live server status.
    In docker mode: checks gateway health + per-server image status.

    Returns enriched catalog data with runtime status.
    """
    if _is_k3d_mode():
        return await _mcp_servers_k3d()

    gw_health = await _docker_health("genai-mcp-gateway")
    gateway_up = gw_health.get("status") == "healthy"
    catalog_by_name = {s["name"]: s for s in MCP_CATALOG}

    # Check all images in parallel
    image_checks = {}
    for name in MCP_SERVERS:
        info = catalog_by_name.get(name, {})
        image = info.get("image", f"genai-mcp-{name}:latest")
        image_checks[name] = _check_mcp_image(image)

    image_results = {}
    if image_checks:
        names = list(image_checks.keys())
        results = await asyncio.gather(*[image_checks[n] for n in names])
        image_results = dict(zip(names, results))

    result = []
    for name in MCP_SERVERS:
        info = catalog_by_name.get(name, {})
        has_image = image_results.get(name, False)
        if gateway_up and has_image:
            status = "healthy"
        elif gateway_up:
            status = "degraded"  # gateway up but image missing
        else:
            status = "down"
        result.append({
            "name": name,
            "title": info.get("title", name.title()),
            "description": info.get("description", ""),
            "parent_stack": info.get("parent_stack", MCP_PARENT_STACK.get(name, "orchestration")),
            "icon": info.get("icon", MCP_ICONS.get(name, "\U0001f527")),
            "image": info.get("image", f"genai-mcp-{name}:latest"),
            "has_image": has_image,
            "gateway_up": gateway_up,
            "status": status,
            "on_demand": True,
        })
    return result


async def _mcp_servers_k3d() -> list[dict]:
    """Fetch MCP server status from agent-gateway /mcp/servers (k3d mode)."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{AGENT_GATEWAY_URL}/mcp/servers", timeout=5)
            if r.status_code == 200:
                data = r.json()
                servers = data if isinstance(data, list) else data.get("servers", [])
                result = []
                for srv in servers:
                    name = srv.get("name", "unknown")
                    srv_status = srv.get("status", "unknown")
                    healthy = srv_status == "healthy" or srv.get("healthy", False)
                    tool_count = srv.get("tool_count", 0)
                    result.append({
                        "name": name,
                        "title": srv.get("description", name.title())[:40],
                        "description": srv.get("description", ""),
                        "parent_stack": srv.get("namespace", MCP_PARENT_STACK.get(name, "platform")),
                        "icon": MCP_ICONS.get(name, "\U0001f527"),
                        "image": "",
                        "has_image": True,
                        "gateway_up": True,
                        "status": "healthy" if healthy else "degraded",
                        "on_demand": False,
                        "tool_count": tool_count,
                    })
                return result
    except Exception:
        pass
    return []


# ── n8n Workflow Listing ─────────────────────────────────────────────────────

_wf_cache: dict = {"data": [], "ts": 0.0}


def _workflows_from_filesystem() -> list[dict]:
    """Fallback: list known workflows from filesystem."""
    wf_dir = PROJECT_DIR / "n8n-data" / "workflows"
    if not wf_dir.is_dir():
        return []
    return [
        {
            "name": w["name"],
            "active": None,  # unknown without API
            "has_webhook": w.get("has_webhook", False),
            "source": "filesystem",
        }
        for w in KNOWN_WORKFLOWS
        if (wf_dir / w["file"]).exists()
    ]


async def _fetch_n8n_workflows(client: httpx.AsyncClient) -> list[dict]:
    """Fetch workflow list from n8n REST API (falls back to filesystem)."""
    if not N8N_API_KEY:
        return _workflows_from_filesystem()
    try:
        r = await client.get(
            f"{_n8n_origin()}/api/v1/workflows",
            headers={"X-N8N-API-KEY": N8N_API_KEY},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            workflows = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(workflows, list):
                workflows = []
            return [
                {
                    "id": w.get("id", ""),
                    "name": w.get("name", ""),
                    "active": w.get("active", False),
                    "nodes": len(w.get("nodes", [])),
                    "tags": [t.get("name", "") for t in (w.get("tags") or [])],
                    "updated": w.get("updatedAt", ""),
                    "has_webhook": any(
                        n.get("type", "")
                        in (
                            "n8n-nodes-base.webhook",
                            "n8n-nodes-base.respondToWebhook",
                            "@n8n/n8n-nodes-langchain.agent",
                        )
                        for n in (w.get("nodes") or [])
                    ),
                    "source": "api",
                }
                for w in workflows
            ]
    except Exception:
        pass
    # API failed or returned non-200 — fall back to filesystem
    return _workflows_from_filesystem()


async def _fetch_n8n_workflows_cached(client: httpx.AsyncClient) -> list[dict]:
    """Cached workflow fetch (refreshes every 30s, called from 5s infra poll)."""
    now = time.monotonic()
    if now - _wf_cache["ts"] < 30 and _wf_cache["data"]:
        return _wf_cache["data"]
    result = await _fetch_n8n_workflows(client)
    if result:
        _wf_cache["data"] = result
        _wf_cache["ts"] = now
    return _wf_cache["data"]


# ── Agent Registry (MLflow Prompts) ─────────────────────────────────────────

_agent_cache: dict = {"data": [], "ts": 0.0}


async def _fetch_agents_from_registry(client: httpx.AsyncClient) -> list[dict]:
    """Fetch agent definitions from agent-gateway (primary) or MLflow prompts (fallback).

    In k3d mode, the agent-gateway at /agents has the authoritative agent list
    from PostgreSQL. Falls back to n8n webhook prompts for docker-compose mode.
    Cached for 30s.
    """
    global AGENT_DEFINITIONS
    now = time.monotonic()
    if now - _agent_cache["ts"] < 30 and _agent_cache["data"]:
        return _agent_cache["data"]

    agents: list[dict] = []

    # Primary: fetch from agent-gateway (works in k3d mode)
    try:
        gw_url = AGENT_GATEWAY_URL
        r = await client.get(f"{gw_url}/agents", timeout=5)
        if r.status_code == 200:
            data = r.json()
            agent_list = data.get("agents", data) if isinstance(data, dict) else data
            for a in agent_list:
                name = a.get("name", "")
                skills = a.get("skills", [])
                agents.append({
                    "id": name.lower(),
                    "name": name.replace("-", " ").title(),
                    "desc": a.get("description", ""),
                    "icon": AGENT_ICONS.get(name.lower(), "\U0001f916"),
                    "webhook": AGENT_WEBHOOK,
                    "config": {},
                    "mcp_tools": [],
                    "skills": skills,
                    "tags": [],
                    "mode": "agent" if skills else "chat",
                    "promotion": {},
                    "runtime": a.get("runtime", "n8n"),
                })
    except Exception:
        pass

    # Fallback: fetch from n8n webhook prompts (docker-compose mode)
    if not agents:
        try:
            r = await client.post(
                f"{_n8n_origin()}/webhook/prompts",
                json={"action": "list"},
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                prompts = data.get("prompts", [])
                for p in prompts:
                    tags = p.get("tags", {})
                    if tags.get("use_case") != "agent":
                        continue
                    name = p["name"].replace(".SYSTEM", "")
                    config = {}
                    try:
                        config = json.loads(tags.get("agent.config", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        pass
                    mcp_tools_raw = config.get("mcp_tools", "")
                    mcp_tools = mcp_tools_raw.split(",") if mcp_tools_raw else []
                    mode = "agent" if mcp_tools_raw else "chat"
                    agents.append({
                        "id": name.lower(),
                        "name": name.title(),
                        "desc": config.get("description", tags.get("agent.description", "")),
                        "icon": tags.get("agent.icon", AGENT_ICONS.get(name.lower(), "\U0001f916")),
                        "webhook": tags.get("agent.webhook", AGENT_WEBHOOK),
                        "config": config,
                        "mcp_tools": mcp_tools,
                        "skills": config.get("skills", []),
                        "tags": config.get("tags", []),
                        "mode": mode,
                        "promotion": {},
                    })
        except Exception:
            pass

    if agents:
        agents.sort(key=lambda a: a["id"])
        _agent_cache["data"] = agents
        _agent_cache["ts"] = now
        AGENT_DEFINITIONS = agents

    return _agent_cache["data"] or AGENT_DEFINITIONS


async def _docker_health(container: str) -> dict:
    """Check container health via docker inspect (legacy) or k8s pod status."""
    if _is_k3d_mode():
        # In k3d mode, check pod health via kubectl
        return await _k8s_pod_health(container)
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            "--format",
            "{{.State.Health.Status}}",
            container,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        health = stdout.decode().strip()
        return {
            "status": "healthy"
            if health == "healthy"
            else "degraded"
            if health == "starting"
            else "down"
        }
    except Exception:
        return {"status": "unknown"}


async def _k8s_pod_health(service_name: str) -> dict:
    """Check pod health for a service in k3d cluster."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "kubectl", "get", "pods", "-n", K3D_NAMESPACE,
            "-l", f"app.kubernetes.io/name={service_name}",
            "-o", "json", "--request-timeout=3s",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            return {"status": "unknown"}
        data = json.loads(stdout.decode())
        items = data.get("items", [])
        if not items:
            return {"status": "down"}
        pod = items[0]
        phase = pod.get("status", {}).get("phase", "Unknown")
        containers = pod.get("status", {}).get("containerStatuses", [])
        ready = all(c.get("ready", False) for c in containers) if containers else False
        if phase == "Running" and ready:
            return {"status": "healthy"}
        elif phase == "Running":
            return {"status": "degraded"}
        return {"status": "down"}
    except Exception:
        return {"status": "unknown"}


# ── k8s Polling ──────────────────────────────────────────────────────────────


async def _k8s_available() -> bool:
    """Check if kubectl is configured and can reach the cluster."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "kubectl",
            "cluster-info",
            "--request-timeout=2s",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        return proc.returncode == 0
    except Exception:
        return False


async def _kubectl_pods_ns(namespace: str) -> list[dict]:
    """Get pod status from a single k8s namespace."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "kubectl", "get", "pods", "-n", namespace, "-o", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return []
        data = json.loads(stdout.decode())
        pods = []
        for item in data.get("items", []):
            meta = item.get("metadata", {})
            status = item.get("status", {})
            phase = status.get("phase", "Unknown")
            restarts = sum(cs.get("restartCount", 0) for cs in status.get("containerStatuses", []))
            container_statuses = status.get("containerStatuses", [])
            ready = (
                all(cs.get("ready", False) for cs in container_statuses)
                if container_statuses
                else False
            )
            pods.append(
                {
                    "name": meta.get("name", ""),
                    "namespace": meta.get("namespace", ""),
                    "phase": phase,
                    "ready": ready,
                    "restarts": restarts,
                    "node": item.get("spec", {}).get("nodeName", ""),
                }
            )
        return pods
    except Exception:
        return []


async def _kubectl_pods(namespaces: list[str]) -> list[dict]:
    """Get pod status from all configured k8s namespaces."""
    results = await asyncio.gather(*[_kubectl_pods_ns(ns) for ns in namespaces])
    return [pod for ns_pods in results for pod in ns_pods]


async def _kubectl_top_pods_ns(namespace: str) -> dict[str, dict]:
    """Get pod resource usage from a single namespace."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "kubectl", "top", "pods", "-n", namespace, "--no-headers",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return {}
        result = {}
        for line in stdout.decode().strip().splitlines():
            parts = line.split()
            if len(parts) >= 3:
                result[parts[0]] = {"cpu": parts[1], "mem": parts[2]}
        return result
    except Exception:
        return {}


async def _kubectl_top_pods(namespaces: list[str]) -> dict[str, dict]:
    """Get pod resource usage from all configured namespaces."""
    results = await asyncio.gather(*[_kubectl_top_pods_ns(ns) for ns in namespaces])
    merged: dict[str, dict] = {}
    for ns_top in results:
        merged.update(ns_top)
    return merged


def _map_k8s_pod_to_service(pod_name: str) -> str | None:
    """Map a k8s pod name to a logical service id."""
    for prefix, sid in K8S_POD_TO_NODE:
        if pod_name.startswith(prefix):
            return sid
    return None


async def _kubectl_nodes() -> list[dict]:
    """Get k8s cluster node status."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "kubectl", "get", "nodes", "-o", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return []
        data = json.loads(stdout.decode())
        nodes = []
        for item in data.get("items", []):
            meta = item.get("metadata", {})
            status = item.get("status", {})
            conditions = {c["type"]: c["status"] for c in status.get("conditions", [])}
            capacity = status.get("capacity", {})
            allocatable = status.get("allocatable", {})
            roles = [
                k.replace("node-role.kubernetes.io/", "")
                for k in meta.get("labels", {})
                if k.startswith("node-role.kubernetes.io/")
            ] or ["worker"]
            nodes.append({
                "name": meta.get("name", ""),
                "ready": conditions.get("Ready") == "True",
                "roles": roles,
                "cpu_capacity": capacity.get("cpu", "?"),
                "mem_capacity": capacity.get("memory", "?"),
                "cpu_allocatable": allocatable.get("cpu", "?"),
                "mem_allocatable": allocatable.get("memory", "?"),
                "conditions": conditions,
                "pod_count": int(capacity.get("pods", 0)),
            })
        return nodes
    except Exception:
        return []


async def _check_integrations(client: httpx.AsyncClient) -> list[dict]:
    """Check cross-service integration paths."""

    async def check(ic: dict) -> dict:
        t0 = time.monotonic()
        headers = {}
        if ic.get("auth") and WEBHOOK_API_KEY:
            headers["X-API-Key"] = WEBHOOK_API_KEY
        try:
            if ic["method"] == "GET":
                r = await client.get(ic["url"], params=ic.get("params"), headers=headers, timeout=5)
            else:
                r = await client.post(ic["url"], headers=headers, timeout=5)
            ms = (time.monotonic() - t0) * 1000
            return {
                "name": ic["name"],
                "desc": ic["desc"],
                "ok": r.status_code == 200,
                "code": r.status_code,
                "response_ms": round(ms),
            }
        except Exception:
            ms = (time.monotonic() - t0) * 1000
            return {
                "name": ic["name"],
                "desc": ic["desc"],
                "ok": False,
                "code": 0,
                "response_ms": round(ms),
            }

    return await asyncio.gather(*[check(ic) for ic in INTEGRATION_CHECKS])


# ── Helm & Terraform Polling ──────────────────────────────────────────────────


async def _helm_releases_ns(namespace: str) -> list[dict]:
    """Get Helm releases in a single namespace."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "helm", "list", "-n", namespace, "-o", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            releases = json.loads(stdout.decode())
            return releases if isinstance(releases, list) else []
    except Exception:
        pass
    return []


async def _helm_releases() -> list[dict]:
    """Get Helm releases across all configured namespaces."""
    results = await asyncio.gather(*[_helm_releases_ns(ns) for ns in K8S_NAMESPACES])
    return [r for ns_releases in results for r in ns_releases]


async def _helm_history(release: str, namespace: str = "platform") -> list[dict]:
    """Get revision history for a Helm release."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "helm",
            "history",
            release,
            "-n",
            namespace,
            "-o",
            "json",
            "--max",
            "5",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            return json.loads(stdout.decode())
    except Exception:
        pass
    return []


def _terraform_status() -> dict:
    """Check Terraform initialization and state (sync — fast file checks)."""
    result: dict = {
        "available": False,
        "initialized": False,
        "resources": 0,
        "dir": str(TERRAFORM_DIR),
    }
    if not TERRAFORM_DIR.is_dir():
        return result
    result["available"] = True
    if (TERRAFORM_DIR / ".terraform").is_dir():
        result["initialized"] = True
    state_file = TERRAFORM_DIR / "terraform.tfstate"
    if state_file.exists():
        try:
            with open(state_file) as f:
                tf_state = json.load(f)
            resources = tf_state.get("resources", [])
            result["resources"] = len(resources)
            result["serial"] = tf_state.get("serial", 0)
            result["applied"] = True
        except Exception:
            pass
    else:
        result["applied"] = False
    return result


async def _fetch_argocd_apps() -> list[dict]:
    """Fetch ArgoCD Application resources from k8s."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "kubectl", "get", "applications", "-n", "platform", "-o", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return []
        data = json.loads(stdout)
        apps = []
        for item in data.get("items", []):
            spec = item.get("spec", {})
            status = item.get("status", {})
            resources = status.get("resources", [])
            apps.append({
                "name": item.get("metadata", {}).get("name", ""),
                "project": spec.get("project", ""),
                "source_path": spec.get("source", {}).get("path", ""),
                "dest_namespace": spec.get("destination", {}).get("namespace", ""),
                "sync_status": status.get("sync", {}).get("status", "Unknown"),
                "health": status.get("health", {}).get("status", "Unknown"),
                "resources": len(resources),
            })
        return apps
    except Exception:
        return []


async def _fetch_gitlab_projects() -> list[dict]:
    """Fetch GitLab projects and recent pipelines via API."""
    # Get PAT from ArgoCD repo secret (same token used for git access)
    try:
        proc = await asyncio.create_subprocess_exec(
            "kubectl", "-n", "platform", "get", "secret", "argocd-repo-gitlab",
            "-o", "jsonpath={.data.password}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0 or not stdout.strip():
            return []
        import base64

        token = base64.b64decode(stdout.strip()).decode()
    except Exception:
        return []

    gitlab_url = "http://gitlab.platform.127.0.0.1.nip.io"
    headers = {"PRIVATE-TOKEN": token}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{gitlab_url}/api/v4/projects",
                params={"per_page": 50},
                headers=headers,
            )
            if resp.status_code != 200:
                return []
            projects = resp.json()
            results = []
            for p in projects:
                pid = p.get("id")
                # Fetch latest pipeline
                pipe_resp = await client.get(
                    f"{gitlab_url}/api/v4/projects/{pid}/pipelines",
                    params={"per_page": 1},
                    headers=headers,
                )
                latest_pipeline = None
                if pipe_resp.status_code == 200:
                    pipes = pipe_resp.json()
                    if pipes:
                        latest_pipeline = {
                            "status": pipes[0].get("status", ""),
                            "ref": pipes[0].get("ref", ""),
                            "created_at": pipes[0].get("created_at", ""),
                        }
                results.append({
                    "name": p.get("name", ""),
                    "path": p.get("path_with_namespace", ""),
                    "default_branch": p.get("default_branch", ""),
                    "visibility": p.get("visibility", ""),
                    "last_activity": p.get("last_activity_at", ""),
                    "web_url": p.get("web_url", ""),
                    "latest_pipeline": latest_pipeline,
                })
            return results
    except Exception:
        return []


async def poll_platform() -> dict:
    """Poll platform deployment metadata (Helm releases, Terraform state, ArgoCD, GitLab)."""
    k8s_ok = await _k8s_available()
    releases_raw: list[dict] = []
    argocd_apps: list[dict] = []
    gitlab_projects: list[dict] = []
    if k8s_ok:
        releases_raw, argocd_apps, gitlab_projects = await asyncio.gather(
            _helm_releases(),
            _fetch_argocd_apps(),
            _fetch_gitlab_projects(),
        )

    # Enrich releases with history
    releases = []
    for r in releases_raw:
        name = r.get("name", "")
        ns = r.get("namespace", "platform")
        history = await _helm_history(name, ns) if name else []
        releases.append(
            {
                "name": name,
                "namespace": r.get("namespace", ""),
                "chart": r.get("chart", ""),
                "app_version": r.get("app_version", ""),
                "status": r.get("status", ""),
                "revision": r.get("revision", ""),
                "updated": r.get("updated", ""),
                "history": history[-3:] if history else [],
            }
        )

    tf = _terraform_status()

    return {
        "helm_releases": releases,
        "terraform": tf,
        "argocd_apps": argocd_apps,
        "gitlab_projects": gitlab_projects,
        "methods": {
            "docker_compose": any(
                s.get("container_state") == "running"
                for s in state.get("infra", {}).get("services", [])
            ),
            "helm": len(releases) > 0,
            "terraform": tf.get("initialized", False),
        },
    }


async def poll_infra() -> dict:
    """Full infrastructure poll — k8s-native (k3d mode) or docker-compose + optional k8s."""
    # Initialize k3d mode detection on first poll
    _is_k3d_mode()
    k8s_ok = await _k8s_available()

    async with httpx.AsyncClient() as client:
        coros = [
            asyncio.gather(*[_check_health(client, t) for t in HEALTH_TARGETS]),
            _check_webhooks(client),
            _docker_containers(),
            _docker_ps(),
            _mcp_servers(),
            _check_integrations(client),
            _fetch_n8n_workflows_cached(client),
            _fetch_agents_from_registry(client),
            _fetch_neo4j_health(),
            _fetch_pgvector_health(),
        ]
        if k8s_ok:
            coros.append(_kubectl_pods(K8S_NAMESPACES))
            coros.append(_kubectl_top_pods(K8S_NAMESPACES))
            coros.append(_kubectl_nodes())

        results = await asyncio.gather(*coros)

    health_results = results[0]
    webhook_results = results[1]
    containers = results[2]
    ps_data = results[3]
    mcp = results[4]
    integrations = results[5]
    workflows = results[6]
    _agents = results[7]  # populates AGENT_DEFINITIONS global
    neo4j_health = results[8]
    pgvector_health = results[9]
    k8s_pods: list[dict] = results[10] if k8s_ok else []
    k8s_top: dict[str, dict] = results[11] if k8s_ok else {}
    k8s_nodes: list[dict] = results[12] if k8s_ok else []

    # ── Docker services ──
    stats_by_name = {c["name"]: c for c in containers}

    services = []
    for h in health_results:
        container_name = f"genai-{h['name']}"
        container = stats_by_name.get(container_name, {})
        ps_info = ps_data.get(container_name, {})
        services.append(
            {
                **h,
                "cpu": container.get("cpu", "--"),
                "mem": container.get("mem", "--"),
                "container_state": ps_info.get("state", "unknown"),
                "uptime": ps_info.get("status", "--"),
            }
        )

    # Add docker-only services (no HTTP health endpoint)
    if not _is_k3d_mode():
        gw_health = await _docker_health("genai-mcp-gateway")
        gw_stats = stats_by_name.get("genai-mcp-gateway", {})
        gw_ps = ps_data.get("genai-mcp-gateway", {})
        services.append(
            {
                "name": "mcp-gateway",
                "category": "application",
                **gw_health,
                "code": 0,
                "response_ms": 0,
                "cpu": gw_stats.get("cpu", "--"),
                "mem": gw_stats.get("mem", "--"),
                "container_state": gw_ps.get("state", "unknown"),
                "uptime": gw_ps.get("status", "--"),
            }
        )
    else:
        # In k3d mode, agent-gateway IS the MCP proxy
        try:
            async with httpx.AsyncClient() as agw_client:
                r = await agw_client.get(f"{AGENT_GATEWAY_URL}/health/detail", timeout=3)
                agw_status = "healthy" if r.status_code == 200 else "degraded"
        except Exception:
            agw_status = "down"
        services.append(
            {
                "name": "agent-gateway",
                "category": "application",
                "status": agw_status,
                "code": 200 if agw_status == "healthy" else 0,
                "response_ms": 0,
                "cpu": "--",
                "mem": "--",
                "container_state": "running" if agw_status == "healthy" else "unknown",
                "uptime": "--",
            }
        )

    healthy = sum(1 for s in services if s["status"] == "healthy")
    total = len(services)

    # ── Build hierarchical topology ──
    # Merge docker + k8s status per logical service
    docker_status: dict[str, dict] = {}
    for s in services:
        docker_status[s["name"]] = {
            "status": s["status"],
            "cpu": s.get("cpu", "--"),
            "mem": s.get("mem", "--"),
        }
    for cname, info in ps_data.items():
        sid = CONTAINER_TO_NODE.get(cname)
        if sid and sid not in docker_status:
            st = "healthy" if info.get("state") == "running" else "down"
            cs = stats_by_name.get(cname, {})
            docker_status[sid] = {
                "status": st,
                "cpu": cs.get("cpu", "--"),
                "mem": cs.get("mem", "--"),
            }

    k8s_status: dict[str, dict] = {}
    k8s_pod_details: dict[str, dict] = {}
    for pod in k8s_pods:
        sid = _map_k8s_pod_to_service(pod["name"])
        if not sid:
            continue
        phase = pod.get("phase", "Unknown")
        ready = pod.get("ready", False)
        if phase == "Running" and ready:
            st = "healthy"
        elif phase == "Running":
            st = "degraded"
        else:
            st = "down"
        top = k8s_top.get(pod["name"], {})
        k8s_status[sid] = {"status": st, "cpu": top.get("cpu", "--"), "mem": top.get("mem", "--")}
        k8s_pod_details[sid] = {
            "pod": pod["name"],
            "restarts": pod.get("restarts", 0),
            "phase": phase,
            "node": pod.get("node", ""),
        }

    # Build logical topology nodes (one per service, merged status)
    topo_nodes: list[dict] = []
    for svc in BASE_SERVICES:
        sid = svc["sid"]
        d_st = docker_status.get(sid)
        k_st = k8s_status.get(sid)
        pod_info = k8s_pod_details.get(sid, {})

        deploys = []
        statuses = []
        if sid == "ollama":
            if d_st:
                deploys.append("host")
                statuses.append(d_st["status"])
        elif _is_k3d_mode():
            # k3d mode: everything is k8s, Docker containers don't exist
            if k_st:
                deploys.append("k8s")
                statuses.append(k_st["status"])
            elif d_st:
                # Health check passed via ingress — mark as k8s
                deploys.append("k8s")
                statuses.append(d_st["status"])
        else:
            if d_st:
                deploys.append("docker")
                statuses.append(d_st["status"])
            if k_st:
                deploys.append("k8s")
                statuses.append(k_st["status"])

        if not deploys:
            continue  # service not running anywhere

        # Worst status wins
        if "down" in statuses:
            combined = "down"
        elif "degraded" in statuses:
            combined = "degraded"
        else:
            combined = "healthy"

        # Pick best metrics (prefer k8s if available, it has metrics-server)
        metrics = k_st or d_st or {}

        topo_nodes.append(
            {
                "id": sid,
                **svc,
                "stack": SERVICE_STACK.get(sid, "orchestration"),
                "status": combined,
                "deploys": deploys,
                "cpu": metrics.get("cpu", "--"),
                "mem": metrics.get("mem", "--"),
                "docker": d_st,
                "k8s": k_st,
                "pod_name": pod_info.get("pod", ""),
                "restarts": pod_info.get("restarts", 0),
            }
        )

    # Enrich pgvector topology nodes with health data
    for tn in topo_nodes:
        if tn["id"] == "pgvector" and pgvector_health.get("available"):
            tn["detail"] = f"pgvector v{pgvector_health.get('extension_version', '?')}"
            vc = pgvector_health.get("vector_columns")
            if vc is not None:
                tn["detail"] += f" · {vc} vector cols"

    # Enrich ArgoCD + GitLab topology nodes from platform poll data
    platform_data = state.get("platform", {})
    argo_apps = {a["name"]: a for a in platform_data.get("argocd_apps", [])}
    gl_projects = platform_data.get("gitlab_projects", [])
    for tn in topo_nodes:
        if tn["id"] == "argocd-server" and argo_apps:
            healthy = sum(1 for a in argo_apps.values() if a["health"] == "Healthy")
            total = len(argo_apps)
            synced = sum(1 for a in argo_apps.values() if a["sync_status"] == "Synced")
            tn["detail"] = f"{healthy}/{total} healthy · {synced} synced"
        elif tn["id"] == "argocd-controller" and argo_apps:
            app_names = ", ".join(sorted(argo_apps.keys()))
            tn["detail"] = f"Managing: {app_names}"
        elif tn["id"] == "gitlab-ce" and gl_projects:
            tn["detail"] = f"{len(gl_projects)} repos"
            failed = sum(
                1
                for p in gl_projects
                if p.get("latest_pipeline", {}) and p["latest_pipeline"].get("status") == "failed"
            )
            if failed:
                tn["detail"] += f" · {failed} failing"

    # Collect dynamic edges (agents + MCP) — merged with BASE_EDGES below
    dynamic_edges: list[dict] = []

    # Dynamic agent nodes from MLflow prompt registry
    # Chat webhook health determines all agent status (all agents route through it)
    webhook_status = {w["path"]: w.get("ok", False) for w in webhook_results}
    chat_ok = webhook_status.get("/webhook/chat", False)
    for agent in AGENT_DEFINITIONS:
        sid = f"agent-{agent['id']}"
        topo_nodes.append(
            {
                "id": sid,
                "sid": sid,
                "label": agent["name"],
                "category": "agent",
                "group": "agent",
                "detail": f"MLflow prompt \u00b7 {agent['id']}",
                "stack": "agents",
                "status": "healthy" if chat_ok else "down",
                "deploys": ["mlflow"],
            }
        )
        dynamic_edges.append({"source": sid, "target": "agent-gateway", "label": "chat", "type": "tools"})
        SERVICE_STACK[sid] = "agents"

    # Dynamic MCP tool server nodes from k8s services
    # Each MCP server is slotted into its parent system's stack group
    for m in mcp:
        name = m["name"]
        sid = f"mcp-{name}"
        parent_stack = m.get("parent_stack", MCP_PARENT_STACK.get(name, "orchestration"))
        mcp_status = m.get("status", "unknown")
        detail = m.get("description", "")
        topo_nodes.append(
            {
                "id": sid,
                "sid": sid,
                "label": m.get("title", name.title()),
                "category": "mcp",
                "group": "mcp",
                "detail": detail,
                "stack": parent_stack,
                "status": mcp_status,
                "deploys": ["mcp"],
            }
        )
        dynamic_edges.append(
            {"source": sid, "target": "agent-gateway", "label": "MCP", "type": "tools"}
        )
        # Edges from MCP server to the service(s) it manages
        for target_sid, edge_label in MCP_TARGETS.get(name, []):
            dynamic_edges.append(
                {"source": sid, "target": target_sid, "label": edge_label, "type": "tools"}
            )
        SERVICE_STACK[sid] = parent_stack

    # Virtual node: benchmarks (always present if files exist)
    benchmarks_dir = PROJECT_DIR / "data" / "benchmarks"
    bench_count = len(list(benchmarks_dir.glob("*.jsonl"))) if benchmarks_dir.is_dir() else 0
    if bench_count > 0:
        bench_svc = BASE_SERVICES_MAP.get("benchmarks", {})
        topo_nodes.append(
            {
                "id": "benchmarks",
                **bench_svc,
                "stack": "experiments",
                "status": "healthy",
                "deploys": ["local"],
                "detail": f"{bench_count} JSONL files",
            }
        )

    # Dynamic k8s cluster node objects
    for knode in k8s_nodes:
        sid = f"k8s-node-{knode['name']}"
        roles = ", ".join(knode["roles"])
        # Convert memory from Ki to human-readable
        mem_raw = knode["mem_capacity"]
        try:
            mem_ki = int(mem_raw.replace("Ki", ""))
            mem_gi = round(mem_ki / 1024 / 1024, 1)
            mem_str = f"{mem_gi}Gi"
        except (ValueError, AttributeError):
            mem_str = mem_raw
        topo_nodes.append({
            "id": sid,
            "sid": sid,
            "label": knode["name"],
            "category": "k8s-node",
            "group": "platform",
            "detail": f"{roles} \u00b7 {knode['cpu_capacity']} CPU \u00b7 {mem_str}",
            "stack": "platform",
            "status": "healthy" if knode["ready"] else "down",
            "deploys": ["k8s"],
            "conditions": knode["conditions"],
        })
        SERVICE_STACK[sid] = "platform"
        # Edges from pods on this node
        for pod in k8s_pods:
            if pod.get("node") == knode["name"]:
                pod_sid = _map_k8s_pod_to_service(pod["name"])
                if pod_sid:
                    dynamic_edges.append({
                        "source": pod_sid,
                        "target": sid,
                        "label": "scheduled",
                        "type": "metadata",
                    })

    # Edges between logical service nodes (BASE_EDGES + dynamic agent/MCP edges)
    node_ids = {n["id"] for n in topo_nodes}
    node_status = {n["id"]: n["status"] for n in topo_nodes}
    all_edge_defs = list(BASE_EDGES) + dynamic_edges
    topo_edges: list[dict] = []
    for e in all_edge_defs:
        if e["source"] in node_ids and e["target"] in node_ids:
            src_st = node_status.get(e["source"], "unknown")
            tgt_st = node_status.get(e["target"], "unknown")
            topo_edges.append(
                {
                    **e,
                    "ok": src_st == "healthy" and tgt_st == "healthy",
                }
            )

    # Stack aggregate status
    stack_status: dict[str, str] = {}
    for stack in ("inference", "tracing", "experiments", "orchestration", "dataops", "platform", "agents"):
        stack_nodes = [n for n in topo_nodes if n.get("stack") == stack]
        if not stack_nodes:
            stack_status[stack] = "unknown"
        elif any(n["status"] == "down" for n in stack_nodes):
            stack_status[stack] = "down"
        elif any(n["status"] == "degraded" for n in stack_nodes):
            stack_status[stack] = "degraded"
        else:
            stack_status[stack] = "healthy"

    # Environments active
    docker_running = {
        n["id"]
        for n in topo_nodes
        if "docker" in n.get("deploys", []) or "host" in n.get("deploys", [])
    }
    k8s_running = {n["id"] for n in topo_nodes if "k8s" in n.get("deploys", [])}

    topology = {
        "nodes": topo_nodes,
        "edges": topo_edges,
        "stacks": stack_status,
        "stack_descriptions": STACK_DESCRIPTIONS,
        "environments": {
            "docker": bool(docker_running - {"ollama"}),
            "k8s": bool(k8s_running),
        },
    }

    # k8s pod summary for the services panel
    k8s_summary = []
    if k8s_ok:
        for pod in k8s_pods:
            sid = _map_k8s_pod_to_service(pod["name"])
            top = k8s_top.get(pod["name"], {})
            k8s_summary.append(
                {
                    "name": pod["name"],
                    "service": sid or pod["name"],
                    "phase": pod.get("phase", "Unknown"),
                    "ready": pod.get("ready", False),
                    "restarts": pod.get("restarts", 0),
                    "cpu": top.get("cpu", "--"),
                    "mem": top.get("mem", "--"),
                }
            )

    # Enrich agents from registry (status tied to chat webhook health)
    webhook_status_map = {w["path"]: w for w in webhook_results}
    chat_wh = webhook_status_map.get("/webhook/chat", {})
    agents = []
    for agent_def in AGENT_DEFINITIONS:
        agents.append(
            {
                **agent_def,
                "status": "healthy" if chat_wh.get("ok") else "down",
                "response_ms": chat_wh.get("response_ms"),
                "http_status": chat_wh.get("status", 0),
                "source": "mlflow",
            }
        )

    # Ops group summaries
    ops_group_status = {}
    for gid, gdef in OPS_GROUPS.items():
        group_svcs = [s for s in services if s["name"] in gdef["services"]]
        up = sum(1 for s in group_svcs if s["status"] == "healthy")
        ops_group_status[gid] = {
            "label": gdef["label"],
            "desc": gdef["desc"],
            "color": gdef["color"],
            "healthy": up,
            "total": len(group_svcs),
            "status": "healthy"
            if up == len(group_svcs) and group_svcs
            else "degraded"
            if up > 0
            else "down"
            if group_svcs
            else "unknown",
        }

    return {
        "services": services,
        "agents": agents,
        "webhooks": list(webhook_results),
        "workflows": workflows,
        "mcp_servers": mcp,
        "ops_groups": ops_group_status,
        "integrations": list(integrations),
        "topology": topology,
        "k8s_pods": k8s_summary,
        "k8s_nodes": k8s_nodes,
        "k8s_available": k8s_ok,
        "neo4j": neo4j_health,
        "pgvector": pgvector_health,
        "summary": {"healthy": healthy, "total": total},
    }


# ── MLOps Poller (30s) ───────────────────────────────────────────────────────


async def _langfuse_get(
    client: httpx.AsyncClient, path: str, params: dict | None = None
) -> dict | None:
    """GET from Langfuse public API."""
    try:
        r = await client.get(
            f"{LANGFUSE_HOST}/api/public{path}",
            auth=(LANGFUSE_PK, LANGFUSE_SK),
            params=params,
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
        # 422/500/502/503 = ClickHouse OOM or DNS, not fatal
    except Exception as e:
        print(f"[langfuse] {path} -> {e}")
    return None


async def _fetch_langfuse_summary(client: httpx.AsyncClient) -> dict:
    """Fetch trace/score/observation summary from Langfuse."""
    from_time = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    traces_data, scores_data, obs_data = await asyncio.gather(
        _langfuse_get(client, "/traces", {"fromTimestamp": from_time, "limit": 50}),
        _langfuse_get(client, "/scores", {"fromTimestamp": from_time, "limit": 50}),
        _langfuse_get(
            client,
            "/observations",
            {
                "type": "GENERATION",
                "fromStartTime": from_time,
                "limit": 50,
            },
        ),
    )

    result: dict = {"available": False}

    # Traces
    traces = (traces_data or {}).get("data", [])
    if traces:
        result["available"] = True
        latencies = [t["latency"] for t in traces if t.get("latency") and t["latency"] > 0]
        result["trace_count"] = len(traces)
        if latencies:
            sorted_lat = sorted(latencies)
            n = len(sorted_lat)
            result["latency_p50"] = round(sorted_lat[int(n * 0.5)])
            result["latency_p95"] = round(sorted_lat[min(int(n * 0.95), n - 1)])
        result["recent_traces"] = [
            {
                "id": (t.get("id") or "?")[:12],
                "name": t.get("name") or "--",
                "latency": t.get("latency"),
                "tokens": (t.get("totalUsage") or {}).get("total", 0) or 0,
                "scores": {
                    k: round(v, 2)
                    for k, v in (t.get("scores") or {}).items()
                    if isinstance(v, (int, float))
                },
                "time": _fmt_time(t.get("timestamp") or t.get("createdAt")),
            }
            for t in traces[:10]
        ]

    # Scores
    scores = (scores_data or {}).get("data", [])
    if scores:
        vals = [s["value"] for s in scores if s.get("value") is not None]
        by_name: dict[str, list[float]] = {}
        for s in scores:
            name = s.get("name", "unknown")
            val = s.get("value")
            if val is not None:
                by_name.setdefault(name, []).append(float(val))
        result["score_count"] = len(vals)
        result["score_avg"] = round(statistics.mean(vals), 2) if vals else None
        result["scores_by_name"] = {
            name: round(statistics.mean(v), 2) for name, v in by_name.items()
        }

    # Observations (tokens + per-model breakdown)
    obs = (obs_data or {}).get("data", [])
    if obs:
        total_input = sum((o.get("usage") or {}).get("input", 0) or 0 for o in obs)
        total_output = sum((o.get("usage") or {}).get("output", 0) or 0 for o in obs)
        result["tokens_input"] = total_input
        result["tokens_output"] = total_output
        result["tokens_total"] = total_input + total_output

        # Per-model breakdown (FR-006)
        by_model: dict[str, dict] = {}
        error_count = 0
        for o in obs:
            model = o.get("model") or "unknown"
            usage = o.get("usage") or {}
            m = by_model.setdefault(
                model,
                {"requests": 0, "tokens_in": 0, "tokens_out": 0, "latencies": []},
            )
            m["requests"] += 1
            m["tokens_in"] += usage.get("input", 0) or 0
            m["tokens_out"] += usage.get("output", 0) or 0
            lat = o.get("latency")
            if lat and lat > 0:
                m["latencies"].append(lat)
            if o.get("level") == "ERROR":
                error_count += 1

        result["by_model"] = {
            model: {
                "requests": m["requests"],
                "tokens_in": m["tokens_in"],
                "tokens_out": m["tokens_out"],
                "avg_latency_ms": round(statistics.mean(m["latencies"])) if m["latencies"] else 0,
            }
            for model, m in by_model.items()
        }
        result["error_rate"] = round(error_count / len(obs), 3) if obs else 0

        # Pass raw observations for inference metrics derivation in poll_mlops
        result["_raw_observations"] = obs

    return result


async def _fetch_mlflow_summary(client: httpx.AsyncClient) -> dict:
    """Fetch experiment and model summary from MLflow."""
    result: dict = {"available": False}
    try:
        r = await client.get(
            f"{MLFLOW_BASE}/api/2.0/mlflow/experiments/search",
            params={"max_results": 1000},
            timeout=10,
        )
        if r.status_code == 200:
            experiments = r.json().get("experiments", [])
            result["available"] = True
            result["experiment_count"] = len(experiments)

        r2 = await client.get(
            f"{MLFLOW_BASE}/api/2.0/mlflow/registered-models/search",
            timeout=10,
        )
        if r2.status_code == 200:
            models = r2.json().get("registered_models", [])
            result["prompt_count"] = len(models)
            total_versions = sum(len(m.get("latest_versions", [])) for m in models)
            result["prompt_versions"] = total_versions
    except Exception:
        pass
    return result


async def _fetch_sessions_summary(client: httpx.AsyncClient) -> dict:
    """Fetch session counts via n8n webhook."""
    result: dict = {"available": False}
    headers = {"Content-Type": "application/json"}
    if WEBHOOK_API_KEY:
        headers["X-API-Key"] = WEBHOOK_API_KEY
    try:
        r = await client.post(
            f"{_n8n_origin()}/webhook/sessions",
            json={"action": "list"},
            headers=headers,
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            sessions = data.get("sessions", [])
            result["available"] = True
            result["total"] = len(sessions)
            result["active"] = sum(1 for s in sessions if s.get("status") == "active")
            result["closed"] = sum(1 for s in sessions if s.get("status") == "closed")
            result["total_messages"] = sum(s.get("message_count", 0) for s in sessions)
    except Exception:
        pass
    return result


async def _fetch_datasets_summary(client: httpx.AsyncClient) -> dict:
    """Fetch dataset/benchmark counts."""
    result: dict = {"available": False}
    headers = {"Content-Type": "application/json"}
    if WEBHOOK_API_KEY:
        headers["X-API-Key"] = WEBHOOK_API_KEY
    try:
        r = await client.post(
            f"{_n8n_origin()}/webhook/datasets",
            json={"action": "list"},
            headers=headers,
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            datasets = data.get("datasets", [])
            result["available"] = True
            result["dataset_count"] = len(datasets)
    except Exception:
        pass

    # Also count local JSONL benchmark files
    benchmarks_dir = PROJECT_DIR / "data" / "benchmarks"
    if benchmarks_dir.exists():
        jsonl_files = list(benchmarks_dir.glob("*.jsonl"))
        total_cases = 0
        for f in jsonl_files:
            total_cases += sum(1 for _ in f.open())
        result["benchmark_files"] = len(jsonl_files)
        result["benchmark_cases"] = total_cases

    return result


async def _fetch_drift(client: httpx.AsyncClient) -> dict:
    """Fetch drift status."""
    result: dict = {"available": False}
    headers = {"Content-Type": "application/json"}
    if WEBHOOK_API_KEY:
        headers["X-API-Key"] = WEBHOOK_API_KEY
    try:
        r = await client.post(
            f"{_n8n_origin()}/webhook/traces",
            json={"action": "drift_check", "prompt_name": "assistant"},
            headers=headers,
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            result["available"] = True
            result.update(data)
    except Exception:
        pass
    return result


def _fmt_time(ts: str | None) -> str:
    if not ts:
        return "--"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError, AttributeError):
        return "--"


# ── Spec 020: Dashboard Enrichment Collectors ─────────────────────────────────


async def _fetch_neo4j_health() -> dict:
    """Check Neo4j health and graph stats (FR-004)."""
    neo4j_port = SERVICES.get("neo4j", {}).get("port", 7474)
    neo4j_base = (
        f"http://neo4j.genai.{K3D_DOMAIN}"
        if _is_k3d_mode()
        else f"http://localhost:{neo4j_port}"
    )
    result: dict = {"available": False, "status": "down"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(neo4j_base, timeout=3)
            if r.status_code == 200:
                data = r.json()
                result["available"] = True
                result["status"] = "healthy"
                result["version"] = data.get("neo4j_version", "unknown")
                result["edition"] = data.get("neo4j_edition", "unknown")
                # Cypher queries for graph stats
                try:
                    cr = await client.post(
                        f"{neo4j_base}/db/neo4j/query/v2",
                        json={
                            "statement": "MATCH (n) RETURN count(n) AS nodes "
                            "UNION ALL MATCH ()-[r]->() RETURN count(r) AS nodes"
                        },
                        headers={"Content-Type": "application/json"},
                        timeout=3,
                    )
                    if cr.status_code == 200:
                        rows = cr.json().get("data", {}).get("values", [])
                        if len(rows) >= 2:
                            result["node_count"] = rows[0][0] if rows[0] else 0
                            result["relationship_count"] = rows[1][0] if rows[1] else 0
                except Exception:
                    pass
    except Exception:
        pass
    return result


async def _fetch_pgvector_health() -> dict:
    """Check pgvector health and vector stats (FR-005)."""
    result: dict = {"available": False, "status": "down"}

    if _is_k3d_mode():
        return await _fetch_pgvector_health_k8s()

    # Use psql via docker exec (avoids needing asyncpg dependency)
    try:
        # Secret file existence = pgvector is configured
        if not (PROJECT_DIR / "secrets" / "pgvector_password").exists():
            return result
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            "genai-pgvector",
            "psql",
            "-U",
            "vectors",
            "-d",
            "vectors",
            "-t",
            "-A",
            "-c",
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
        if proc.returncode == 0 and stdout.strip():
            result["available"] = True
            result["status"] = "healthy"
            result["extension_version"] = stdout.decode().strip()

            # Count vector tables + total vectors
            proc2 = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                "genai-pgvector",
                "psql",
                "-U",
                "vectors",
                "-d",
                "vectors",
                "-t",
                "-A",
                "-c",
                "SELECT count(*) FROM information_schema.columns "
                "WHERE udt_name = 'vector'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=3)
            if proc2.returncode == 0 and stdout2.strip():
                result["vector_columns"] = int(stdout2.decode().strip() or "0")
    except (asyncio.TimeoutError, Exception):
        pass
    return result


async def _fetch_pgvector_health_k8s() -> dict:
    """Check pgvector health via kubectl exec (k3d mode)."""
    result: dict = {"available": False, "status": "down"}
    try:
        # Find pgvector pod
        proc = await asyncio.create_subprocess_exec(
            "kubectl", "exec", "-n", K3D_NAMESPACE,
            "deploy/genai-pgvector", "--",
            "psql", "-U", "vectors", "-d", "vectors", "-t", "-A", "-c",
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0 and stdout.strip():
            result["available"] = True
            result["status"] = "healthy"
            result["extension_version"] = stdout.decode().strip()

            proc2 = await asyncio.create_subprocess_exec(
                "kubectl", "exec", "-n", K3D_NAMESPACE,
                "deploy/genai-pgvector", "--",
                "psql", "-U", "vectors", "-d", "vectors", "-t", "-A", "-c",
                "SELECT count(*) FROM information_schema.columns WHERE udt_name = 'vector'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=5)
            if proc2.returncode == 0 and stdout2.strip():
                result["vector_columns"] = int(stdout2.decode().strip() or "0")
    except Exception:
        pass
    return result


async def _fetch_n8n_executions(client: httpx.AsyncClient) -> dict:
    """Fetch n8n execution history (FR-001)."""
    result: dict = {"available": False}
    if not N8N_API_KEY:
        return result
    try:
        r = await client.get(
            f"{_n8n_origin()}/api/v1/executions",
            params={"limit": 50, "includeData": "false"},
            headers={"X-N8N-API-KEY": N8N_API_KEY},
            timeout=5,
        )
        if r.status_code == 200:
            execs = r.json().get("data", [])
            result["available"] = True
            result["total"] = len(execs)

            now = datetime.now(timezone.utc)
            success = sum(1 for e in execs if e.get("status") == "success")
            errors_1h = sum(
                1
                for e in execs
                if e.get("status") == "error"
                and _parse_ts(e.get("startedAt")) > now - timedelta(hours=1)
            )
            errors_24h = sum(1 for e in execs if e.get("status") == "error")

            result["success_rate"] = round(success / len(execs) * 100, 1) if execs else 0
            result["errors_1h"] = errors_1h
            result["errors_24h"] = errors_24h

            # Per-workflow aggregation
            by_wf: dict[str, list[float]] = {}
            for e in execs:
                wf = e.get("workflowData", {}).get("name") or e.get("workflowId", "?")
                started = e.get("startedAt")
                finished = e.get("stoppedAt")
                if started and finished:
                    try:
                        dur = (
                            _parse_ts(finished) - _parse_ts(started)
                        ).total_seconds() * 1000
                        by_wf.setdefault(wf, []).append(dur)
                    except Exception:
                        pass

            result["avg_duration_by_workflow"] = {
                wf: round(statistics.mean(durs))
                for wf, durs in by_wf.items()
                if durs
            }

            result["recent"] = [
                {
                    "id": (e.get("id") or "?")[:12],
                    "workflow": (
                        e.get("workflowData", {}).get("name")
                        or e.get("workflowId", "?")
                    ),
                    "status": e.get("status", "unknown"),
                    "started": _fmt_time(e.get("startedAt")),
                    "finished": _fmt_time(e.get("stoppedAt")),
                    "error": (e.get("data", {}) or {}).get("error", {}).get(
                        "message", ""
                    )[:100]
                    if e.get("status") == "error"
                    else "",
                }
                for e in execs[:10]
            ]
    except Exception:
        pass
    return result


def _parse_ts(ts: str | None) -> datetime:
    """Parse ISO timestamp to datetime."""
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


async def _fetch_prompt_lifecycle(client: httpx.AsyncClient) -> list[dict]:
    """Fetch prompt version/canary details (FR-003)."""
    result: list[dict] = []
    headers = {"Content-Type": "application/json"}
    if WEBHOOK_API_KEY:
        headers["X-API-Key"] = WEBHOOK_API_KEY
    try:
        r = await client.post(
            f"{_n8n_origin()}/webhook/prompts",
            json={"action": "list"},
            headers=headers,
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            prompts = data.get("prompts", [])
            for p in prompts:
                aliases = p.get("aliases", {})
                result.append(
                    {
                        "name": p.get("name", "?"),
                        "production_version": aliases.get("production"),
                        "staging_version": aliases.get("staging"),
                        "version_count": p.get("version_count") or p.get("versions"),
                        "canary_enabled": bool(aliases.get("staging")),
                        "tags": p.get("tags", {}),
                    }
                )
    except Exception:
        pass
    return result


async def poll_mlops() -> dict:
    """Full MLOps metrics poll."""
    async with httpx.AsyncClient() as client:
        (
            langfuse,
            mlflow_summary,
            sessions,
            datasets,
            drift,
            executions,
            prompts,
        ) = await asyncio.gather(
            _fetch_langfuse_summary(client),
            _fetch_mlflow_summary(client),
            _fetch_sessions_summary(client),
            _fetch_datasets_summary(client),
            _fetch_drift(client),
            _fetch_n8n_executions(client),
            _fetch_prompt_lifecycle(client),
        )

    # Derive per-model inference metrics from Langfuse observations (FR-002/FR-006)
    inference: dict = {"available": False}
    obs_data = langfuse.get("_raw_observations", [])
    if obs_data:
        by_model: dict[str, dict] = {}
        for o in obs_data:
            model = o.get("model") or "unknown"
            usage = o.get("usage") or {}
            m = by_model.setdefault(
                model,
                {"requests": 0, "tokens_in": 0, "tokens_out": 0, "latencies": [], "errors": 0},
            )
            m["requests"] += 1
            m["tokens_in"] += usage.get("input", 0) or 0
            m["tokens_out"] += usage.get("output", 0) or 0
            lat = o.get("latency")
            if lat and lat > 0:
                m["latencies"].append(lat)
            status = o.get("statusMessage") or ""
            if "error" in status.lower() or o.get("level") == "ERROR":
                m["errors"] += 1

        inference["available"] = True
        inference["by_model"] = {
            model: {
                "requests": m["requests"],
                "tokens_in": m["tokens_in"],
                "tokens_out": m["tokens_out"],
                "avg_latency_ms": round(statistics.mean(m["latencies"])) if m["latencies"] else 0,
                "errors": m["errors"],
            }
            for model, m in by_model.items()
        }

    return {
        "langfuse": langfuse,
        "mlflow": mlflow_summary,
        "sessions": sessions,
        "datasets": datasets,
        "drift": drift,
        "executions": executions,
        "prompts": prompts,
        "inference": inference,
    }


# ── Background polling tasks ─────────────────────────────────────────────────


async def infra_loop():
    while True:
        try:
            state["infra"] = await poll_infra()
            state["timestamp"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            state["infra"]["error"] = str(e)
        await asyncio.sleep(5)


async def mlops_loop():
    await asyncio.sleep(2)  # stagger start
    while True:
        try:
            state["mlops"] = await poll_mlops()
        except Exception as e:
            state["mlops"]["error"] = str(e)
        await asyncio.sleep(30)


async def platform_loop():
    await asyncio.sleep(3)  # stagger after mlops
    while True:
        try:
            state["platform"] = await poll_platform()
        except Exception as e:
            state["platform"]["error"] = str(e)
        await asyncio.sleep(30)


# ── FastAPI App ───────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    t1 = asyncio.create_task(infra_loop())
    t2 = asyncio.create_task(mlops_loop())
    t3 = asyncio.create_task(platform_loop())
    yield
    t1.cancel()
    t2.cancel()
    t3.cancel()


_startup_ts = time.time()
app = FastAPI(title="GenAI MLOps Observatory", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "dashboard-static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/status")
async def api_status():
    return JSONResponse(state)


@app.get("/api/events")
async def api_events(request: Request):
    async def generate():
        last_infra = ""
        last_mlops = ""
        last_platform = ""
        while True:
            if await request.is_disconnected():
                break
            infra_json = json.dumps(state.get("infra", {}))
            mlops_json = json.dumps(state.get("mlops", {}))
            platform_json = json.dumps(state.get("platform", {}))
            ts = state.get("timestamp", "")
            if infra_json != last_infra:
                yield f"event: infra\ndata: {infra_json}\n\n"
                yield f"event: timestamp\ndata: {json.dumps({'timestamp': ts})}\n\n"
                last_infra = infra_json
            if mlops_json != last_mlops:
                yield f"event: mlops\ndata: {mlops_json}\n\n"
                last_mlops = mlops_json
            if platform_json != last_platform:
                yield f"event: platform\ndata: {platform_json}\n\n"
                last_platform = platform_json
            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
async def index():
    # Cache-bust static assets by injecting startup timestamp
    return HTML_PAGE.replace(".js\"", f'.js?v={int(_startup_ts)}"').replace(
        "styles.css\"", f'styles.css?v={int(_startup_ts)}"'
    )


# ── HTML Shell ────────────────────────────────────────────────────────────────
# Minimal HTML; CSS and JS are served from /static/ (dashboard-static/).

HTML_PAGE = (
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GenAI MLOps Observatory</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script>
// Shim react/jsx-runtime for ReactFlow UMD (no official UMD build exists)
window.jsxRuntime = (function(R) {
  function jsx(type, props, key) {
    var p = Object.assign({}, props);
    if (key !== undefined) p.key = key;
    var c = p.children; delete p.children;
    return Array.isArray(c) ? R.createElement.apply(R, [type, p].concat(c))
         : c !== undefined ? R.createElement(type, p, c)
         : R.createElement(type, p);
  }
  return { jsx: jsx, jsxs: jsx, Fragment: R.Fragment };
})(React);
</script>
<script src="https://unpkg.com/@xyflow/react@12/dist/umd/index.js"></script>
<link href="https://unpkg.com/@xyflow/react@12/dist/style.css" rel="stylesheet">
<link href="/static/styles.css" rel="stylesheet">
<script>window.__DRIFT_CONFIG = """
    + json.dumps(CFG.get("drift", {}))
    + """;</script>
</head>
<body>
<header>
  <h1>GenAI MLOps Observatory</h1>
  <div class="header-right">
    <span id="summary-badge" class="status-badge degraded">Connecting...</span>
    <span id="timestamp" class="timestamp">--:--:--</span>
  </div>
</header>

<div id="platform-bar"></div>

<div class="tab-bar">
  <button class="tab-btn active" data-tab="topology">Topology</button>
  <button class="tab-btn" data-tab="services">Services</button>
  <button class="tab-btn" data-tab="operations">Operations</button>
</div>

<div id="tab-topology" class="tab-content active">
  <section>
    <div class="section-title">Platform Architecture</div>
    <div id="topology-container"></div>
  </section>
  <section>
    <div class="section-title">Integration Status</div>
    <div id="integrations"></div>
  </section>
</div>

<div id="tab-services" class="tab-content">
  <section>
    <div id="ops-groups" class="ops-group-bar"></div>
  </section>
  <section>
    <div class="section-title">Infrastructure</div>
    <div id="services" class="card-grid"></div>
  </section>
  <section>
    <div class="section-title">Agents</div>
    <div id="agents" class="agent-grid"></div>
  </section>
  <section>
    <div class="three-col">
      <div>
        <div class="section-title">n8n Workflows</div>
        <div id="workflows"></div>
      </div>
      <div>
        <div class="section-title">Webhooks</div>
        <div id="webhooks" class="webhook-grid"></div>
      </div>
      <div>
        <div class="section-title">MCP Servers</div>
        <div id="mcp" class="mcp-grid"></div>
      </div>
    </div>
  </section>
  <section>
    <div class="two-col">
      <div>
        <div class="section-title">Deployments</div>
        <div id="deployments"></div>
      </div>
      <div>
        <div class="section-title">Kubernetes Pods</div>
        <div id="k8s-pods"></div>
      </div>
    </div>
  </section>
</div>

<div id="tab-operations" class="tab-content">
  <section>
    <div class="section-title">Agent Operations (24h)</div>
    <div id="mlops-panels" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px"></div>
  </section>
  <section>
    <div class="section-title">n8n Executions</div>
    <div id="executions-table"></div>
  </section>
  <section>
    <div class="section-title">Recent Traces</div>
    <div id="traces-table"></div>
  </section>
</div>

<script src="/static/topology.js"></script>
<script src="/static/panels.js"></script>
<script src="/static/app.js"></script>
</body>
</html>"""
)


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse as ap

    parser = ap.ArgumentParser(description="GenAI MLOps Platform Observatory")
    parser.add_argument("--port", type=int, default=DASHBOARD_PORT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--k3d", action="store_true", help="Force k3d/k8s-native mode (no Docker queries)")
    args = parser.parse_args()

    if args.k3d:
        os.environ["DASHBOARD_K3D"] = "true"

    import uvicorn

    mode = "k3d" if _is_k3d_mode() else "docker-compose"
    print(f"Observatory starting at http://localhost:{args.port} (mode: {mode})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

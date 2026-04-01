# Platform Monorepo

[![Build Images](https://github.com/r-aas/platform_monorepo/actions/workflows/build-images.yml/badge.svg)](https://github.com/r-aas/platform_monorepo/actions/workflows/build-images.yml)
[![Lint Charts](https://github.com/r-aas/platform_monorepo/actions/workflows/lint-charts.yml/badge.svg)](https://github.com/r-aas/platform_monorepo/actions/workflows/lint-charts.yml)
[![Release](https://github.com/r-aas/platform_monorepo/releases/latest)](https://github.com/r-aas/platform_monorepo/releases)

A reference implementation for **AgentOps end-to-end** — running entirely on a single Mac. No cloud. No API keys. Everything local, reproducible, and observable.

This is what a complete agent operations system looks like when you wire together best-of-breed open-source tools: agent definitions, prompt lifecycle, experiment tracking, tool federation, autonomous scheduling, LLM observability, and GitOps deployment — all in one repo.

```
task up    # ~20 min from zero to fully operational
```

## Why This Exists

Building AI agents is easy. Operating them is hard. There's no single tool that covers the full lifecycle:

| Problem | What's needed | What this repo uses |
|---------|---------------|---------------------|
| Agents need tools | Standardized tool interface | **9 MCP servers** behind a unified gateway (243 tools) |
| Agents need memory | Persistent context across runs | **pgvector** with per-agent TTL and memory categories |
| Agents need scheduling | Autonomous execution on cadence | **kagent** CRDs + k8s CronJobs |
| Prompts need versioning | Track what changed and when | **MLflow** prompt registry with aliases and canary routing |
| Prompts need evaluation | Know if changes help or hurt | **LLM-as-judge** eval pipeline with A/B testing |
| LLM calls need observability | Cost, latency, quality tracking | **Langfuse** tracing + drift detection |
| Everything needs deployment | Reproducible, auditable, rollback-able | **ArgoCD** GitOps from in-cluster **GitLab** |
| Everything needs to talk | Standard protocols | **OpenAI-compatible API**, **A2A protocol**, **MCP** |

This repo is the answer to "how do I actually run all of this together?"

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    macOS (Apple Silicon)                  │
│                                                          │
│  Ollama (native, Metal GPU)                              │
│     ↑                                                    │
│  ┌──┴────────────────────────────────────────────────┐   │
│  │  k3d cluster "mewtwo"                             │   │
│  │                                                   │   │
│  │  LiteLLM ──→ Ollama (192.168.65.254:11434)           │   │
│  │     ↑                                             │   │
│  │  n8n (17 workflows) ──→ MLflow (prompts/evals)    │   │
│  │     ↑                       ↓                     │   │
│  │  agentgateway ←── 9 MCP servers (243 tools)       │   │
│  │     ↑                                             │   │
│  │  kagent (6 agents on CronJob schedules)           │   │
│  │     ↑                                             │   │
│  │  ArgoCD ←── GitLab CE (in-cluster git)            │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
│  Colima VM (dockerd, 8 CPU, 32 GB RAM)                   │
└─────────────────────────────────────────────────────────┘
```

### How the layers connect

**You ask a question** → n8n `/webhook/chat` receives it → looks up the agent's system prompt from MLflow → classifies the task → picks the right task-specific prompt → calls LiteLLM → LiteLLM routes to Ollama → response is traced to Langfuse and MLflow → returned to you with a `trace_id` for feedback.

**An agent runs autonomously** → kagent CronJob fires → POSTs to the agent's A2A endpoint → agent loads its memory from pgvector → picks tools from the MCP gateway → executes → writes results back to memory → logs trace.

**You change a prompt** → commit to GitLab → ArgoCD syncs → n8n workflow promotion hook patches URLs and upserts workflows → new prompt version is live. Roll back by reverting the commit.

## Services

| Service | Purpose | URL |
|---------|---------|-----|
| **n8n** | Workflow automation — 17 workflows expose webhook APIs for chat, prompts, eval, tracing | http://n8n.platform.127.0.0.1.nip.io |
| **MLflow** | Prompt registry (versioned, with aliases), experiment tracking, eval storage | http://mlflow.platform.127.0.0.1.nip.io |
| **LiteLLM** | OpenAI-compatible proxy — routes to Ollama, handles auth, per-key access | http://litellm.platform.127.0.0.1.nip.io |
| **Langfuse** | LLM observability — traces, scores, cost analysis, drift detection | http://langfuse.platform.127.0.0.1.nip.io |
| **Gateway** | Unified entry point — agent-gateway (Python) + agentgateway MCP proxy (Rust) | http://gateway.platform.127.0.0.1.nip.io |
| **ArgoCD** | GitOps controller — syncs all 35 Helm charts from GitLab | http://argocd.platform.127.0.0.1.nip.io |
| **GitLab CE** | In-cluster git — source of truth for ArgoCD, no external dependencies | http://gitlab.platform.127.0.0.1.nip.io |
| **ODD Platform** | Data catalog — metadata, lineage, quality (PostgreSQL-only, ARM64 native) | http://odd.platform.127.0.0.1.nip.io |
| **Plane** | Project management — issues, sprints, backlogs | http://plane.platform.127.0.0.1.nip.io |
| **MinIO** | S3-compatible object storage for MLflow artifacts | http://minio.platform.127.0.0.1.nip.io |

All URLs use [nip.io](https://nip.io) wildcard DNS — `*.platform.127.0.0.1.nip.io` resolves to `127.0.0.1`. No `/etc/hosts` editing needed.

## Agents

Six autonomous agents, each with a defined role, schedule, tool access, and memory:

| Agent | Schedule | What it does | Tools |
|-------|----------|--------------|-------|
| **platform-admin** | Every 15 min | Watches cluster health, responds to incidents, manages k8s resources | kubernetes, gitlab, kagent, ollama |
| **project-coordinator** | Hourly | Triages backlog, manages sprints, reports status across Plane and GitLab | kubernetes, plane, gitlab |
| **data-engineer** | Every 2 hours | Manages data catalog, traces lineage, runs quality checks, handles ingestion | kubernetes, minio, mlflow |
| **mlops** | Every 4 hours | Tracks experiments, manages model lifecycle, monitors drift | kubernetes, mlflow, langfuse, minio, ollama |
| **developer** | Every 6 hours | Generates code, reviews PRs, runs security audits, manages CI/CD | kubernetes, gitlab |
| **qa-eval** | Nightly (2 AM) | Runs benchmarks, detects regressions, evaluates prompt quality | kubernetes, mlflow, langfuse |

Each agent has:
- **Autonomy guardrails** — max budget ($2-10), max turns (100-300), approval gates for destructive ops
- **Persistent memory** — pgvector with categorized memories (incidents, decisions, patterns, baselines)
- **Collaboration graph** — agents can delegate to each other via A2A protocol

Agent definitions live in `agents/` as YAML specs.

## Workflows (n8n)

The 17 n8n workflows are the API layer of the platform. Key endpoints:

| Endpoint | Workflow | What it does |
|----------|----------|--------------|
| `POST /webhook/chat` | Chat | Unified chat — agent mode (with MCP tools) or plain LLM. Task classification, session management, trace logging |
| `POST /webhook/prompts` | Prompt CRUD | Create, update, delete, promote, diff, canary config for versioned prompts |
| `POST /webhook/eval` | Prompt Eval | Run test cases with LLM-as-judge scoring. A/B eval between production and staging |
| `POST /webhook/traces` | Tracing | Log executions, submit feedback, set baselines, detect drift |
| `POST /webhook/sessions` | Sessions | Persistent conversation history with append/close lifecycle |
| `POST /webhook/datasets` | Datasets | Upload and manage evaluation datasets |
| `POST /webhook/experiments` | Experiments | Browse MLflow experiments, runs, and metrics |
| `POST /webhook/agents` | Agent Catalog | Query and manage registered agents |
| `GET /webhook/v1/models` | OpenAI Compat | Drop-in OpenAI API — lists prompts as models |
| `POST /webhook/v1/chat/completions` | OpenAI Compat | Chat completions with prompt-enhanced routing and canary support |
| `POST /webhook/a2a` | A2A Server | Google Agent-to-Agent protocol (JSON-RPC 2.0) |

Workflow JSONs live in `n8n-data/workflows/` and are promoted to the cluster via a Helm post-install hook that clones the repo, patches service URLs, and upserts via the n8n REST API.

## MCP Servers (Tool Federation)

Nine MCP servers expose platform capabilities as tools. The **agentgateway** (Rust, Linux Foundation) federates all of them into a single endpoint:

| Server | Wraps | Example tools |
|--------|-------|---------------|
| **mcp-kubernetes** | k8s API | `kubectl_get`, `kubectl_logs`, `exec_in_pod`, `kubectl_apply` |
| **mcp-gitlab** | GitLab CE | `create_issue`, `create_merge_request`, `list_pipelines` |
| **mcp-mlflow** | MLflow API | `search_experiments`, `log_metric`, `get_model_version` |
| **mcp-langfuse** | Langfuse API | `get_traces`, `create_score`, `get_usage` |
| **mcp-n8n** | n8n API | `list_workflows`, `execute_workflow`, `get_executions` |
| **mcp-plane** | Plane API | `create_issue`, `list_cycles`, `update_sprint` |
| **mcp-minio** | MinIO S3 | `list_buckets`, `get_object`, `put_object` |
| **mcp-ollama** | Ollama API | `list_models`, `pull_model`, `generate` |
| **mcp-odd-platform** | ODD Platform | `search_catalog`, `get_upstream_lineage`, `get_quality_tests` |

**243 tools** available in a single MCP session at `gateway.platform.127.0.0.1.nip.io/mcp/all`. Tool names are prefixed by backend (e.g., `kubernetes_kubectl_get`, `gitlab_create_issue`).

Per-backend routes also available: `/mcp/kubernetes`, `/mcp/gitlab`, `/mcp/mlflow`, etc.

## Prompt Lifecycle

The platform implements a complete prompt-as-code lifecycle:

```
seed → eval + judge → optimize → benchmark → promote → canary → monitor
```

1. **Version** — Prompts stored in MLflow with semantic versioning, `production` and `staging` aliases
2. **Evaluate** — Run test cases against prompts, score with LLM-as-judge (built-in or custom criteria)
3. **A/B test** — Canary routing sends configurable traffic percentage to staging version
4. **Promote** — Move staging to production when metrics improve
5. **Monitor** — Trace every LLM call, detect drift against baselines, alert on regression

## Prerequisites

**Minimum**: Apple Silicon Mac with 64 GB RAM (see [Hardware Requirements](#hardware-requirements) for details).

| Tool | Version | Install |
|------|---------|---------|
| macOS | 14+ (Apple Silicon) | — |
| Colima | 0.8+ | `brew install colima` |
| Docker CLI | 27+ | `brew install docker` |
| k3d | 5.7+ | `brew install k3d` |
| kubectl | 1.30+ | `brew install kubectl` |
| Helm | 3.16+ | `brew install helm` |
| helmfile | 0.169+ | `brew install helmfile` |
| Task | 3.40+ | `brew install go-task` |
| Ollama | 0.6+ | [ollama.com](https://ollama.com) |
| uv | 0.6+ | `brew install uv` |
| jq, yq | latest | `brew install jq yq` |

```bash
brew install colima docker k3d kubectl helm helmfile go-task uv jq yq
brew install --cask ollama
```

## Quick Start

```bash
# 1. Clone
git clone https://github.com/r-aas/platform_monorepo.git
cd platform_monorepo

# 2. Create secrets
cp envs/secrets.env.example envs/secrets.env
# Defaults work for local dev — edit if you want custom passwords

# 3. Bootstrap everything
task up
```

That's it. `task up` handles everything: preflight checks → starts Colima VM → starts Ollama → pulls models (glm-4.7-flash + nomic-embed-text) → creates k3d cluster → helmfile bootstrap → GitLab setup → pulls/builds images → ArgoCD sync → n8n workflow promotion → agent deployment → smoke tests. ~20 minutes on first run.

### Verify it works

```bash
task smoke           # Hit every endpoint, report pass/fail
task urls            # Print all URLs with credentials
task status          # Full platform health check
```

### Try it

```bash
# Chat with an agent
curl -X POST http://n8n.platform.127.0.0.1.nip.io/webhook/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "what experiments are running?", "agent_name": "mlops"}'

# Chat with MCP tools (agent can call any of 243 tools)
curl -X POST http://n8n.platform.127.0.0.1.nip.io/webhook/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "list pods in the genai namespace", "config": {"mcp_tools": "all"}}'

# Use the OpenAI-compatible API
curl -X POST http://n8n.platform.127.0.0.1.nip.io/webhook/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "glm-4.7-flash", "messages": [{"role": "user", "content": "hello"}]}'

# Initialize an MCP session (all 243 tools)
curl -X POST http://gateway.platform.127.0.0.1.nip.io/mcp/all \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

## Day-to-Day Operations

```bash
task stop            # Pause (preserves state, frees RAM — ~21s)
task start           # Resume (~7 min)
task restart         # Full restart (handles crashes)
task down            # Destroy cluster (PV data preserved)
task smoke           # Verify all endpoints
task status          # Platform health overview
task urls            # All URLs + credentials
task doctor          # Preflight + smoke combined
```

## Repo Structure

```
charts/                 # 35 Helm charts (ArgoCD-managed after bootstrap)
  genai-n8n/            #   n8n + workflow promotion hook
  genai-mlflow/         #   MLflow tracking server
  genai-litellm/        #   LLM proxy
  genai-agentgateway/   #   Rust MCP proxy (Linux Foundation)
  genai-agent-gateway/  #   Python agent gateway (custom)
  genai-langfuse/       #   LLM observability
  genai-odd-platform/   #   Data catalog (ODD Platform)
  genai-plane/          #   Project management
  genai-minio/          #   Object storage
  genai-agentregistry/  #   Agent/skill catalog + semantic search
  genai-mcp-*/          #   Individual MCP server charts (9)
  genai-pg-*/           #   PostgreSQL instances (n8n, mlflow, plane)
  gitlab-ce/            #   In-cluster source control
  argocd/               #   GitOps controller
  ingress-nginx/        #   Ingress controller
n8n-data/workflows/     # 17 workflow JSONs (promoted to cluster via Helm hook)
agents/                 # Agent YAML definitions (6 agents + shared config)
skills/                 # 21 skill definitions
scripts/                # Bootstrap, import, benchmark, smoke test scripts
specs/                  # Feature specs (001-029, spec-driven development)
services/
  agent-gateway/        # Python FastAPI — agent registry, skill catalog, MCP proxy
images/                 # 19 Docker image builds (MCP servers, custom services)
mcp-servers/            # MCP server catalog config
data/                   # Seed prompts, benchmarks, training data
docs/                   # Architecture docs, environment guide
envs/                   # Environment config (global.env, secrets.env)
manifests/              # Raw k8s manifests + CRDs
taskfiles/              # Taskfile includes (mcp, mlops, quality, status, workflows)
helmfile.yaml           # Bootstrap-only (seeds ArgoCD + infra)
Taskfile.yml            # Root task runner
```

## Secrets

All secrets live in `envs/secrets.env` (gitignored). The example file ships with safe defaults for local dev:

| Secret | What it's for |
|--------|---------------|
| `PG_MLFLOW_PASSWORD` | MLflow PostgreSQL |
| `PG_LANGFUSE_PASSWORD` | Langfuse PostgreSQL |
| `PG_PLANE_PASSWORD` | Plane PostgreSQL |
| `MLFLOW_FLASK_SECRET_KEY` | MLflow session signing |
| `MINIO_ROOT_USER` / `PASSWORD` | MinIO S3 storage |
| `LITELLM_API_KEY` | LiteLLM proxy auth |
| `GITLAB_PAT` | Auto-generated during `task up` |
| `PLANE_API_TOKEN` | Plane project management API |
| `LANGFUSE_PUBLIC_KEY` / `SECRET_KEY` | Langfuse observability |
| `PGVECTOR_PASSWORD` | Shared pgvector (ODD Platform, agent registry) |

`task seed-secrets` creates k8s secrets from this file. Use `--force` to recreate.

## Troubleshooting

### Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Pods stuck in `Pending` | Colima VM out of resources | `colima stop && colima start --cpu 8 --memory 32 --disk 200` |
| `ImagePullBackOff` on MCP pods | Custom images not on all k3d nodes | `task build-images` (imports to all nodes) |
| n8n webhooks return 404 | Workflows not activated after import | `task smoke` to check; workflow promotion hook runs on deploy |
| MLflow rejects requests | DNS rebinding protection | Chart sets `disableSecurityMiddleware` flag — check ArgoCD sync |
| Ollama unreachable from cluster | Wrong host IP | Pods must use `192.168.65.254` (Colima gateway), not `localhost` |
| LiteLLM 401 errors | Missing API key in n8n | Check `LITELLM_API_KEY` in secrets.env, run `task seed-secrets` |
| ArgoCD sync stuck | Failed Helm hook blocking | Delete the failed Job: `kubectl delete job <name> -n genai` |
| PostgreSQL won't start | sshfs doesn't support chown | local-path provisioner must use `/var/lib/rancher/k3s/local-storage` (overlay FS) |
| `disk-pressure` taint after restart | Colima VM disk was full | Free space, restart Colima, then `kubectl taint nodes <node> node.kubernetes.io/disk-pressure-` |

### Diagnostic commands

```bash
task doctor          # Preflight checks + smoke tests
task status          # Full platform status
task smoke           # Hit every endpoint
kubectl get pods -n genai | grep -v Running    # Find unhealthy pods
kubectl logs deploy/genai-n8n -n genai         # n8n logs
kubectl logs deploy/genai-mlflow -n genai      # MLflow logs
```

## How it's deployed

1. **helmfile** bootstraps the cluster — installs ingress-nginx, creates namespaces, deploys GitLab CE and ArgoCD
2. **ArgoCD** takes over — watches GitLab for changes to `charts/`, auto-syncs all 35 Helm charts
3. **Workflow promotion** — a Helm post-install hook on the n8n chart clones this repo, patches service URLs for k8s DNS, and upserts all workflows via the n8n REST API
4. **Agent scheduling** — kagent CRDs define agents, k8s CronJobs POST to their A2A endpoints on cadence

Change anything in `charts/` → push to GitLab → ArgoCD syncs automatically. That's it.

## Hardware Requirements

The platform runs 35 Helm charts totaling **9.3 CPU cores** and **12.5 GB memory** in requests (26.5 GB limits), plus Ollama running natively on the Mac for GPU inference. Here's what you actually need:

### Resource breakdown

| Component | CPU | RAM | Disk |
|-----------|-----|-----|------|
| Colima VM (k3d cluster) | 8 cores | 24-32 GB | 200 GB |
| Ollama (native, Metal GPU) | shared | 19 GB (glm-4.7-flash) | 20 GB (model files) |
| macOS + apps | shared | ~6 GB | — |

### Machine tiers

With glm-4.7-flash (19 GB) + Colima VM + macOS:

| Machine | RAM | Works? | Notes |
|---------|-----|--------|-------|
| 24 GB | 24 GB | No | Not enough for VM + model + macOS |
| 36 GB | 36 GB | No | Can't fit 19 GB model + usable VM |
| 48 GB | 48 GB | Tight | 22 GB VM, expect memory pressure under load |
| 64 GB | 64 GB | Yes | 32 GB VM, comfortable headroom |
| 96-128 GB | 96-128 GB | Ideal | Full resource limits, room for larger models |

### LLM model

The platform uses `glm-4.7-flash` (19 GB) for inference and `nomic-embed-text` (274 MB) for embeddings:

```bash
ollama pull glm-4.7-flash
ollama pull nomic-embed-text
```

### Adjusting for smaller machines

If you have 36-48 GB RAM, reduce the Colima VM size:

```bash
# In task up, or manually:
colima start --cpu 6 --memory 20 --disk 150
```

The cluster will still run — pods will schedule with less headroom and some may restart under memory pressure.

### Disk space

| What | Size |
|------|------|
| Colima VM disk | 200 GB (thin-provisioned, grows as needed) |
| Persistent volumes (databases, storage) | ~59 GB |
| Docker images (all services) | ~25 GB |
| Ollama models | ~20 GB (glm-4.7-flash + nomic-embed-text) |
| Repo + tools | ~2 GB |

Developed on a MacBook Pro M4 Max (128 GB RAM, 16 cores).

## License

MIT

# Platform Monorepo

Local-first AI/ML platform running entirely on a single Mac. 35 Helm charts, 8 autonomous agents, 9 MCP servers, 243 federated tools — all managed by ArgoCD on k3d.

## What This Is

A complete agentic AI platform that runs on your laptop. No cloud required. Everything is Helm-charted, GitOps-managed, and reproducible from zero with one command.

```
task up    # ~20 min from nothing to fully operational
```

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    macOS (Apple Silicon)                  │
│                                                          │
│  Ollama (native, Metal GPU)                              │
│     ↑                                                    │
│  ┌──┴────────────────────────────────────────────────┐   │
│  │  k3d cluster "mewtwo"                             │   │
│  │                                                   │   │
│  │  LiteLLM ──→ Ollama (192.168.5.2:11434)           │   │
│  │     ↑                                             │   │
│  │  n8n (workflows) ──→ MLflow (experiments/prompts) │   │
│  │     ↑                    ↓                        │   │
│  │  agentgateway ←── 9 MCP servers (243 tools)       │   │
│  │     ↑                                             │   │
│  │  kagent (8 agents on CronJob schedules)           │   │
│  │     ↑                                             │   │
│  │  ArgoCD ←── GitLab CE (in-cluster git)            │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
│  Colima VM (dockerd, 8 CPU, 32 GB RAM)                   │
└─────────────────────────────────────────────────────────┘
```

### Services

| Layer | Service | Purpose |
|-------|---------|---------|
| **Git + GitOps** | GitLab CE, ArgoCD | In-cluster source control + continuous deployment |
| **LLM** | Ollama, LiteLLM | Native GPU inference + OpenAI-compatible proxy |
| **Orchestration** | n8n | Workflow automation, webhook APIs, AI agent runtime |
| **Tracking** | MLflow | Experiment tracking, prompt registry, model registry |
| **Observability** | Langfuse | LLM tracing, scoring, cost analysis |
| **Data Catalog** | DataHub | Metadata, lineage, quality checks |
| **Project Mgmt** | Plane | Issue tracking, sprints, backlogs |
| **Storage** | MinIO, PostgreSQL (x4), pgvector | S3 artifacts, per-service databases, embeddings |
| **Agents** | kagent (CNCF) | 8 autonomous agents on k8s CronJobs |
| **MCP Proxy** | agentgateway (LF) | Rust MCP proxy, 9 backends, 243 federated tools |
| **Agent Catalog** | agentregistry | Agent/skill/MCP server registry with semantic search |

## Prerequisites

| Requirement | Version | Install |
|-------------|---------|---------|
| macOS | 14+ (Apple Silicon) | — |
| Homebrew | latest | [brew.sh](https://brew.sh) |
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
# Install all at once
brew install colima docker k3d kubectl helm helmfile go-task uv jq yq
brew install --cask ollama
```

## Quick Start

```bash
# 1. Clone
git clone https://github.com/r-aas/platform_monorepo.git
cd platform_monorepo

# 2. Pull an LLM model
ollama pull glm-4.7-flash   # or qwen2.5:14b, llama3.1:8b, etc.

# 3. Create secrets file
cp envs/secrets.env.example envs/secrets.env
# Edit envs/secrets.env with your values (or leave defaults for local dev)

# 4. Bootstrap everything
task up
```

`task up` does: preflight checks → Colima VM → Ollama verify → k3d cluster → helmfile bootstrap → GitLab setup → image builds → ArgoCD sync → n8n workflow import → agent deployment → smoke tests.

## Usage

```bash
task status          # Full platform status
task urls            # All service URLs + credentials
task smoke           # Verify everything is reachable
task stop            # Pause (preserves state, frees RAM)
task start           # Resume (~7 min)
task restart         # Full restart (handles crashes)
task down            # Destroy cluster (PV data preserved)
```

### Key URLs (after `task up`)

| Service | URL |
|---------|-----|
| ArgoCD | http://argocd.platform.127.0.0.1.nip.io |
| n8n | http://n8n.platform.127.0.0.1.nip.io |
| MLflow | http://mlflow.platform.127.0.0.1.nip.io |
| GitLab | http://gitlab.platform.127.0.0.1.nip.io |
| Langfuse | http://langfuse.platform.127.0.0.1.nip.io |
| Plane | http://plane.platform.127.0.0.1.nip.io |
| DataHub | http://datahub.platform.127.0.0.1.nip.io |
| Gateway | http://gateway.platform.127.0.0.1.nip.io |
| Gateway MCP | http://gateway.platform.127.0.0.1.nip.io/mcp |
| LiteLLM | http://litellm.platform.127.0.0.1.nip.io |

### Chat with MCP Tools

```bash
curl -X POST http://n8n.platform.127.0.0.1.nip.io/webhook/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"list namespaces in the cluster","config":{"mcp_tools":"all"}}'
```

### MCP Tool Federation

```bash
# Initialize MCP session (all 243 tools from 8 backends)
curl -X POST http://gateway.platform.127.0.0.1.nip.io/mcp/all \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

## Structure

```
charts/              # 35 Helm charts (ArgoCD-managed)
services/            # Custom services (agent-gateway, datahub-bridge)
agents/              # Agent YAML definitions (6 agents + shared config)
skills/              # Skill definitions (21 skills)
scripts/             # Bootstrap, setup, ingestion, secrets
specs/               # Feature specs (spec-driven development)
taskfiles/           # Taskfile includes
envs/                # Environment config (global.env, secrets.env)
manifests/           # Raw k8s manifests + CRDs
images/              # Custom Docker image builds (13 images)
mcp-servers/         # MCP server configs
helmfile.yaml        # Bootstrap-only (seeds ArgoCD + infra)
Taskfile.yml         # Root task runner
```

## Companion Repo

The n8n workflow definitions, smoke tests, and MLflow prompt seeds live in [genai-mlops](https://github.com/r-aas/genai-mlops). It's automatically imported during `task up`.

## Hardware

Developed on a MacBook Pro M4 Max (128 GB RAM, 16 cores). The Colima VM is configured for 8 CPU / 32 GB RAM / 200 GB disk. Smaller machines will work but may need reduced resource limits in chart values.

## License

MIT

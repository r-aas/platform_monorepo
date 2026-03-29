# platform_monorepo

Shared infrastructure for the k3d "mewtwo" platform. Helm charts, agent definitions, scripts, specs, and the agent-gateway service.

## Structure

```
charts/              # 28 Helm charts (ArgoCD manages all post-bootstrap)
services/
  agent-gateway/     # Unified service: agent registry, OpenAI chat, MCP proxy, A2A cards, sandbox
  datahub-obsidian-source/  # DataHub custom source for Obsidian vault
  n8n-datahub-bridge/       # n8n → DataHub event bridge
agents/              # Agent YAML definitions (mlops, developer, platform-admin + _shared)
scripts/             # Bootstrap, setup, ingestion, lineage, quality, secrets
specs/               # Spec-driven feature designs (001, 015, 020-027)
taskfiles/           # Taskfile includes (agents, arch, sandbox, etc.)
envs/                # Environment config (global.env, secrets.env)
manifests/           # Raw k8s manifests
images/              # Custom Docker image builds
mcp-servers/         # MCP server configs
helmfile.yaml        # Bootstrap-only (seeds ArgoCD, ingress, GitLab)
Taskfile.yml         # Root task runner (symlinked to ~/work/Taskfile.yml)
RESUME.md            # Session state for /continue
BACKLOG.md           # Prioritized task queue (P0-P3)
```

## Key Commands

```bash
task up              # Full bootstrap: colima → k3d → helmfile → GitLab → images → ArgoCD → n8n → agents → smoke
task start           # Resume paused cluster
task stop            # Pause cluster (preserves state)
task down            # Destroy cluster (PV data preserved)
task smoke           # Verify all services reachable
task status          # Full platform status
task urls            # Print all URLs + credentials

task n8n-import      # Import genai-mlops workflows into n8n
task agent-sync      # Sync agent YAMLs to MLflow prompt registry
task seed-secrets    # Create k8s secrets from ~/work/envs/secrets.env
task seed-registry   # Seed agent registry with agents + env bindings

task datahub-ingest  # Register DataHub ingestion sources (PostgreSQL)
task datahub-lineage # Emit cross-service lineage edges
task datahub-quality # Run data quality checks against platform DBs

task benchmark-smoke # Quick 1-agent, 3-case benchmark
task benchmark-agents # Full agent benchmarks with LLM-as-judge
```

## Agent Gateway (`services/agent-gateway/`)

Python 3.12 + FastAPI. Single service that consolidates:

- **Agent registry**: CRUD via PostgreSQL + pgvector (replacing MLflow tag-based storage)
- **OpenAI-compatible chat**: `/v1/chat/completions` with `model=agent:{name}` routing
- **MCP proxy**: Aggregates tools from k8s MCP servers, exposes SSE + Streamable HTTP
- **MCP discovery**: Tool search via embeddings
- **A2A cards**: `/.well-known/agent-card.json`
- **Sandbox**: Ephemeral k8s Jobs for code execution
- **Skill catalog**: Hybrid search over agent skills

### Dev workflow

```bash
cd services/agent-gateway
uv sync
uv run pytest
uv run ruff check .
```

### Building + deploying

```bash
task build-images    # Builds all images including agent-gateway, imports to k3d
# Or manually:
docker build -t agent-gateway:latest services/agent-gateway/
k3d image import agent-gateway:latest -c mewtwo
kubectl rollout restart deployment/genai-agent-gateway -n genai
```

## Helm Charts

28 charts in `charts/`. All managed by ArgoCD after bootstrap. Key charts:

| Chart | Namespace | Purpose |
|-------|-----------|---------|
| `genai-agent-gateway` | genai | Agent gateway service |
| `genai-n8n` | genai | Workflow automation |
| `genai-mlflow` | genai | Experiment tracking, prompt registry |
| `genai-litellm` | genai | LLM proxy to Ollama |
| `genai-langfuse` | genai | LLM observability |
| `genai-datahub` | genai | Data catalog |
| `genai-minio` | genai | Object storage |
| `genai-plane` | genai | Project management |
| `genai-mcp-*` | genai | MCP servers (kubernetes, gitlab, n8n, datahub, plane) |
| `genai-pg-*` | genai | PostgreSQL instances (n8n, mlflow, plane, metamcp) |
| `gitlab-ce` | platform | Source control |
| `argocd` | platform | GitOps controller |
| `ingress-nginx` | ingress-nginx | Ingress controller |

Never `helm install` manually. ArgoCD manages day-2 operations.

## Namespaces

- `platform` — GitLab, ArgoCD
- `genai` — All ML/AI services
- `ingress-nginx` — Ingress controller
- `kube-system` — k3s system components

## DNS Convention

`{app}.{namespace-short}.127.0.0.1.nip.io` — resolves to localhost via nip.io.

- `argocd.mewtwo.127.0.0.1.nip.io`
- `n8n.mewtwo.127.0.0.1.nip.io`
- `mlflow.genai.127.0.0.1.nip.io`
- `agent-gateway.genai.127.0.0.1.nip.io`

Inside k8s pods, use service DNS: `genai-agent-gateway.genai.svc.cluster.local`

## Secrets

All secrets managed via `scripts/seed-secrets.sh` reading from `~/work/envs/secrets.env`.

Secrets covered: PostgreSQL passwords (n8n, mlflow, plane), n8n encryption key, MLflow flask key, MinIO credentials, LiteLLM key, GitLab PAT, Plane API token, Langfuse keys, DataHub MySQL password, n8n API key.

Use `--force` flag to recreate existing secrets.

## Agent Definitions (`agents/`)

YAML-based agent specs synced to MLflow prompt registry via `task agent-sync`.

- `mlops/` — MLOps agent (experiment tracking, model deployment)
- `developer/` — Developer assistant
- `platform-admin/` — Infrastructure management
- `_shared/` — Shared skills and tool definitions
- `envs/` — Environment bindings (k3d-mewtwo, docker-compose)

## DataHub Integration

- **Ingestion**: 3 PostgreSQL sources (n8n, mlflow, langfuse) running every 6h
- **Lineage**: 5 cross-service dataset edges via GMS REST API
- **Quality**: 5 assertions checking row counts against live PostgreSQL pods
- **Recipes**: Must be JSON (not YAML) — YAML causes "Invalid recipe json" on execution

## Sandbox (Ephemeral Code Execution)

Agent gateway creates k8s Jobs for sandboxed code execution.

- Git clone uses in-cluster GitLab: `gitlab-ce.platform.svc.cluster.local` (not nip.io)
- PAT read from `gitlab-pat` k8s secret, injected into clone URL
- Jobs run in `genai` namespace with resource limits

## Testing

```bash
cd services/agent-gateway && uv run pytest
task smoke                    # Platform-wide health checks
task benchmark-smoke          # Quick agent benchmark (1 agent, 3 cases)
task doctor                   # Preflight + smoke
```

## Specs

Feature specs at `specs/NNN-name/`. Status tracked in frontmatter.

Shipped: 001 (agent-gateway), 015 (DataOps — phases 1-3), 020-027 (various platform features).

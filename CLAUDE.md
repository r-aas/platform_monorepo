# platform_monorepo

Shared infrastructure for the k3d "mewtwo" platform. Helm charts, agent definitions, scripts, specs, and the agent-gateway service.

## Structure

```
charts/              # 35 Helm charts (ArgoCD manages all post-bootstrap)
services/
  agent-gateway/     # Slim orchestrator: skill catalog, semantic discovery, schedule→A2A glue
agents/              # Agent YAML definitions (6 agents + _shared)
skills/              # Skill definitions (21 skills)
scripts/             # Bootstrap, setup, ingestion, benchmarks, secrets, smoke tests
specs/               # Spec-driven feature designs (001-029)
taskfiles/           # Taskfile includes (agents, arch, mcp, mlops, quality, etc.)
envs/                # Environment config (global.env, secrets.env)
manifests/           # Raw k8s manifests
images/              # Custom Docker image builds (19 images incl. MCP servers)
mcp-servers/         # MCP server configs
n8n-data/
  workflows/         # 17 n8n workflow JSONs (promoted to k3d via Helm hook)
data/                # Seed data (prompts, benchmarks, training sets)
docs/                # Architecture docs, environment guide, checklists
docker-compose.yml   # Local dev fallback (not used in k3d)
pyproject.toml       # uv project config (scripts, benchmarks)
helmfile.yaml        # Bootstrap-only (seeds ArgoCD, ingress, GitLab)
Taskfile.yml         # Root task runner (symlinked to ~/work/Taskfile.yml)
RESUME.md            # Session state for /continue
BACKLOG.md           # Prioritized task queue (P0-P3)
```

## Key Commands

```bash
task up              # Full bootstrap: colima → k3d → helmfile → GitLab → images → ArgoCD → n8n → agents → smoke
task start           # Resume paused cluster (single command, ~7 min)
task stop            # Pause cluster (single command, ~21s)
task down            # Destroy cluster (PV data preserved)
task smoke           # Verify all services reachable
task status          # Full platform status
task urls            # Print all URLs + credentials

task n8n-import      # Import genai-mlops workflows into n8n
task agent-sync      # Sync agent YAMLs to MLflow prompt registry
task seed-secrets    # Create k8s secrets from ~/work/envs/secrets.env
task seed-registry   # Seed agent registry with agents + env bindings


task benchmark-smoke # Quick 1-agent, 3-case benchmark
task benchmark-agents # Full agent benchmarks with LLM-as-judge
```

## Agent Platform Architecture

The platform uses best-of-breed OSS components for each layer:

| Layer | Component | Role |
|-------|-----------|------|
| **Agent Runtime** | kagent (CNCF Sandbox) | K8s CRDs for agents, MCP servers, memory. A2A protocol. Google ADK execution |
| **MCP Proxy** | agentgateway (Linux Foundation) | Rust, multiplexes MCP servers, tool federation (243 tools), CEL policies, Gateway API |
| **Artifact Registry** | agentregistry | Agents, skills, prompts catalog. pgvector semantic search. Blueprints |
| **LLM Proxy** | LiteLLM | OpenAI-compatible, routes to Ollama, per-key access control |
| **Scheduling** | k8s CronJobs | POST to kagent A2A endpoints on cadence |
| **Orchestration** | agent-gateway (custom, slimmed) | Skill catalog, semantic tool discovery, orchestration glue |

## Agent Ecosystem

### Agents (8: 5 built-in kagent + 3 custom via Helm)

| Agent | Schedule | Role | MCP Tools |
|-------|----------|------|-----------|
| platform-admin-agent | */15m | Watchdog — k8s health, incident response | kubernetes-ops, gitlab-ops, kagent-tool-server, ollama-models |
| project-coordinator-agent | */1h | Backlog triage, sprint management, status | kubernetes-ops, plane-project, gitlab-ops |
| data-engineer-agent | */2h | Data catalog, lineage, quality, ingestion | kubernetes-ops, minio-storage, mlflow-tracking |
| mlops-agent | */4h | Experiment tracking, model lifecycle | kubernetes-ops, mlflow-tracking, langfuse-observability, minio-storage, ollama-models |
| developer-agent | */6h | Code gen, review, security, CI/CD | kubernetes-ops, gitlab-ops |
| qa-eval-agent | nightly | Benchmarks, regression detection, prompt eval | kubernetes-ops, mlflow-tracking, langfuse-observability |
| helm-agent (built-in) | reactive | Helm release management | kagent-tool-server |
| k8s-agent (built-in) | reactive | Kubernetes operations | kagent-tool-server |

### MCP Servers (9)

| Server | Wraps | Namespace | Key Tools |
|--------|-------|-----------|-----------|
| mcp-kubernetes | k8s API | platform | kubectl operations, pod logs, exec |
| mcp-gitlab | GitLab CE | platform | repos, MRs, pipelines, issues |
| mcp-n8n | n8n API | orchestration | workflow CRUD, execution, node docs |
| mcp-odd-platform | ODD Platform | data | search, lineage, quality, schema |
| mcp-plane | Plane API | project-management | issues, labels, cycles, sprints |
| mcp-mlflow | MLflow API | mlops | experiments, runs, metrics, model registry |
| mcp-langfuse | Langfuse API | observability | traces, scores, usage, cost analysis |
| mcp-minio | MinIO S3 | storage | buckets, objects, artifacts |
| mcp-ollama | Ollama API | llm | model pull/delete, VRAM, inference test |

### Skills (21)

Core: kubernetes-ops, mlflow-tracking, n8n-workflow-ops, code-generation, documentation, security-audit, benchmark-runner, data-ingestion, prompt-engineering, agent-management, skill-management, vector-store-ops, dev-sandbox

New: catalog-ops, langfuse-ops, artifact-ops, model-management, issue-triage, sprint-management, test-generation, gitlab-pipeline-ops

## Agent Gateway (`services/agent-gateway/`) — Being Slimmed

Python 3.12 + FastAPI. Being reduced to orchestration glue as kagent + agentgateway + agentregistry absorb overlapping functions:

- **Skill catalog**: Hybrid search over agent skills (unique capability, no OSS equivalent)
- **Semantic tool discovery**: pgvector embeddings over tool schemas
- **Sandbox**: Ephemeral k8s Jobs for code execution
- ~~Agent registry~~ → kagent CRDs
- ~~MCP proxy~~ → agentgateway (Rust)
- ~~A2A cards~~ → kagent A2A protocol
- ~~OpenAI chat~~ → LiteLLM

## Agentgateway (`charts/genai-agentgateway/`)

Rust-based MCP/A2A proxy from Linux Foundation. Replaces MetaMCP. Multiplexes all platform MCP servers.
- **Controller** (port 9978 gRPC): Watches CRDs, manages xDS config, auto-deploys proxy pods
- **Proxy** (port 8080 HTTP): MCP data plane — handles `initialize`, `tools/list`, `tools/call`
- AgentgatewayBackend CRs define MCP server targets (8 per-server + 1 aggregated)
- Gateway API: Gateway + HTTPRoute resources create the proxy data plane
- Per-backend routes: `/mcp/{backend}` (kubernetes, gitlab, mlflow, langfuse, minio, ollama, plane, kagent-tools, odd-platform)
- **Aggregated route: `/mcp/all`** — `mcp-all` backend with all 9 servers as targets, tools federated in one session (tool names prefixed by backend: `kubernetes_kubectl_get`, `gitlab_create_issue`, etc.)
- **CEL policies**: 4 AgentgatewayPolicy CRDs enforce tool-level RBAC at the proxy layer. Dangerous tools (exec, delete, apply, scale, model mutation) require `X-Agent-Role: admin` header. Read-only by default for external callers.
- n8n MCP Client endpoint: `http://genai-agentgateway-mcp.genai.svc.cluster.local:8080/mcp/all`
- Supports StreamableHTTP + SSE transports
- Policy engine via CEL expressions (AgentgatewayPolicy CRD)
- ARM64 native, images from `cr.agentgateway.dev`
- Requires Gateway API CRDs: `kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml`

## Agent Registry (`charts/genai-agentregistry/`)

Agent/skill/MCP server catalog with semantic search and blueprints.
- pgvector-backed (shared `genai-pgvector` instance, `agentregistry` database)
- Ports: HTTP 12121, gRPC 21212, MCP 31313
- CLI: `arctl` for scaffolding, building, publishing
- Images from `ghcr.io/agentregistry-dev/agentregistry`
- Anonymous auth enabled for k3d (JWT secret: `agentregistry-jwt`)

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

35 charts in `charts/`. All managed by ArgoCD after bootstrap. Key charts:

| Chart | Namespace | Purpose |
|-------|-----------|---------|
| `genai-agent-gateway` | genai | Agent gateway service |
| `genai-n8n` | genai | Workflow automation |
| `genai-mlflow` | genai | Experiment tracking, prompt registry |
| `genai-litellm` | genai | LLM proxy to Ollama |
| `genai-langfuse` | genai | LLM observability |
| `genai-odd-platform` | genai | Data catalog (ODD Platform) |
| `genai-minio` | genai | Object storage |
| `genai-plane` | genai | Project management |
| `genai-agentgateway` | genai | MCP/A2A proxy (agentgateway, Rust) |
| `genai-agentregistry` | genai | Agent/skill/MCP catalog + semantic search |
| `genai-agent-schedules` | genai | CronJobs → kagent A2A scheduling |
| `genai-mcp-*` | genai | MCP servers (9 total) |
| `genai-pg-*` | genai | PostgreSQL instances (n8n, mlflow, plane) |
| `gitlab-ce` | platform | Source control |
| `argocd` | platform | GitOps controller |
| `ingress-nginx` | ingress-nginx | Ingress controller |

Never `helm install` manually. ArgoCD manages day-2 operations.

## System Integration Process

New services follow the research-first process defined in `~/work/CLAUDE.md` § SYSTEM INTEGRATION PROCESS:

1. **Research** — upstream docs, community deployments, integration-specific research per connection
2. **Diagrams** — testable Mermaid diagrams in `specs/NNN-name/diagrams/` (C4 context, integration flows, sequences)
3. **Helm audit** — review every chart value, align to platform conventions (existingSecret, ARM64, resource limits)
4. **Deploy + verify** — every diagram edge becomes a smoke test assertion

Diagram and spec artifacts live in `specs/NNN-name/`.

## Namespaces

- `platform` — GitLab, ArgoCD
- `genai` — All ML/AI services
- `ingress-nginx` — Ingress controller
- `kube-system` — k3s system components

## DNS Convention

`{app}.platform.127.0.0.1.nip.io` — resolves to localhost via nip.io. All services use `platform` subdomain.

- `argocd.platform.127.0.0.1.nip.io`
- `n8n.platform.127.0.0.1.nip.io`
- `mlflow.platform.127.0.0.1.nip.io`
- `gateway.platform.127.0.0.1.nip.io`

Inside k8s pods, use service DNS: `genai-agent-gateway.genai.svc.cluster.local`

## Secrets

All secrets managed via `scripts/seed-secrets.sh` reading from `~/work/envs/secrets.env`.

Secrets covered: PostgreSQL passwords (n8n, mlflow, plane, pgvector/ODD Platform), n8n encryption key, MLflow flask key, MinIO credentials, LiteLLM key, GitLab PAT, Plane API token, Langfuse keys, n8n API key.

Use `--force` flag to recreate existing secrets.

## Agent Definitions (`agents/`)

YAML-based agent specs with autonomy blocks (schedule, signals, memory, collaborators, guardrails).

- `mlops/` — MLOps agent (experiment tracking, model deployment, observability)
- `developer/` — Developer assistant (code gen, review, security, CI/CD)
- `platform-admin/` — Infrastructure management (watchdog, incident response)
- `data-engineer/` — Data catalog, lineage, quality, ingestion
- `project-coordinator/` — Backlog triage, sprint management, status reporting
- `qa-eval/` — Benchmarks, regression detection, prompt evaluation
- `_shared/` — Shared LLM and MCP configs
- `envs/` — Environment bindings (k3d-mewtwo)

## ODD Platform (Data Catalog)

Lightweight data catalog replacing DataHub. PostgreSQL-only (shared pgvector instance), ARM64 native.

- **Chart**: `genai-odd-platform` — single container + shared PostgreSQL
- **MCP Server**: `mcp-odd-platform` — 17 tools (search, lineage, quality, schema, tags, alerts)
- **API**: REST at `http://odd.platform.127.0.0.1.nip.io/api/`
- **Health**: `/actuator/health`

## Sandbox (Ephemeral Code Execution)

Agent gateway creates k8s Jobs for sandboxed code execution.

- Git clone uses in-cluster GitLab: `gitlab-ce.platform.svc.cluster.local` (not nip.io)
- PAT read from `gitlab-pat` k8s secret, injected into clone URL
- Jobs run in `genai` namespace with resource limits

## Operational Patterns (GitOps / DevOps / AgentOps)

Full reference: `~/.claude/skills/platform-ops-patterns/SKILL.md`

**GitOps**: Git is the source of truth. All changes via Helm charts + ArgoCD. Never `helm install` or `kubectl apply` manually after bootstrap. Secrets via `existingSecret` pattern + `seed-secrets.sh`.

**DevOps**: CI pipeline = lint → test → build → deploy → verify. Quality gates: agent-lint (≤20 tools), helm lint, ruff, pytest, smoke. Images built ARM64-native, multi-stage, <500MB.

**AgentOps**: Agent lifecycle = define → lint → deploy → verify → monitor → iterate. Tool budget ≤20 per agent. Explicit `toolNames` always. Scheduling cadence matched to domain (15m monitoring → nightly benchmarks). Observability via Langfuse traces + MLflow metrics.

## Testing

```bash
cd services/agent-gateway && uv run pytest
task smoke                    # Platform-wide health checks
task benchmark-smoke          # Quick agent benchmark (1 agent, 3 cases)
task doctor                   # Preflight + smoke
```

## Specs

Feature specs at `specs/NNN-name/`. Status tracked in frontmatter.

Shipped: 001-008 (webhook auth, workflow minimize, secrets, agent tasks, integration tests, dataset eval, agent routing, streaming), 010-014 (global config, helm, gitlab, argocd, observatory), 015 (DataOps — phases 1-3), 016-020 (MCP gateway, agent executor, promotion pipeline, A2A registry, dashboard enrichment), 020-027 (platform features).
In-progress: 029 (platform consolidation — kagent + agentgateway + agentregistry integration).

## Monorepo

This repo is the single source of truth for the entire platform. The former `genai-mlops` repo was merged in — workflow JSONs, scripts, benchmarks, specs, and docs all live here now. The n8n workflow promotion Helm hook clones from this repo's `n8n-data/workflows/` path.

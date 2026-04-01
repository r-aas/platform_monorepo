<!-- status: in-progress -->
# 032 — kagent as Central AgentOps Orchestrator

Supersedes: 031 (kagent + kmcp native integration), extends 029 (platform consolidation).

## 1. Problem

The agent platform works but is fragmented across too many overlapping systems:

| Concern | Systems involved | Problem |
|---------|-----------------|---------|
| Agent definitions | Custom YAML → Python transpiler → kagent CRDs | Transpiler breaks on every kagent schema change |
| MCP servers | 9 individual Helm charts + agentgateway static dict + kagent RemoteMCPServer CRDs | Three registries, none authoritative |
| Observability | OTEL disabled in kagent, no Langfuse integration, MLflow traces disconnected | No unified view of agent behavior |
| Scheduling | CronJobs → curl → A2A | Fragile, no retry, no observability |
| Agent orchestration | agent-gateway (~5000 LOC) overlaps with kagent + agentregistry | 65% of agent-gateway is now redundant |
| Agent workflows | 5 n8n workflows duplicate what kagent agents do natively | Unnecessary middleware |
| Model management | Hardcoded per-agent, no rotation, no provider abstraction | ModelConfig CRDs solve this already |
| CI/CD | No eval gates, no feedback loop, no automated quality pipeline | Agents deploy without quality verification |

Nine independent research efforts confirmed: kagent should be the gravitational center. Everything else orbits it.

## 2. Vision

kagent owns the agent lifecycle. Other components serve specific, non-overlapping roles:

```
                            ┌─────────────┐
                            │   GitLab CI  │
                            │  (eval gate) │
                            └──────┬───────┘
                                   │ MR triggers eval
                                   ▼
┌──────────┐  CRD watch   ┌──────────────┐  A2A    ┌────────────┐
│  kmcp    │──────────────▶│   kagent     │◀────────│ CronJobs   │
│controller│  RemoteMCP    │  controller  │         │ (schedules)│
└────┬─────┘               └──────┬───────┘         └────────────┘
     │ manages                    │ manages
     ▼                            ▼
┌──────────┐               ┌──────────────┐
│MCPServer │               │ Agent CRDs   │
│  CRDs    │               │ ModelConfig  │
└────┬─────┘               │ Memory       │
     │ creates              └──────┬───────┘
     ▼                            │ references
┌──────────────┐                  ▼
│RemoteMCPServer│◀─────── Agent tool bindings
│  resources    │
└──────┬────────┘
       │ watched by
       ▼
┌──────────────┐         ┌────────────────┐
│agentgateway  │         │ agentregistry  │
│(MCP federation│         │(catalog/search)│
│ CEL policies)│         │ mirrors CRDs   │
└──────────────┘         └────────────────┘
       │                        │
       ▼                        ▼
┌──────────────┐         ┌────────────────┐
│/mcp/all      │         │semantic search │
│/mcp/{backend}│         │blueprints      │
│243 tools     │         │skill catalog   │
└──────────────┘         └────────────────┘

Observability: kagent OTEL ──▶ Langfuse (traces) + MLflow (experiments) + DataHub (lineage)
LLM routing:   ModelConfig CRDs ──▶ LiteLLM ──▶ Ollama
```

## 3. Architecture — Target State

### Component Responsibilities

```
kagent controller
├── Agent CRDs (6 custom + 2 built-in)
├── ModelConfig CRDs (chat, embedding, summarization)
├── Memory service (pgvector, TTL, semantic search)
├── A2A protocol endpoints
└── OTEL instrumentation → collector

kmcp controller
├── MCPServer CRDs (9 servers)
├── Deployment + Service lifecycle
└── RemoteMCPServer auto-creation → tool discovery

agentgateway (Rust)
├── MCP federation (/mcp/all, /mcp/{backend})
├── CEL policy engine
├── Watches RemoteMCPServer CRDs (dynamic, no static config)
└── A2A request routing

agentregistry
├── Catalog: mirrors kagent Agent CRDs
├── Semantic search over agents + skills + tools
├── Blueprints for agent scaffolding
└── CLI (arctl) for dev workflow

agent-gateway (custom, slimmed to ~500 LOC)
├── Sandbox runtime (ephemeral k8s Jobs)
├── Warm pod pool management
├── Health aggregation endpoint
└── CronJob scheduling coordination

n8n (automation only)
├── 9 API pass-through workflows
├── 3 data pipelines (gitlab-to-plane, plane-to-gitlab, yt-pipeline)
└── NOT: chat, a2a-server, agent-eval, claude-autonomous, prompt-resolve

LiteLLM
├── Model routing (Ollama, future: cloud providers)
├── Per-key access control
└── Request/response logging
```

## 4. Component Ownership Matrix

| Capability | Owner (target) | Current owner | Action |
|-----------|---------------|---------------|--------|
| Agent definition | kagent CRDs | Custom YAML + transpiler | Direct CRD authoring |
| Agent runtime | kagent Python ADK | n8n chat workflow | Replace 5 workflows |
| Agent scheduling | CronJobs → A2A | CronJobs → curl | Keep pattern, delete transpiler |
| MCP server lifecycle | kmcp MCPServer CRDs | 9 individual Helm charts | Migrate to CRDs |
| MCP tool discovery | RemoteMCPServer auto | Manual registration | Automatic via kmcp |
| MCP federation | agentgateway | agentgateway | Watch CRDs instead of static config |
| Tool policy/RBAC | agentgateway CEL | None | New capability |
| Agent catalog | agentregistry | agent-gateway PostgreSQL | Mirror from kagent CRDs |
| Skill catalog | agentregistry | agent-gateway | Migrate |
| Semantic search | agentregistry pgvector | agent-gateway pgvector | Migrate |
| Sandbox execution | agent-gateway (slim) | agent-gateway | Keep, extract as library |
| Model routing | LiteLLM + ModelConfig | LiteLLM + hardcoded env | ModelConfig CRDs |
| Agent memory | kagent memory service | None (stateless agents) | New capability |
| Trace collection | kagent OTEL → Langfuse | Langfuse direct (partial) | Enable OTEL pipeline |
| Experiment tracking | MLflow | MLflow | Add kagent integration |
| Data lineage | DataHub | DataHub | Add agent lineage edges |
| CI eval gates | GitLab CI | None | New capability |
| Benchmarking | kagent agents + MLflow | Scripts + agent-gateway | Migrate eval harness |

## 5. Integration Design

### 5a. MCP Servers: MCPServer CRDs → RemoteMCPServer → agentgateway

**Current**: 9 Helm charts (45+ files) + `mcp-backends.yaml` static dict in agentgateway.

**Target**: 9 MCPServer CRDs managed by kmcp. agentgateway watches RemoteMCPServer resources dynamically.

```
MCPServer CRD (kmcp)
  → kmcp creates: Deployment + Service + RemoteMCPServer
    → agentgateway controller watches RemoteMCPServer
      → auto-configures MCP proxy routes
        → /mcp/{name} and /mcp/all available
```

| Server | Image | Port | Transport |
|--------|-------|------|-----------|
| mcp-kubernetes | ghcr.io/r-aas/mcp-kubernetes | 3000 | StreamableHTTP |
| mcp-gitlab | ghcr.io/r-aas/mcp-gitlab | 3001 | StreamableHTTP |
| mcp-n8n | ghcr.io/r-aas/mcp-n8n | 3002 | StreamableHTTP |
| mcp-datahub | ghcr.io/r-aas/mcp-datahub | 3003 | StreamableHTTP |
| mcp-plane | ghcr.io/r-aas/mcp-plane | 3004 | StreamableHTTP |
| mcp-mlflow | ghcr.io/r-aas/mcp-mlflow | 3005 | StreamableHTTP |
| mcp-langfuse | ghcr.io/r-aas/mcp-langfuse | 3006 | StreamableHTTP |
| mcp-minio | ghcr.io/r-aas/mcp-minio | 3007 | StreamableHTTP |
| mcp-ollama | ghcr.io/r-aas/mcp-ollama | 3008 | StreamableHTTP |

**Key change**: agentgateway must be configured to watch `RemoteMCPServer` CRDs from the `kagent.dev` API group instead of reading a static backend list. This eliminates `mcp-backends.yaml` entirely. When a new MCPServer CRD is created, agentgateway auto-discovers it within seconds.

### 5b. Agent Definitions: Direct kagent CRDs

**Current**: `agents/*/agent.yaml` (custom format) → `scripts/agentspec-to-kagent.py` → kagent CRDs.

**Target**: Write Agent CRDs directly. No transpiler. Custom agent spec format is deleted.

Each agent needs:
- `Agent` CRD with systemMessage, toolNames (required, explicit), memory config
- Reference to shared `ModelConfig` (litellm-config for chat, embedding-config for memory)
- `a2aConfig.skills` for A2A discovery
- Tool references via `RemoteMCPServer` names (auto-created by kmcp)

**6 custom agents** (platform-admin, project-coordinator, data-engineer, mlops, developer, qa-eval) + **2 built-in** (helm-agent, k8s-agent from kagent).

**Critical**: kagent v0.8.0 requires explicit `toolNames` in McpServer tool refs or pods crash with `ValidationError`. Every agent CRD must enumerate its tools.

### 5c. Observability: OTEL → Langfuse + MLflow + DataHub

kagent ships with full OTEL instrumentation (OpenAI, Anthropic, httpx, FastAPI) but it is **disabled** in current `values.yaml`.

**5-phase enablement:**

| Phase | What | How |
|-------|------|-----|
| 1 | Enable OTEL tracing | Set `otel.enabled: true`, configure collector endpoint |
| 2 | Route to Langfuse | OTEL collector → Langfuse OTEL ingestion endpoint |
| 3 | MLflow experiment integration | Agent runs create MLflow experiments, log metrics |
| 4 | DataHub lineage | Emit lineage: Agent → MCP Server → Backend Service |
| 5 | Memory observability | Trace memory reads/writes, semantic search queries |

**Langfuse integration path**: Langfuse supports OTEL trace ingestion natively. kagent OTEL traces route through an OTEL collector sidecar or cluster-level collector to Langfuse's `/api/public/otel/v1/traces` endpoint.

**MLflow integration**: Agent eval runs (qa-eval nightly, CI gate evals) log to MLflow experiments. Baselines stored as MLflow registered models. Regression = score below baseline threshold.

### 5d. Model Management: ModelConfig CRDs → LiteLLM → Ollama

**Current**: Each agent has hardcoded model references in env vars.

**Target**: Centralized ModelConfig CRDs with credential rotation.

```yaml
# Shared chat model
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: litellm-config
  namespace: genai
spec:
  provider: OpenAI
  model: qwen3:14b
  openAI:
    baseUrl: http://genai-litellm.genai.svc.cluster.local:4000/v1
  apiKeySecret: kagent-litellm
  apiKeySecretKey: api-key

# Shared embedding model
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: embedding-config
  namespace: genai
spec:
  provider: OpenAI
  model: nomic-embed-text
  openAI:
    baseUrl: http://genai-litellm.genai.svc.cluster.local:4000/v1
  apiKeySecret: kagent-litellm
  apiKeySecretKey: api-key
```

**Credential rotation**: kagent hashes the referenced secret. When the secret changes, kagent detects the hash mismatch and restarts affected agent pods. No manual rollout needed.

**Provider abstraction**: Agents reference ModelConfig by name, not provider details. Swapping from Ollama to Anthropic = change ModelConfig spec, agents restart automatically.

### 5e. Scheduling: CronJobs → A2A

**Current pattern (keep)**: CronJobs POST to kagent A2A endpoints.

kagent v0.8.0 has no native schedule field in the Agent CRD. The CronJob → A2A pattern works and is observable. Keep it.

| Agent | Schedule | CronJob action |
|-------|----------|---------------|
| platform-admin | */15m | POST /a2a/genai/platform-admin-agent |
| project-coordinator | */1h | POST /a2a/genai/project-coordinator-agent |
| data-engineer | */2h | POST /a2a/genai/data-engineer-agent |
| mlops | */4h | POST /a2a/genai/mlops-agent |
| developer | */6h | POST /a2a/genai/developer-agent |
| qa-eval | 0 2 * * * | POST /a2a/genai/qa-eval-agent |

**What changes**: Delete the transpiler that generates CronJob manifests from custom YAML. CronJobs are authored directly in `charts/genai-agent-schedules/templates/`.

**Future**: When kagent adds native scheduling, migrate CronJobs to Agent CRD `.spec.schedule`. Track kagent issue tracker for this feature.

### 5f. n8n Integration: Keep Automation, Replace Agent Workflows

**5 workflows replaced by kagent agents:**

| Workflow | Nodes | Replacement |
|----------|-------|-------------|
| chat-v1.json | 17 | 1 Agent CRD (biggest win) |
| a2a-server-v1.json | 12 | kagent native A2A |
| agent-eval-v1.json | 9 | qa-eval Agent CRD + MLflow |
| claude-autonomous.json | 8 | developer Agent CRD |
| prompt-resolve-v1.json | 6 | Agent CRD with prompt tools |

**12 workflows kept in n8n:**

| Category | Workflows | Reason |
|----------|-----------|--------|
| API pass-through | sessions-v1, chat-history, metrics, health, model-list, embeddings, diff, promote, mcp-proxy | Thin HTTP adapters, not agent logic |
| Data pipelines | gitlab-to-plane, plane-to-gitlab, yt-pipeline | ETL/sync, not agent tasks |

### 5g. Registry/Catalog: agentregistry Mirrors kagent CRDs

**Three-way overlap resolved:**

| System | Role (target) |
|--------|---------------|
| kagent CRDs | Source of truth for agent definitions |
| agentregistry | Catalog/search layer (semantic search, blueprints, CLI scaffolding) |
| agent-gateway | Thin orchestration only (sandbox, health, scheduling glue) |

agentregistry syncs from kagent CRDs via a controller or periodic reconciliation. It does NOT own agent definitions — it indexes them for discovery.

**Deleted from agent-gateway**: agent table, skill table, mcp_server table, all CRUD endpoints for these. The ~5000 LOC shrinks to ~500 LOC.

## 6. GitLab AgentOps Pipeline

### CI Stages

```
MR opened
  │
  ▼
┌─────────┐   ┌──────────┐   ┌────────────────┐   ┌───────────────┐
│  lint    │──▶│ validate │──▶│ eval-candidate │──▶│ deploy-staging│
│(yamllint,│   │(CRD dry- │   │(benchmark vs   │   │(ArgoCD sync   │
│ kubeval) │   │ run, helm│   │ MLflow baseline)│   │ to stage ns)  │
└─────────┘   │ template)│   └────────────────┘   └───────┬───────┘
              └──────────┘                                 │
                                                           ▼
┌────────────┐   ┌─────────────┐   ┌──────────────────┐   │
│  feedback  │◀──│ post-deploy │◀──│ deploy-prod      │◀──┤
│(Langfuse   │   │ eval        │   │(ArgoCD sync to   │   │
│ scores →   │   │(smoke +     │   │ prod ns, canary) │   │
│ GitLab     │   │ regression  │   └──────────────────┘   │
│ issues)    │   │ check)      │                          │
└────────────┘   └─────────────┘   ┌──────────────────┐   │
                                   │integration-test  │◀──┘
                                   │(A2A invoke, MCP  │
                                   │ tool call, OTEL  │
                                   │ trace present)   │
                                   └──────────────────┘
```

### Eval Infrastructure

| Component | Role |
|-----------|------|
| 22 benchmark datasets | 6 agents, stored in `data/benchmarks/` |
| eval-triad.py | Correctness + helpfulness + safety scoring |
| benchmark.py | Per-agent benchmark runner |
| agent-benchmark.py | Cross-agent comparison |
| qa-eval agent | Nightly scheduled regression detection |
| MLflow | Baseline storage, metric tracking, experiment comparison |
| Langfuse | Trace scoring, session analysis, cost tracking |

### Feedback Loop

```
Langfuse trace scores below threshold
  → GitLab issue created (via CI script or qa-eval agent)
    → Developer iterates on agent CRD / prompt / tools
      → MR opened → CI eval gate → merge if passing
```

## 7. Agent Promotion Pipeline: dev → staging → production

Every agent flows through three environments with enforced quality gates. No agent reaches production without passing all gates. No exceptions.

### Environment Model

```
┌──────────────┐    gate 1     ┌──────────────┐    gate 2     ┌──────────────┐
│   dev        │──────────────▶│   staging    │──────────────▶│  production  │
│  (genai-dev) │  lint+eval    │ (genai-stage)│  soak+smoke   │   (genai)    │
│              │  CRD validate │              │  regression   │              │
│  feature     │  benchmark    │  integration │  canary       │  full traffic│
│  branches    │  pass ≥ 85%   │  tests       │  pass ≥ 90%   │  scheduled   │
└──────────────┘               └──────────────┘               └──────────────┘
```

### Namespace Layout

| Namespace | Purpose | kagent controller | MCP servers | Model |
|-----------|---------|-------------------|-------------|-------|
| `genai-dev` | Feature development, fast iteration | Watches `genai-dev` | Shared (genai MCP services) | glm-4.7-flash |
| `genai-stage` | Integration testing, soak testing | Watches `genai-stage` | Shared (genai MCP services) | glm-4.7-flash |
| `genai` | Production workloads, scheduled agents | Watches `genai` | Owned (genai MCP services) | glm-4.7-flash |

kagent's `watchNamespaces` config already supports multi-namespace watching. A single kagent controller instance watches all three namespaces.

### Git Branch Model

```
feature/agent-name     →  genai-dev     (auto-deploy on push)
main                   →  genai-stage   (auto-deploy on merge)
release/v*             →  genai         (manual promote or auto after soak)
```

ArgoCD ApplicationSets deploy Agent CRDs to the correct namespace based on branch:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: agent-environments
spec:
  generators:
    - git:
        repoURL: http://gitlab-ce.platform.svc.cluster.local/root/platform_monorepo.git
        revision: HEAD
        directories:
          - path: charts/genai-kagent
  template:
    metadata:
      name: 'kagent-{{branch}}'
    spec:
      destination:
        namespace: '{{namespace}}'  # mapped by branch
```

### Gate 1: dev → staging (MR merge to main)

**Trigger**: MR from feature branch to main.
**Enforced by**: GitLab CI required pipeline + MR approval.
**Cannot be bypassed**: Pipeline must pass for merge button to appear.

| Check | Tool | Threshold | Blocking |
|-------|------|-----------|----------|
| Agent CRD schema valid | kubeval + dry-run apply | Valid YAML, no unknown fields | **Yes** |
| Helm template renders | `helm template` | No render errors | **Yes** |
| System prompt quality | Custom lint (length > 100 chars, no TODO, tools referenced exist) | All checks pass | **Yes** |
| MCP tool references valid | Cross-ref Agent toolNames against RemoteMCPServer CRDs | All tools resolvable | **Yes** |
| Benchmark vs baseline | eval-triad.py against MLflow baseline | pass_rate ≥ 85% | **Yes** |
| Benchmark regression | Delta vs main branch baseline | No metric drops > 5% | **Yes** |
| Secret detection | gitleaks | No secrets in diff | **Yes** |
| Python lint (if gateway changes) | ruff check + format | Clean | **Yes** |
| Dockerfile lint | hadolint | No critical issues | No (warning) |

**How it works in GitLab CI**:

```yaml
# .gitlab-ci.yml — Gate 1 jobs run on MR events
agent-lint:
  stage: lint
  rules:
    - if: $CI_MERGE_REQUEST_ID
      changes: [agents/**/*]
  script:
    - kubeval charts/genai-kagent/templates/agents.yaml
    - python3 scripts/agent-lint.py --strict

agent-eval-gate:
  stage: quality-gate
  rules:
    - if: $CI_MERGE_REQUEST_ID
      changes: [agents/**/*]
  script:
    - python3 scripts/eval-triad.py --baseline-source mlflow --fail-on-regression 0.05
  allow_failure: false  # BLOCKING — MR cannot merge if this fails
```

### Gate 2: staging → production (release promotion)

**Trigger**: Tag `release/v*` or manual promotion via `task agents:promote`.
**Enforced by**: GitLab CI + soak period + smoke tests.
**Cannot be bypassed**: Release pipeline must pass.

| Check | Tool | Threshold | Blocking |
|-------|------|-----------|----------|
| All Gate 1 checks passed | GitLab CI pipeline status | Green | **Yes** |
| Staging soak period | Time-based (agent ran ≥ 2 scheduled cycles) | Completed without error | **Yes** |
| Integration test | A2A invoke each agent in staging | All 8 agents respond | **Yes** |
| MCP tool call | Each agent calls at least 1 tool successfully | Tools return valid responses | **Yes** |
| OTEL traces present | Query Langfuse for staging traces | Traces exist for each agent | **Yes** |
| Benchmark vs staging baseline | eval-triad.py on staging data | pass_rate ≥ 90% (stricter) | **Yes** |
| No error spike | Query Langfuse error rate for staging period | Error rate < 5% | **Yes** |
| Memory service operational | Agent can store + retrieve memory | Read/write succeeds | No (warning) |

**Soak period enforcement**:

```yaml
# GitLab CI — Gate 2 waits for soak period
staging-soak-check:
  stage: pre-promote
  script:
    - |
      # Check each agent has completed at least 2 scheduled runs in staging
      for agent in platform-admin project-coordinator data-engineer mlops developer qa-eval; do
        RUNS=$(kubectl get pods -n genai-stage -l agent=$agent --field-selector=status.phase=Succeeded --no-headers | wc -l)
        if [ "$RUNS" -lt 2 ]; then
          echo "FAIL: $agent has only $RUNS completed runs in staging (need ≥ 2)"
          exit 1
        fi
      done
      echo "✓ All agents completed soak period"
```

### Post-Production Monitoring (Continuous Gate)

After deployment to production, quality is continuously enforced:

| Check | Cadence | Tool | Action on failure |
|-------|---------|------|-------------------|
| Nightly full benchmark | Daily 2 AM | qa-eval agent + eval-triad.py | GitLab issue + Langfuse alert |
| Langfuse score monitoring | Every agent run | Langfuse scoring | Auto-create issue if avg score < 80% |
| Error rate monitoring | Continuous | Langfuse error traces | Alert if error rate > 10% in 1h window |
| Memory health | Daily | kagent memory service health | Warning issue |
| MCP tool availability | */5m | agentgateway /health | PagerDuty if any server unhealthy > 15m |

**Automated rollback**: If production pass_rate drops below 70% (critical threshold = 0.7 × 90% gate), the feedback stage auto-creates a revert MR in GitLab:

```
Production score drops below 63% (critical)
  → GitLab CI feedback stage creates revert MR
    → Revert MR auto-merges (if configured) or awaits approval
      → ArgoCD syncs previous Agent CRD version
        → Agent reverts to last known-good state
```

### Promotion Commands

```bash
# Develop: push to feature branch → auto-deploys to genai-dev
git push origin feature/improve-platform-admin

# Promote to staging: merge MR (Gate 1 must pass)
# GitLab MR merge button blocked until pipeline green

# Promote to production: tag release
task agents:promote          # Creates release tag, triggers Gate 2

# Emergency rollback
task agents:rollback         # Reverts to previous release tag
task agents:rollback -- v0.1.2  # Reverts to specific version
```

### Agent Version Tracking

Each agent CRD carries version metadata:

```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: platform-admin-agent
  namespace: genai
  labels:
    app.kubernetes.io/version: "0.2.0"
    agentops.dev/promoted-from: "genai-stage"
    agentops.dev/promoted-at: "2026-03-31T14:00:00Z"
    agentops.dev/gate1-pipeline: "12345"
    agentops.dev/gate2-pipeline: "12346"
    agentops.dev/baseline-score: "0.92"
  annotations:
    agentops.dev/changelog: "Improved incident detection prompt, added kubectl_top tool"
```

Labels enable:
- `kubectl get agents -l app.kubernetes.io/version=0.2.0` — find agents at specific version
- `kubectl get agents -l agentops.dev/promoted-from=genai-stage` — audit trail
- Rollback to any labeled version via `kubectl apply` of previous CRD

## 8. Deletion Plan

### Files to Delete

| Path | Reason |
|------|--------|
| `scripts/agentspec-to-kagent.py` | Transpiler replaced by direct CRD authoring |
| `agents/_shared/` | Config moves to ModelConfig CRDs |
| `agents/envs/` | Environment bindings move to Helm values |
| `charts/genai-mcp-kubernetes/` | Replaced by MCPServer CRD |
| `charts/genai-mcp-gitlab/` | Replaced by MCPServer CRD |
| `charts/genai-mcp-n8n/` | Replaced by MCPServer CRD |
| `charts/genai-mcp-datahub/` | Replaced by MCPServer CRD |
| `charts/genai-mcp-plane/` | Replaced by MCPServer CRD |
| `charts/genai-mcp-mlflow/` | Replaced by MCPServer CRD |
| `charts/genai-mcp-langfuse/` | Replaced by MCPServer CRD |
| `charts/genai-mcp-minio/` | Replaced by MCPServer CRD |
| `charts/genai-mcp-ollama/` | Replaced by MCPServer CRD |
| `mcp-servers/mcp-backends.yaml` | agentgateway watches CRDs dynamically |
| `n8n-data/workflows/chat-v1.json` | Replaced by Agent CRD |
| `n8n-data/workflows/a2a-server-v1.json` | Replaced by kagent A2A |
| `n8n-data/workflows/agent-eval-v1.json` | Replaced by qa-eval Agent CRD |
| `n8n-data/workflows/claude-autonomous.json` | Replaced by developer Agent CRD |
| `n8n-data/workflows/prompt-resolve-v1.json` | Replaced by Agent CRD |

### Code to Delete from agent-gateway

| Module | LOC (approx) | Reason |
|--------|-------------|--------|
| Agent CRUD endpoints | ~800 | kagent CRDs + agentregistry |
| Skill CRUD endpoints | ~600 | agentregistry |
| MCP server registry | ~400 | kmcp + agentgateway |
| A2A card serving | ~300 | kagent A2A protocol |
| OpenAI chat proxy | ~500 | LiteLLM |
| Benchmark harness | ~400 | MLflow + qa-eval agent |
| Agent spec parser | ~300 | No custom spec format |
| **Total deleted** | **~3300** | |
| **Remaining** | **~500** | Sandbox, warm pool, health agg, CronJob glue |

### Database Tables to Drop (agent-gateway PostgreSQL)

| Table | Replacement |
|-------|-------------|
| agents | kagent CRDs |
| skills | agentregistry |
| mcp_servers | kmcp MCPServer CRDs |
| agent_skills | kagent Agent CRD toolNames |
| agent_mcp_bindings | kagent Agent CRD tool refs |
| benchmarks | MLflow experiments |

## 9. Migration Phases

### Phase 1: Foundation (Week 1-2)

**Goal**: kagent OTEL enabled, ModelConfig CRDs deployed, kmcp controller installed.

| Deliverable | Verification |
|-------------|-------------|
| Enable `otel.enabled: true` in kagent Helm values | `kubectl logs` shows OTEL spans emitted |
| Deploy OTEL collector (sidecar or cluster) | Collector `/healthz` returns 200 |
| Route OTEL → Langfuse | Traces visible in Langfuse UI |
| Create ModelConfig CRDs (litellm-config, embedding-config) | `kubectl get modelconfigs -n genai` shows 2 configs |
| Install kmcp controller | `kubectl get crd mcpservers.kmcp.io` exists |
| Create `kagent-litellm` secret | Secret exists in genai namespace |

### Phase 2: MCP Migration (Week 2-3)

**Goal**: All 9 MCP servers managed by MCPServer CRDs. Old charts deleted.

| Deliverable | Verification |
|-------------|-------------|
| Write 9 MCPServer CRDs | `kubectl get mcpservers -n genai` shows 9, all Ready |
| RemoteMCPServer auto-created | `kubectl get remotemcpservers -n genai` shows 9 |
| Configure agentgateway to watch CRDs | `/mcp/all` returns 243 tools (same as before) |
| Delete `mcp-backends.yaml` | File absent, agentgateway still serves tools |
| Delete 9 `charts/genai-mcp-*` dirs | Dirs absent, ArgoCD healthy |
| Smoke test all MCP endpoints | `task smoke` passes MCP section |

### Phase 3: Agent Migration (Week 3-4)

**Goal**: All agents defined as direct kagent CRDs. Transpiler deleted.

| Deliverable | Verification |
|-------------|-------------|
| Rewrite 6 agent CRDs in kagent v1alpha2 | `kubectl get agents.kagent.dev -n genai` shows 8 (6 custom + 2 built-in) |
| Each agent references ModelConfig by name | Agent pods start without LLM errors |
| Each agent has explicit toolNames | No ValidationError in agent pod logs |
| Agent memory configured (pgvector + TTL) | Memory read/write succeeds via A2A |
| Delete transpiler script | `scripts/agentspec-to-kagent.py` absent |
| Delete `agents/_shared/` and `agents/envs/` | Dirs absent |
| CronJobs POST to kagent A2A | Scheduled tasks fire on cadence |
| Delete 5 n8n workflows | Workflows absent from n8n UI |

### Phase 4: Agent-Gateway Slim + Registry (Week 4-5)

**Goal**: agent-gateway reduced to ~500 LOC. agentregistry mirrors kagent CRDs.

| Deliverable | Verification |
|-------------|-------------|
| Delete agent/skill/MCP CRUD from agent-gateway | Endpoints return 404 |
| Delete benchmark harness from agent-gateway | Eval runs use MLflow + qa-eval agent |
| Delete OpenAI chat proxy | `/v1/chat/completions` routes to LiteLLM |
| agent-gateway retains: sandbox, warm pool, health | `/health/detail` returns all components |
| agentregistry indexes kagent CRDs | `arctl search agent "kubernetes"` returns results |
| agentregistry indexes skills | Semantic search over 21 skills works |
| Drop obsolete DB tables | Tables absent from agent-gateway PostgreSQL |

### Phase 5: GitLab CI Pipeline + Feedback Loop (Week 5-6)

**Goal**: Full CI/CD lifecycle with eval gates and automated feedback.

| Deliverable | Verification |
|-------------|-------------|
| `.gitlab-ci.yml` with 8 stages | Pipeline runs on MR to agents/ path |
| lint stage (yamllint, kubeval) | Catches malformed CRDs |
| validate stage (dry-run, helm template) | Catches schema errors |
| eval-candidate stage (benchmark vs baseline) | Blocks MR if score regresses |
| deploy-staging (ArgoCD sync to stage) | Agent running in stage namespace |
| integration-test (A2A invoke + MCP tool call) | End-to-end agent invocation succeeds |
| deploy-prod (ArgoCD sync, canary optional) | Agent running in prod namespace |
| post-deploy-eval (smoke + regression) | Langfuse traces show healthy scores |
| feedback (scores → GitLab issues) | Issue auto-created on regression |

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| kmcp controller not ARM64 | Medium | High | Check image manifest before install. Fall back to manual Deployment management if needed |
| agentgateway CRD-watch not supported | Low | High | Current version supports Gateway API. If CRD watch fails, keep static config as fallback |
| kagent OTEL → Langfuse format mismatch | Medium | Medium | OTEL collector can transform spans. Langfuse OTEL endpoint is GA |
| Agent memory migration (stateless → pgvector) | Low | Medium | kagent memory service is independent. No existing state to migrate |
| n8n workflow deletion breaks dependents | Medium | Medium | Audit all n8n webhook callers before deleting. Keep API pass-throughs |
| agent-gateway slim misses a capability | Medium | Low | Keep agent-gateway running alongside. Delete code incrementally, verify after each removal |
| GitLab CI eval gate too slow (LLM inference) | High | Medium | Use smallest viable model for eval. Cache baselines. Timeout at 5 min per agent |
| 22 benchmark datasets stale | Medium | Medium | qa-eval nightly job detects drift. Manual review quarterly |
| CronJob → A2A auth | Low | Medium | kagent A2A endpoints in-cluster, no auth needed. Add network policy if needed |
| Three-way registry sync (kagent → agentregistry) | Medium | Medium | Start with periodic sync (CronJob). Move to controller-based watch if latency matters |

## 11. Verification

### Per-Phase Smoke Tests

```bash
# Phase 1: Foundation
kubectl get modelconfigs -n genai -o name | wc -l  # expect 2
kubectl get crd mcpservers.kmcp.io                   # exists
curl -s langfuse.platform.127.0.0.1.nip.io/api/public/traces | jq '.data | length'  # > 0

# Phase 2: MCP Migration
kubectl get mcpservers -n genai -o jsonpath='{range .items[*]}{.metadata.name}: {.status.conditions[-1].type}={.status.conditions[-1].status}{"\n"}{end}'
# All should show Ready=True
curl -s gateway.platform.127.0.0.1.nip.io/mcp/all -X POST \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq '.result.tools | length'
# expect 243

# Phase 3: Agent Migration
kubectl get agents.kagent.dev -n genai -o name | wc -l  # expect 8
kubectl logs -l app=platform-admin-agent -n genai --tail=5  # no ValidationError
curl -s -X POST gateway.platform.127.0.0.1.nip.io/api/a2a/genai/platform-admin-agent \
  -H 'Content-Type: application/json' \
  -d '{"message":{"role":"user","parts":[{"text":"health check"}]}}' | jq .status
# expect "completed"

# Phase 4: Agent-Gateway Slim
curl -s gateway.platform.127.0.0.1.nip.io/health/detail | jq .
# sandbox: ok, warm_pool: ok, no agent_registry key
curl -s gateway.platform.127.0.0.1.nip.io/api/agents  # expect 404

# Phase 5: CI Pipeline
# Trigger: push a change to agents/platform-admin/agent.yaml on a branch
# Verify: GitLab pipeline runs 8 stages, all green
# Verify: Langfuse shows eval traces from CI
# Verify: MLflow shows new experiment run with scores
```

### Regression Checklist

After full migration, these must all still work:

| Check | Command | Expected |
|-------|---------|----------|
| MCP federation | `curl /mcp/all tools/list` | 243 tools |
| Agent A2A | `curl /api/a2a/genai/{agent}` | 200 for all 8 agents |
| Scheduled runs | `kubectl get cronjobs -n genai` | 6 CronJobs, last run < expected interval |
| Langfuse traces | Langfuse UI → Traces | Agent invocations visible with spans |
| MLflow experiments | MLflow UI → Experiments | Agent eval experiments with metrics |
| Semantic search | `arctl search agent "kubernetes"` | Returns platform-admin, k8s-agent |
| Sandbox execution | POST /api/sandbox with code payload | Job completes, output returned |
| n8n remaining workflows | `curl n8n.platform.../api/v1/workflows` | 12 active workflows |
| DataHub lineage | DataHub UI → Lineage | Agent → MCP → Backend edges visible |
| Health endpoint | `curl /health/detail` | All components green |

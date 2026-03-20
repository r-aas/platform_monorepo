# The Factory

A self-optimizing system that continuously builds agentic capabilities for R's platform. Each scheduled run reads state, picks work, executes, and updates — compounding capability over time.

## The Stack

```
┌─────────────────────────────────────────────────────┐
│  R (Claude Code)                                     │
│  "The shell" — issues commands, steers the factory   │
├─────────────────────────────────────────────────────┤
│  Agent Gateway                                       │
│  "The kernel" — routes, composes, invokes            │
│  POST /v1/chat/completions → agent:{name}            │
├─────────────────────────────────────────────────────┤
│  Agents                                              │
│  "Processes" — compositions of skills + runtime      │
│  agents/*.yaml → MLflow prompt registry              │
├─────────────────────────────────────────────────────┤
│  Skills                                              │
│  "Libraries" — reusable tasks + MCP refs + prompts   │
│  skills/*.yaml → MLflow model registry               │
├─────────────────────────────────────────────────────┤
│  MCP Servers                                         │
│  "I/O devices" — tool surfaces via MetaMCP           │
│  namespaces: genai, platform, data, ops              │
├─────────────────────────────────────────────────────┤
│  Runtimes                                            │
│  "Execution engines" — n8n, python, claude-code      │
│  Same AgentRunConfig → any runtime                   │
├─────────────────────────────────────────────────────┤
│  Intelligence                                        │
│  "The brain" — RAG, embeddings, eval, benchmarks     │
│  Ollama + MLflow experiments + vector search          │
└─────────────────────────────────────────────────────┘
```

## Domain Taxonomy

The factory organizes work by domain → subdomain. Each subdomain produces skills, agents, and/or MCP configs.

### D1: Platform Core
Infrastructure that everything else runs on.

| Subdomain | Produces | Status |
|-----------|----------|--------|
| k3d-cluster | Skills: cluster-ops | Exists (k8s-troubleshooting skill) |
| networking | Skills: ingress-management | Partial (private-homelab-ops) |
| ci-cd | Skills: gitlab-pipeline-ops | Exists (platform-gitlab-ci skill) |
| argocd | Skills: gitops-management | Exists (platform-argocd skill) |
| helm | Skills: chart-authoring | Exists (platform-helm-authoring) |
| storage | Skills: pv-management | Not started |

### D2: Agent Runtime
The gateway and everything it orchestrates.

| Subdomain | Produces | Status |
|-----------|----------|--------|
| gateway-core | Agent Gateway service | MVP done (spec 001) |
| agent-definitions | Agent YAMLs | 2 agents (mlops, agent-ops) |
| skill-library | Skill YAMLs + registry | 6 skills defined |
| runtimes | n8n, python, claude-code | n8n done, others TODO |
| composition | Composer + prompt merging | Done |
| search | Hybrid RAG (keyword + embeddings) | Keyword done, embeddings TODO |

### D3: MCP Mesh
The tool surface layer that agents use.

| Subdomain | Produces | Status |
|-----------|----------|--------|
| metamcp-admin | MCP: namespace management | MCP server exists |
| genai-namespace | MCP tools: n8n, mlflow, k8s | Configured |
| platform-namespace | MCP tools: gitlab, argocd | Configured |
| gateway-mcp | MCP: gateway API as tools | Not started (T045) |
| tool-discovery | Search + auto-registration | Keyword search done |

### D4: Intelligence
RAG, evaluation, and continuous improvement.

| Subdomain | Produces | Status |
|-----------|----------|--------|
| embeddings | Vector search via Ollama | TODO in all search endpoints |
| eval-framework | Benchmark runner + datasets | Datasets exist, runner TODO |
| mlflow-tracking | Experiment tracking | Connected |
| prompt-optimization | Auto-improve system prompts | Not started |

### D5: Orchestration
Multi-agent workflows and pipeline composition.

| Subdomain | Produces | Status |
|-----------|----------|--------|
| workflow-gitops | Export/import n8n workflows | Not started (Phase 6) |
| agent-chains | Agent-to-agent delegation | Not started |
| multi-agent | Parallel agent coordination | Not started |
| n8n-workflows | Workflow templates | Exists (genai-mlops) |

### D6: Observability
Monitoring and tracing for the entire stack.

| Subdomain | Produces | Status |
|-----------|----------|--------|
| agent-tracing | MLflow traces per invocation | Endpoint exists, logging TODO |
| dashboard | Topology + metrics UI | Observatory exists, needs rework |
| alerting | Failure detection | Not started |

## How Domains Compose

```
R types: "deploy model X to staging"
  → Claude Code resolves agent: mlops
  → Gateway composes: mlops agent + kubernetes-ops skill + mlflow-tracking skill
  → Effective config: system_prompt + skill fragments + MCP servers (k8s + mlflow)
  → Runtime (n8n) executes: calls MCP tools, tracks in MLflow
  → R sees: streaming response + MLflow experiment link

R types: "create a new data-ingestion agent with S3 and postgres skills"
  → Claude Code resolves agent: agent-ops
  → Gateway composes: agent-ops + agent-management skill + skill-management skill
  → agent-ops creates: agents/data-ingestion.yaml + skills/s3-ops.yaml + skills/postgres-ops.yaml
  → Gateway syncs new definitions to MLflow
  → New agent immediately invocable
```

## Evolution Rules

1. **Missing capability → new skill**. If a task requires tools the system doesn't have, create a skill YAML.
2. **Repeated pattern → new agent**. If R keeps composing the same skills manually, define an agent.
3. **External tool needed → new MCP server**. If a skill needs tools not in any namespace, register in MetaMCP.
4. **Skill underperforms → evolve**. If benchmark pass rate drops, improve prompt_fragment or add eval cases.
5. **Cross-domain pattern → new subdomain**. If work spans two domains repeatedly, it's a new subdomain.

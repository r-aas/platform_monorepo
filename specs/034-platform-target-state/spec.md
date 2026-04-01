<!-- status: in-progress -->
# 034 — Platform Target State

Single spec for all remaining platform work. Replaces 029-033 (archived in `specs/_archived/`).

Component interfaces are defined in `data/architecture/components.yaml`. AI system taxonomy in `data/compliance/taxonomy.yaml`. ISO 42001 compliance map in `data/compliance/iso42001.yml`. This spec says what needs to change and why. Those files say what exists now.

## Current State (2026-04-01)

**Working**: 8 agents (kagent CRDs, all Ready), 9 MCP servers (4 Ready, 5 need secrets), agentgateway (243 tools federated, 4 CEL policies), agentregistry (6 agents, 9 servers, 21 skills), LiteLLM, Langfuse, MLflow, n8n, ODD Platform, Plane, GitLab CE, ArgoCD. Policy engine: 18 policies, solo/enterprise profiles.

**Dead weight**: transpiler script, `agents/_shared/`, `agents/envs/`, 9 old MCP Helm charts (superseded by MCPServer CRDs once secrets are fixed), 5 n8n workflows that duplicate kagent agents.

## Work Items

Each item is a discrete deliverable. No dependencies between items unless noted.

### W1: MCP Server Secrets

Create 5 k8s secrets so all 9 MCPServer CRDs reach Ready. Then delete the 9 old `charts/genai-mcp-*` directories.

| Secret | Keys | Source |
|--------|------|--------|
| mcp-langfuse-env | LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY | secrets.env |
| mcp-minio-env | MINIO_ROOT_USER, MINIO_ROOT_PASSWORD | secrets.env |
| mcp-plane-env | PLANE_API_KEY | secrets.env (PLANE_API_TOKEN) |
| mcp-gitlab-env | GITLAB_TOKEN | secrets.env (GITLAB_PAT) |
| mcp-n8n-env | N8N_API_KEY | secrets.env |

**Verify**: `kubectl get mcpservers -n genai` — all 9 show Ready=True.
**Then delete**: `charts/genai-mcp-kubernetes/` through `charts/genai-mcp-ollama/` (9 dirs).

### W2: Delete Transpiler + Custom Agent Format

Delete `scripts/agentspec-to-kagent.py`, `agents/_shared/`, `agents/envs/`. Agent CRDs are authored directly in `charts/genai-kagent/templates/`.

**Verify**: `kubectl get agents.kagent.dev -n genai` shows 8 agents, all Ready.

### W3: OTEL → Langfuse Trace Pipeline

Enable `otel.enabled: true` in kagent Helm values. Route traces to Langfuse OTEL ingestion endpoint.

| Step | What |
|------|------|
| Set `otel.enabled: true` | kagent emits OTEL spans |
| Deploy OTEL collector or configure direct export | Spans reach Langfuse |
| Set Langfuse OTEL endpoint | `langfuse-web:3000/api/public/otel/v1/traces` |

**Verify**: Agent invocation via A2A → traces visible in Langfuse UI with tool-call spans.

### W4: Delete Redundant n8n Workflows

5 workflows replaced by kagent agents:

| Workflow | Replacement |
|----------|-------------|
| chat-v1.json | Agent CRDs + A2A |
| a2a-server-v1.json | kagent native A2A |
| agent-eval-v1.json | qa-eval Agent CRD + MLflow |
| claude-autonomous.json | developer Agent CRD |
| prompt-resolve-v1.json | Agent CRD with prompt tools |

**Verify**: n8n UI shows 12 active workflows (API pass-throughs + data pipelines).

### W5: Agent Promotion Pipeline

Three namespaces: `genai-dev`, `genai-stage`, `genai`. kagent controller already supports `watchNamespaces`.

| Gate | Trigger | Checks | Threshold |
|------|---------|--------|-----------|
| dev → staging | MR merge to main | CRD lint, benchmark vs baseline, gitleaks | pass_rate ≥ 85% |
| staging → production | Release tag | Soak period (2 cycles), integration test, regression | pass_rate ≥ 90% |

**Verify**: Push agent change to feature branch → deploys to genai-dev. Merge → genai-stage. Tag → genai.

### W6: Taxonomy-Aware Policy Engine

Wire `data/compliance/taxonomy.yaml` into `agentops-policy.py`:

- Add `--type` flag to scope policies by system type
- Agent specs get a `type` field (declarative/autonomous/orchestrator)
- MCP servers only get 3 policies instead of 18
- Add `--scope-doc` flag to auto-generate ISO 42001 Clause 4.3 scope document

**Verify**: `uv run scripts/agentops-policy.py --type mcp_server` runs 3 policies. `--scope-doc` produces markdown.

### W7: OWASP Agentic Top 10 Policies

10 new policies (P-050 through P-059). Compliance map at `data/compliance/owasp-agentic-top10.yml`.

| ID | Name | Check |
|----|------|-------|
| P-050 | prompt-injection-defense | System prompt has injection mitigation instructions |
| P-051 | tool-permission-boundaries | All tools have explicit allow/deny in spec |
| P-052 | privilege-escalation-guard | No agent can grant itself elevated permissions |
| P-053 | tool-output-validation | Agent spec declares output schema or validation |
| P-054 | cross-agent-trust-boundary | Multi-agent calls go through A2A, not direct |
| P-055 | memory-poisoning-defense | Memory has TTL and source tagging |
| P-056 | cascading-hallucination-guard | Multi-hop tool chains have depth limit |
| P-057 | resource-exhaustion-limit | Token budget and timeout declared in spec |
| P-058 | supply-chain-integrity | All images from signed registry (ghcr.io) |
| P-059 | logging-completeness | OTEL traces enabled, Langfuse scoring active |

**Verify**: `uv run scripts/agentops-policy.py --standard owasp` runs 10 checks.

### W8: Admission Policies (Kyverno + CEL)

Three-layer admission architecture (research: microsoft/agent-governance-toolkit GovernedAgent CRD, safe-k8s D09.007):

| Layer | Engine | Scope |
|-------|--------|-------|
| 1 | Kyverno ClusterPolicy | Standard k8s (pod security, resource limits, image registry) |
| 2 | Kyverno CEL expressions | Agent-specific (tool count, eval score, purpose annotation) |
| 3 | agentgateway CEL | Runtime (tool-level RBAC, dangerous tool blocking — already deployed) |

Layer 2 policies for agent CRDs:

| Policy | CEL Expression | Action |
|--------|---------------|--------|
| require-eval-pass | `has(object.metadata.annotations['agentops.dev/eval-pass-rate'])` | audit → enforce |
| require-tool-budget | `object.spec.tools.size() <= 20` | audit → enforce |
| require-purpose | `has(object.metadata.annotations['agentops.dev/purpose'])` | audit → enforce |

Start in audit mode. Switch to enforce after 1 week of clean audits. Publish as CI/CD Catalog component.

**Verify**: `kubectl apply` of non-compliant Agent CRD → warning (audit) or rejection (enforce). `kubectl get policyreport -n genai` shows audit results.

### W9: Compliance Dashboard

Log policy results to MLflow experiment `__agentops_compliance`. Annotate Langfuse traces with compliance scores.

| View | Source |
|------|--------|
| Agent × Policy heatmap | MLflow |
| Annex A coverage gauge | iso42001.yml |
| Compliance trend | MLflow time series |
| Per-invocation annotations | Langfuse scores |

**Verify**: `mlflow.platform.127.0.0.1.nip.io` → experiment `__agentops_compliance` has runs.

### W10: Slim agent-gateway to ~500 LOC

Delete everything kagent + agentregistry + agentgateway already does. Keep:

| Keep | Why |
|------|-----|
| Sandbox runtime (ephemeral k8s Jobs) | No OSS equivalent |
| Warm pod pool | Performance |
| `/health/detail` aggregation | Single pane of glass |
| Scheduling coordination | CronJob template management |

**Verify**: `wc -l services/agent-gateway/src/**/*.py` < 600.

### W11: GitLab CI/CD Catalog

Create reusable pipeline components in `ci-catalog/`. Each is a parameterized template published to GitLab CI/CD Catalog.

| Component | Inputs | What it does |
|-----------|--------|-------------|
| `agent-lint` | agent_name, strict | CRD schema lint, tool count, no secrets |
| `agent-eval-gate` | agent_name, threshold, baseline_source | Benchmark vs MLflow baseline |
| `mcp-server-deploy` | server_name, image, transport | MCPServer CRD validation + health |
| `compliance-check` | profile, standard, type | agentops-policy.py with taxonomy scoping |
| `promotion-gate` | agent_name, source_env, target_env | Soak, integration test, regression |

Convention: include components via `include: component:` syntax. Never copy-paste pipeline YAML.

**Verify**: `ci-catalog/` contains 5 components, each with `template.yml` and `README.md`. At least one agent pipeline uses `include: component:` syntax.

### W12: GitOps × AgentOps Lifecycle Integration

Wire the 7 AgentOps decision graphs into the GitOps apparatus. ArgoCD manages state, GitLab CI manages gates, agentops-policy.py manages compliance. Each graph maps to a concrete execution path.

| Graph | GitOps Trigger | CI/CD Catalog Component | ArgoCD Action |
|-------|---------------|------------------------|---------------|
| G1: Define | MR opened with agent spec change | `agent-lint` | — |
| G2: Evaluate | MR pipeline stage | `agent-eval-gate` | — |
| G3: Promote | MR merge (→staging) or tag (→prod) | `promotion-gate` | Sync to target namespace |
| G4: Request | Runtime (no GitOps trigger) | — | — |
| G5: Monitor | CronJob or Langfuse webhook | `compliance-check` | — |
| G6: Incident | Alert or audit failure | — | Rollback to previous Git SHA |
| G7: Audit | Scheduled pipeline | `compliance-check` | — |

ArgoCD ApplicationSets for namespace promotion:

```yaml
# Three ApplicationSets, one per environment
genai-dev:    sources from branch HEAD, auto-sync
genai-stage:  sources from main branch, auto-sync after CI passes
genai:        sources from release tags, manual sync
```

GitLab CI pipeline template (`.gitlab-ci.yml`) composes from catalog:

```yaml
include:
  - component: $CI_SERVER_FQDN/platform/ci-catalog/agent-lint@main
    inputs: { agent_name: "$AGENT", strict: true }
  - component: $CI_SERVER_FQDN/platform/ci-catalog/agent-eval-gate@main
    inputs: { agent_name: "$AGENT", threshold: "0.85" }
  - component: $CI_SERVER_FQDN/platform/ci-catalog/promotion-gate@main
    inputs: { agent_name: "$AGENT", source_env: dev, target_env: staging }
```

MCP server changes use a simpler pipeline:

```yaml
include:
  - component: $CI_SERVER_FQDN/platform/ci-catalog/mcp-server-deploy@main
    inputs: { server_name: "$SERVER", transport: http }
  - component: $CI_SERVER_FQDN/platform/ci-catalog/compliance-check@main
    inputs: { profile: solo, type: mcp_server }
```

**Verify**: Agent spec MR → lint → eval → promote pipeline runs end-to-end. ArgoCD syncs to correct namespace. `agentops-policy.py --gate` runs in CI.

## Priority Order

| Priority | Items | Why first |
|----------|-------|-----------|
| P1 | W1, W2 | Unblock MCPServer CRDs, delete dead code |
| P1 | W3 | Observability is table stakes |
| P1 | W11, W12 | CI/CD Catalog + GitOps×AgentOps integration enables all downstream gates |
| P2 | W5, W6 | Promotion pipeline + taxonomy-aware policies |
| P2 | W4, W10 | Delete redundant code |
| P2 | W7, W8, W9 | Governance hardening |

## Success Criteria

- [ ] All 9 MCPServer CRDs Ready, old charts deleted
- [ ] No transpiler, no `agents/_shared/`, no `agents/envs/`
- [ ] OTEL traces from kagent visible in Langfuse
- [ ] 12 n8n workflows (5 deleted)
- [ ] dev → staging → production promotion with eval gates
- [ ] `agentops-policy.py --type` scopes by taxonomy
- [ ] 28 policies (18 existing + 10 OWASP)
- [ ] At least 1 admission policy in audit mode
- [ ] Compliance metrics in MLflow
- [ ] agent-gateway < 600 LOC
- [ ] 5 CI/CD Catalog components published, composable via `include:`
- [ ] All 7 AgentOps graphs mapped to GitOps triggers (ArgoCD ApplicationSets + CI pipelines)
- [ ] Agent MR → lint → eval → promote pipeline runs end-to-end

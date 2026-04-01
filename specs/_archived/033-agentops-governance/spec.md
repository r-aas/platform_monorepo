<!-- status: in-progress -->
# 033 — AgentOps Governance: ISO 42001 Compliance, Policy Engine, Taxonomy

Extends: 029 (platform consolidation), 032 (kagent central architecture).

## 1. Problem

The platform has a working agent lifecycle (define → evaluate → promote → request → monitor → incident → audit) but no formal governance framework. Policy checks exist (`agentops-policy.py`, 18 policies) but lack:

- **Formal AI system taxonomy** — ISO 42001 Clause 4.3 requires organizations to define their AIMS scope, including what constitutes an "AI system." We use terms like "Agent Runtime," "MCP Server," "Agent Orchestrator" informally. No machine-readable taxonomy.
- **Compliance traceability** — `iso42001.yml` maps controls to policies, but no CI-level enforcement or dashboard visibility. No audit trail.
- **Admission-time enforcement** — Policies run as CLI checks. No Kubernetes admission control (Kyverno/CEL) to block non-compliant agent deployments.
- **Standards expansion** — Only ISO 42001 is mapped. OWASP Agentic Top 10, NIST COSAiS, and EU AI Act are banked but not integrated.
- **Taxonomy-driven routing** — Agent type should determine which policies apply, what eval thresholds are required, and what observability is mandated.

## 2. Goals

| # | Goal |
|---|------|
| G1 | Formalize an AI system taxonomy (machine-readable, ISO 22989-aligned) |
| G2 | Bind taxonomy types to policy scopes (which policies apply to which system types) |
| G3 | Add Kubernetes admission policies for agent CRDs (CEL via agentgateway or Kyverno) |
| G4 | Build compliance dashboard (policy results → MLflow or Langfuse metrics) |
| G5 | Integrate OWASP Agentic Top 10 as security gates |
| G6 | Prepare NIST COSAiS overlay mapping (tracking, not blocking) |
| G7 | Automate ISO 42001 Clause 4.3 scope document generation from taxonomy + inventory |

## 3. Non-Goals

- Full ISO 42001 certification (requires organizational controls beyond tooling)
- EU AI Act conformity assessment (deferred — regulation still evolving)
- Singapore IMDA Framework (deferred)
- Replacing agentgateway CEL policies (they complement, not overlap)

## 4. AI System Taxonomy

ISO 42001 does not define AI system types — it defers to ISO 22989 ("AI system": engineered system generating outputs for human-defined objectives) and requires organizations to define their own scope (Clause 4.3). ISO 23053 defines abstract functional components (data management, model, inference, monitoring).

We define the following taxonomy, informed by ISO 22989/23053 but specific to our agentic platform:

### 4.1 System Types

```yaml
# data/compliance/taxonomy.yaml
schema_version: 1
standard_refs:
  - "ISO/IEC 22989:2022 §3.1.4 (AI system)"
  - "ISO/IEC 22989:2022 §3.1.29 (AI agent)"
  - "ISO/IEC 23053:2022 (AI functional components)"
  - "ISO/IEC 42001:2023 Clause 4.3 (AIMS scope)"

types:
  agent:
    description: Autonomous entity that senses environment and acts toward objectives
    iso_ref: "ISO 22989 §3.1.29"
    subtypes:
      declarative:
        description: Agent with fixed tool set and system prompt, no dynamic planning
        examples: [platform-admin, project-coordinator]
      autonomous:
        description: Agent with dynamic planning, tool selection, memory
        examples: [developer, mlops]
      orchestrator:
        description: Agent that coordinates other agents (multi-agent)
        examples: [qa-eval]
    policy_scope: [P-001 through P-041]  # all policies apply

  mcp_server:
    description: Tool provider exposing capabilities via Model Context Protocol
    iso_ref: "ISO 23053 §5.3 (tool component)"
    examples: [mcp-kubernetes, mcp-gitlab, mcp-mlflow]
    policy_scope: [P-003, P-006, P-032]  # tool naming, purpose, observability

  llm_gateway:
    description: Proxy routing LLM requests to inference backends
    iso_ref: "ISO 23053 §5.2 (inference component)"
    examples: [litellm]
    policy_scope: [P-002, P-032]  # no secrets, observability

  eval_pipeline:
    description: Automated quality gate producing pass/fail verdicts
    iso_ref: "ISO 23053 §5.4 (monitoring component)"
    examples: [benchmark-runner, agentops-policy.py]
    policy_scope: [P-010, P-012, P-020, P-041]  # data, eval, threshold, provenance

  artifact_store:
    description: Versioned storage for datasets, models, agent snapshots
    iso_ref: "ISO 23053 §5.1 (data management component)"
    examples: [mlflow, minio]
    policy_scope: [P-002, P-041]  # no secrets, provenance

  observability:
    description: Trace collection, cost tracking, session replay
    iso_ref: "ISO 23053 §5.4 (monitoring component)"
    examples: [langfuse, otel-collector]
    policy_scope: [P-032]  # observability itself
```

### 4.2 Taxonomy Properties

Each system type carries:

| Property | Purpose | Example |
|----------|---------|---------|
| `policy_scope` | Which AgentOps policies apply | Agent: all 18; MCP Server: 3 |
| `eval_required` | Whether promotion requires eval gate | Agent: yes; MCP Server: health-only |
| `observability_level` | Minimum trace granularity | Agent: span-per-tool-call; Gateway: request-count |
| `iso_controls` | Which Annex A controls this type satisfies | Agent: A.4.2, A.6.2.2; MCP Server: A.4.4 |
| `risk_tier` | Impact classification for A.5 assessment | autonomous agent: high; declarative: medium; MCP server: low |

## 5. Policy Engine Enhancements

### 5.1 Taxonomy-Aware Policy Scoping

Currently `agentops-policy.py` runs all 18 policies against all agents. With taxonomy:

```python
# Policy only runs if system type is in its scope
POLICY_SCOPE = {
    "P-001": {"agent"},
    "P-003": {"agent", "mcp_server"},
    "P-010": {"agent", "eval_pipeline"},
    # ...
}
```

### 5.2 New Policies (OWASP Agentic Top 10)

| ID | Name | OWASP Ref | Level | Enforcement |
|----|------|-----------|-------|-------------|
| P-050 | prompt-injection-defense | ASI-01 | L1 | static |
| P-051 | tool-permission-boundaries | ASI-02 | L0 | static |
| P-052 | privilege-escalation-guard | ASI-03 | L2 | runtime |
| P-053 | tool-output-validation | ASI-04 | L2 | static |
| P-054 | cross-agent-trust-boundary | ASI-05 | L2 | static |
| P-055 | memory-poisoning-defense | ASI-06 | L3 | runtime |
| P-056 | cascading-hallucination-guard | ASI-07 | L2 | runtime |
| P-057 | resource-exhaustion-limit | ASI-08 | L1 | static |
| P-058 | supply-chain-integrity | ASI-09 | L3 | static |
| P-059 | logging-completeness | ASI-10 | L1 | static |

### 5.3 Kubernetes Admission Policies

Extend existing agentgateway CEL policies with agent-lifecycle gates:

```yaml
# Agent CRD admission — block deploy without eval pass
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
metadata:
  name: require-eval-pass
spec:
  targetRef:
    group: kagent.dev
    kind: Agent
  cel:
    expressions:
      - "has(object.metadata.annotations['agentops.dev/eval-pass-rate'])"
      - "double(object.metadata.annotations['agentops.dev/eval-pass-rate']) >= 0.8"
```

Alternative: Kyverno ClusterPolicies for richer validation (JSON schema, external API calls).

## 6. Compliance Dashboard

### 6.1 Data Flow

```
agentops-policy.py --json
    → MLflow experiment "__agentops_compliance"
        → run per agent per check
        → metrics: pass_rate, coverage, enforcement_stats
    → Langfuse score (per agent trace)
        → score_name: "iso42001_compliance"
        → value: 0.0-1.0 (policies passed / applicable)
```

### 6.2 Dashboard Views

| View | Source | Content |
|------|--------|---------|
| Compliance heatmap | MLflow | Agent × Policy matrix, color-coded |
| Coverage gauge | iso42001.yml | % of Annex A controls with automated checks |
| Trend line | MLflow | Compliance score over time per agent |
| Audit log | Langfuse | Per-invocation compliance annotations |

## 7. ISO 42001 Clause 4.3 Scope Document

Auto-generated from taxonomy + agent inventory:

```markdown
# AIMS Scope Document (Auto-generated)

## Organization: Applied AI Systems, LLC
## Standard: ISO/IEC 42001:2023
## Generated: {date}

## AI System Inventory

| System | Type | Subtype | Risk Tier | Status |
|--------|------|---------|-----------|--------|
| platform-admin | agent | declarative | medium | production |
| developer | agent | autonomous | high | production |
| mcp-kubernetes | mcp_server | — | low | production |
| litellm | llm_gateway | — | medium | production |
| ...

## Compliance Profile: {solo|enterprise}
## Policy Coverage: {N}/{M} Annex A controls automated
## Last Audit: {date}
```

## 8. Implementation Phases

### Phase 1: Taxonomy (this sprint)
- [ ] Create `data/compliance/taxonomy.yaml`
- [ ] Add `--type` flag to `agentops-policy.py` for taxonomy-aware scoping
- [ ] Add `type` field to agent spec YAML schema
- [ ] Generate Clause 4.3 scope document from inventory

### Phase 2: OWASP Integration
- [ ] Implement P-050 through P-059 (10 security policies)
- [ ] Map to `data/compliance/owasp-agentic-top10.yml` compliance map
- [ ] Add `--standard owasp` filter to policy engine

### Phase 3: Admission Policies
- [ ] CEL policies for agent CRD validation (eval-pass annotation required)
- [ ] Kyverno ClusterPolicies for richer validation (if CEL insufficient)
- [ ] CI pipeline integration (GitLab CI runs policy engine as gate)

### Phase 4: Dashboard + Audit Trail
- [ ] MLflow compliance experiment logging
- [ ] Langfuse compliance score annotations
- [ ] Auto-generated scope document in CI artifacts

### Phase 5: NIST COSAiS Overlay (tracking)
- [ ] Map NIST SP 800-53 AI controls to existing policies
- [ ] Create `data/compliance/nist-cosais.yml` compliance map
- [ ] Track coverage gaps, no enforcement yet

## 9. Risks

| Risk | Mitigation |
|------|------------|
| Taxonomy too rigid | Keep types extensible (subtypes array), version schema |
| Policy explosion (18→28+) | Group by standard, filter by `--standard` flag |
| Admission policies block legit deploys | Start in audit mode (warn, don't block) |
| OWASP checks are subjective | Static checks for structure; runtime checks for behavior |
| NIST COSAiS not finalized | Track only, don't block on it |

## 10. Success Criteria

- [ ] `data/compliance/taxonomy.yaml` exists and validates
- [ ] `agentops-policy.py --type agent` scopes policies correctly
- [ ] `agentops-policy.py --standard owasp` runs OWASP checks
- [ ] Clause 4.3 scope document auto-generates from `--scope-doc`
- [ ] At least 1 admission policy blocks non-compliant agent CRD
- [ ] MLflow compliance metrics visible in dashboard
- [ ] 62% → 75%+ Annex A coverage after OWASP integration

## 11. Reference Repos

| Repo | What We Learned |
|------|----------------|
| `microsoft/agent-governance-toolkit` | OPA+Cedar backends, trust scoring, execution rings, 10/10 OWASP |
| `ciso-assistant-community` | Machine-readable ISO 42001 YAML with maturity scoring |
| `rulehub/rulehub` | Compliance map schema (framework → policy mapping) |
| `safe-k8s` | 593 K8s controls, `primary_enforcement_point` concept |
| `HeadyZhang/agent-audit` | Static security scanner, 53 OWASP rules |
| `Aquifer-sea/pattern8` | Zero-trust governance, MCP SecurityGuard pattern |
| `finos-labs/open-eago` | FINOS enterprise multi-agent orchestration spec |

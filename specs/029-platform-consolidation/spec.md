<!-- status: in-progress -->
# 029 - Platform Consolidation

## Summary

Replace the custom agent-gateway monolith with a composition of best-of-breed OSS components: **kagent** (agent runtime), **agentgateway** (MCP/A2A proxy), **agentregistry** (catalog + discovery), **MetaMCP** (namespace scoping), and **LiteLLM** (LLM proxy, already deployed). The custom agent-gateway shrinks to a thin orchestration glue layer.

## Problem

The current agent-gateway service owns too many concerns:
- Agent registry (PostgreSQL + pgvector)
- OpenAI-compatible chat proxy
- MCP proxy / tool federation
- A2A card serving
- Sandbox runtime (ephemeral k8s Jobs)
- Skill catalog + semantic discovery

Each of these now has a mature OSS project that does it better. Maintaining a custom implementation across all six axes is unsustainable for a one-person platform.

## Goals

| # | Goal |
|---|------|
| G1 | Replace MCP proxying with agentgateway (Rust, CNCF sandbox, MCP+A2A+LLM gateway) |
| G2 | Replace agent registry + skill catalog with agentregistry (Go, pgvector, CLI + web UI) |
| G3 | Add kagent as the Kubernetes-native agent runtime (CRDs for Agent, Tool, ModelConfig) |
| G4 | Add MetaMCP for namespace-scoped MCP server filtering (per-agent tool subsets) |
| G5 | Retain LiteLLM as the LLM proxy (already deployed, working) |
| G6 | Shrink custom agent-gateway to orchestration glue only: semantic discovery, scheduling coordination, cross-component health |
| G7 | Move from n8n CronJob-triggered workflows to CronJob -> kagent A2A for scheduled agent tasks |

## Non-Goals

- Multi-cluster federation (k3d single cluster only)
- Cloud LLM providers (Ollama-only for now)
- Replacing n8n for human-in-the-loop workflows

## Component Roles

### agentgateway (CNCF)
- **What**: Rust proxy for MCP, A2A, and LLM traffic
- **Why chosen**: Only project that unifies all three protocols. CEL policy engine, RBAC, rate limiting, OpenTelemetry built in. Kubernetes controller with Gateway API support.
- **Replaces**: Custom MCP proxy, A2A card serving, tool federation logic in agent-gateway

### agentregistry
- **What**: Go registry for MCP servers, agents, skills, and prompts with pgvector semantic search
- **Why chosen**: Unified catalog with CLI (`areg`) and web UI. Supports import from npm/PyPI/Docker/GitHub. Metadata enrichment and curation.
- **Replaces**: Custom PostgreSQL+pgvector registry, skill catalog, SKILL.md file-based discovery

### kagent
- **What**: Kubernetes-native agent runtime using CRDs (Agent, Tool, ModelConfig, Memory)
- **Why chosen**: Agents are k8s resources. Built on AutoGen 0.4 (AgentChat). Supports A2A protocol natively. Memory CRD for persistent agent state.
- **Replaces**: Custom sandbox runtime (ephemeral Jobs), agent execution logic

### MetaMCP
- **What**: MCP namespace scoping proxy
- **Why chosen**: Solves the "too many tools" problem. Filters MCP servers per agent/context. Sits between kagent and agentgateway.
- **Replaces**: Planned custom namespace scoping (see project_mcp_namespace_scoping.md memory)

### LiteLLM (existing)
- **What**: Python LLM proxy with OpenAI-compatible API
- **Why chosen**: Already deployed and working. Budget controls, model aliasing, usage tracking.
- **Replaces**: Nothing new -- already in stack

### agent-gateway (slim)
- **What**: Thin Python (FastAPI) orchestration service
- **Shrinks to**: Semantic discovery across agentregistry, cross-component health aggregation (`/health/detail`), scheduling coordination (CronJob templates), dashboard data aggregation
- **Removes**: MCP proxy, A2A cards, chat proxy, registry storage, sandbox runtime

## Integration Points

| Source | Target | Protocol | Auth | Purpose |
|--------|--------|----------|------|---------|
| CronJob | kagent | HTTP POST (A2A) | ServiceAccount | Scheduled agent tasks |
| kagent agent | agentgateway | MCP (Streamable HTTP) | JWT | Tool calls |
| kagent agent | LiteLLM | OpenAI-compat HTTP | Bearer token | LLM inference |
| agentgateway | MCP servers (9) | stdio/SSE/HTTP | Per-server secrets | Tool execution |
| agentgateway | agentregistry | HTTP | API key | Tool discovery |
| MetaMCP | agentgateway | MCP | JWT | Namespace-filtered tool access |
| n8n | agentgateway | MCP (SSE) | Bearer token | Tool calls from workflows |
| n8n | LiteLLM | OpenAI-compat HTTP | Bearer token | Chat completions |
| agentregistry | PostgreSQL+pgvector | TCP | Password | Catalog storage + semantic search |
| agent-gateway (slim) | agentregistry | HTTP | API key | Discovery aggregation |
| agent-gateway (slim) | kagent | k8s API | ServiceAccount | Agent status, CRD reads |

## Scheduling Model

**Current**: n8n CronJob workflows trigger HTTP requests to custom endpoints.

**Target**: Kubernetes CronJobs POST to kagent A2A endpoints. Each scheduled task is:
1. A `CronJob` resource in the `genai` namespace
2. A minimal container that POSTs a task to kagent's A2A endpoint
3. kagent creates an agent pod, executes the task, stores results in Memory CRD
4. Agent pod terminates after completion

Benefits: No n8n dependency for scheduled automation. n8n reserved for human-in-the-loop workflows, complex branching, and UI-driven operations.

## Deployment

All components deploy as Helm charts managed by ArgoCD in the `genai` namespace.

| Component | Chart Source | Image | ARM64 |
|-----------|-------------|-------|-------|
| agentgateway | `controller/install/helm` (upstream) | `ghcr.io/agentgateway/agentgateway` | Yes (Rust) |
| agentregistry | TBD (upstream or custom) | `ghcr.io/agentregistry-dev/agentregistry` | Verify |
| kagent | TBD (upstream Helm) | TBD | Verify |
| MetaMCP | Custom chart | TBD | Verify |
| LiteLLM | Existing `genai-litellm` chart | `ghcr.io/berriai/litellm` | Yes |
| agent-gateway (slim) | Existing chart, trimmed | Custom build | Yes (Python) |

## Rollout Phases

### Phase 1: agentgateway (MCP proxy replacement)
- Deploy agentgateway Helm chart
- Migrate 9 MCP server configs to agentgateway YAML
- Verify all MCP tools accessible via agentgateway
- Remove MCP proxy code from custom agent-gateway

### Phase 2: agentregistry (catalog replacement)
- Deploy agentregistry with pgvector
- Import existing MCP servers and skills into registry
- Wire agentgateway to discover tools from agentregistry
- Remove registry code from custom agent-gateway

### Phase 3: kagent (agent runtime)
- Deploy kagent CRDs and controller
- Create Agent/Tool/ModelConfig CRDs for existing agents
- Migrate one scheduled workflow from n8n to CronJob -> kagent
- Validate A2A communication through agentgateway

### Phase 4: MetaMCP (namespace scoping)
- Deploy MetaMCP
- Configure per-agent tool namespaces
- Wire kagent agents to use MetaMCP instead of direct agentgateway

### Phase 5: Slim agent-gateway
- Strip removed capabilities from custom agent-gateway
- Retain: semantic discovery, health aggregation, scheduling templates
- Update dashboard to query new components

## Risks

| Risk | Mitigation |
|------|-----------|
| agentgateway ARM64 image availability | Rust cross-compile; build from source if needed |
| kagent maturity (early project) | Phase 3 is last; evaluate stability during phases 1-2 |
| agentregistry pgvector conflicts with existing DB | Separate PostgreSQL instance or shared with schema isolation |
| MetaMCP adds latency to tool calls | Benchmark; bypass for latency-sensitive agents |
| Too many moving parts at once | Phased rollout; each phase has independent rollback |

## Success Criteria

- [ ] All 9 MCP servers accessible through agentgateway
- [ ] Tool catalog searchable via agentregistry CLI and API
- [ ] At least one agent running as kagent CRD
- [ ] Scheduled task executes via CronJob -> kagent A2A
- [ ] Custom agent-gateway codebase reduced by >60%
- [ ] No regression in existing n8n workflows

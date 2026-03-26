<!-- status: draft -->
# Spec 027: Agent Platform — Registry, Skills, Environments, Sandboxed Execution

## Problem

The platform has a working agent gateway (spec 001) with three agents (mlops, developer, platform-admin) backed by MLflow tags and n8n workflows. But:

1. **Agent definitions are not portable.** They're stored as MLflow prompt tags — custom, flat, locked to our infra. Can't deploy the same agent to OCI, AWS, or another A2A-compliant host.

2. **Skills are bolted onto agents, not first-class.** Skills are MLflow model registry entries with JSON-encoded tags. No versioning, no capability abstraction, no discovery beyond our gateway.

3. **Environment binding doesn't exist.** Agent definitions hardcode cluster-internal URLs (litellm:4000, mcp-kubernetes:3000). Moving an agent to another environment means rewriting the definition.

4. **No sandboxed execution.** Agents run via n8n only. No way to run Claude Code, OpenHands, or other coding agents in ephemeral isolated environments.

5. **MLflow is overloaded.** It's the agent registry, skill registry, prompt store, experiment tracker, and model registry. Agent metadata doesn't fit its data model (deeply nested, multi-environment, relationship-heavy).

6. **No GitOps for agents.** Agent sync is manual (`task agent-sync`). Definitions should flow through git → ArgoCD → cluster like everything else.

## Vision

Agents are portable artifacts defined in Oracle Agent Spec format, stored in git, deployed via ArgoCD, discoverable via A2A agent cards, executable on any runtime (n8n, direct LLM, cloud services, sandboxed containers). Skills are reusable capability packages with progressive disclosure. The agent registry is the control plane that binds portable definitions to concrete environments.

## Prior Art

| Project | Pattern We Adopt | What We Skip |
|---------|-----------------|--------------|
| **Oracle Agent Spec** | Portable agent YAML with Pydantic models, LLM config abstraction, tool types | Flows (we use n8n), OCI-specific adapters |
| **Google A2A** | Agent Cards for discovery, `tasks/send` + `tasks/sendSubscribe` for delegation | Push notifications (not needed yet) |
| **Microsoft Agent Framework** | SKILL.md manifest with progressive disclosure, runtime skill loading | .NET SDK, Copilot integration |
| **MCP Registry spec** | OpenAPI spec for MCP server discovery (`modelcontextprotocol/registry`) | GitHub-specific registry features |
| **ToolHive (Stacklok)** | K8s operator for MCP servers, multi-backend registry aggregation | vMCP token optimization (premature) |
| **BeeAI (IBM)** | Agent catalog with embedded metadata for scale-to-zero discovery | ACP (merged into A2A) |
| **kubernetes-sigs/agent-sandbox** | CRDs: Sandbox, SandboxTemplate, SandboxClaim; pre-warmed pod pools | gVisor (not on ARM64/k3d) |
| **LiteLLM MCP Registry** | `enable_mcp_registry: true` — free MCP discovery in existing stack | Already running, just needs config flag |
| **Spec 019** | A2A agent cards generated from catalog, skill tags, protocol compliance | Was n8n-scoped; this spec is platform-level |

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Git (Source of Truth)                        │
│                                                                      │
│  agents/                    skills/                 envs/agents/      │
│    mlops/agent.yaml           k8s-ops/SKILL.md       local.yaml      │
│    developer/agent.yaml       mlflow/SKILL.md        oci-prod.yaml   │
│    platform-admin/            code-review/SKILL.md                   │
│      agent.yaml               ...                                    │
│    sandbox-coder/                                                    │
│      agent.yaml                                                      │
│      Dockerfile.sandbox                                              │
└────────────────────────┬─────────────────────────────────────────────┘
                         │ ArgoCD auto-sync
                         ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     Agent Registry (FastAPI + pgvector)               │
│                                                                      │
│  Watches ConfigMaps (agent defs, skill defs, env bindings)           │
│                                                                      │
│  ┌────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│  │   Agents   │ │    Skills    │ │ Environments │ │ Deployments  │ │
│  │  catalog   │ │   catalog    │ │   bindings   │ │   tracker    │ │
│  └─────┬──────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ │
│        │               │                │                │          │
│  ┌─────▼───────────────▼────────────────▼────────────────▼────────┐ │
│  │                    PostgreSQL (pgvector)                        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Serves: REST API, A2A Agent Cards, MCP Registry                     │
└────────────────────────┬─────────────────────────────────────────────┘
                         │
            ┌────────────┼────────────────────┐
            ▼            ▼                    ▼
     ┌────────────┐ ┌──────────┐    ┌──────────────────┐
     │  Gateway   │ │ External │    │ Other Gateways   │
     │  (local)   │ │ A2A      │    │ (OCI, AWS, etc.) │
     │            │ │ clients  │    │                  │
     └─────┬──────┘ └──────────┘    └──────────────────┘
           │
     ┌─────┴──────┬──────────┬──────────────┐
     ▼            ▼          ▼              ▼
  ┌─────┐  ┌────────┐  ┌─────────┐  ┌───────────┐
  │ n8n │  │ direct │  │ sandbox │  │ A2A       │
  │     │  │ LLM +  │  │ (k8s   │  │ remote    │
  │     │  │ tools  │  │  Job)  │  │ agent     │
  └─────┘  └────────┘  └─────────┘  └───────────┘
```

## Components

### C.01: Agent Definitions (Oracle Agent Spec YAML)

Agents defined as portable Agent Spec YAML in `agents/{name}/agent.yaml`.

```yaml
# agents/mlops/agent.yaml
component_type: Agent
name: mlops
description: "MLOps engineer — experiment tracking, model lifecycle, monitoring"
agentspec_version: "26.2.0"

llm_config:
  component_type: OpenAiCompatibleConfig
  url: "{{llm_base_url}}"
  model_id: "{{llm_model}}"
  api_key: "{{llm_api_key}}"

system_prompt: |
  You are an MLOps engineer specializing in experiment tracking,
  model lifecycle management, and monitoring. You have access to
  MLflow, Kubernetes, and observability tools.

  Focus area: {{domain}}

tools:
  - component_type: RemoteTool
    name: mlflow_search
    description: "Search MLflow experiments and runs"
    url: "{{mcp_experiment_tracking}}/tools/call"
    http_method: POST

capabilities:
  - experiment-tracking
  - model-registry
  - kubernetes

skills:
  - kubernetes-ops
  - mlflow-tracking

metadata:
  runtime: n8n              # default runtime
  workflow: chat            # n8n workflow name
  tags: ["mlops", "platform"]
```

The `{{placeholders}}` are resolved from environment bindings at deployment time. The agent definition itself contains zero environment-specific values.

### C.02: Skill Definitions (SKILL.md + manifest)

Adopting Microsoft Agent Framework's progressive disclosure pattern, adapted to our stack. Skills live in `skills/{name}/SKILL.md`.

```markdown
---
name: kubernetes-ops
version: 1.1.0
description: Kubernetes cluster operations — pod management, deployments, troubleshooting
tags: [infrastructure, kubernetes, deployment]
capabilities:
  - kubernetes
operations:
  - get_pods
  - describe_resource
  - get_logs
  - rollout_status
---

# Kubernetes Operations

You can manage Kubernetes clusters. Available operations:

## Pod Management
- List and inspect pods across namespaces
- Read pod logs with filtering
- Check container status and restart counts

## Deployment Operations
- Check rollout status
- Describe deployments and their conditions

## Troubleshooting
- Identify CrashLoopBackOff pods
- Check resource limits and requests
- Inspect events for failure patterns

## Constraints
- Read-only operations only (no delete, no exec)
- Namespace-scoped (agent's namespace binding determines scope)
```

Progressive disclosure:
1. **Advertise** (~100 tokens): frontmatter name + description + tags
2. **Load** (full): entire SKILL.md injected into agent system prompt
3. **Resolve**: capabilities → MCP servers via environment binding

Skill evaluation datasets live alongside:
```
skills/kubernetes-ops/
  SKILL.md
  eval/
    get-pods.json
    troubleshoot.json
```

### C.03: Environment Bindings

Environment bindings resolve abstract agent requirements to concrete infrastructure. Stored in `envs/agents/{environment}.yaml`.

```yaml
# envs/agents/local.yaml
environment: local-k3d
cluster: mewtwo

gateway:
  url: http://agent-gateway.genai.127.0.0.1.nip.io
  internal: http://genai-agent-gateway.genai.svc.cluster.local:8000

llm:
  base_url: http://genai-litellm.genai.svc.cluster.local:4000/v1
  api_key_ref: secret/genai/litellm-api-key    # k8s secret reference
  default_model: qwen2.5:14b

mcp_registry: http://genai-litellm.genai.svc.cluster.local:4000

# Capability → MCP server mapping
capabilities:
  experiment-tracking:
    mcp_server: mlflow
    url: http://genai-mlflow.genai.svc.cluster.local:80
  model-registry:
    mcp_server: mlflow
    url: http://genai-mlflow.genai.svc.cluster.local:80
  kubernetes:
    mcp_server: mcp-kubernetes
    url: http://genai-mcp-kubernetes.genai.svc.cluster.local:3000
  git:
    mcp_server: mcp-gitlab
    url: http://genai-mcp-gitlab.genai.svc.cluster.local:3000
  workflows:
    mcp_server: mcp-n8n
    url: http://genai-mcp-n8n.genai.svc.cluster.local:3000
  catalog:
    mcp_server: mcp-datahub
    url: http://genai-mcp-datahub.genai.svc.cluster.local:8000
  ontology:
    mcp_server: open-ontologies
    url: http://genai-open-ontologies.genai.svc.cluster.local:8080

runtimes:
  n8n:
    url: http://genai-n8n.genai.svc.cluster.local:5678
    api_key_ref: secret/genai/n8n-api-key
  sandbox:
    image_registry: ""        # k3d uses local images
    namespace: genai
    service_account: agent-sandbox
    storage_class: local-path
    ttl_seconds: 3600
    resource_limits:
      cpu: "2"
      memory: 4Gi

auth:
  type: k8s-serviceaccount   # or oci-iam, aws-iam
```

```yaml
# envs/agents/oci-prod.yaml
environment: oci-prod

gateway:
  url: https://agents.r-aas.dev

llm:
  provider: oci-genai
  compartment_ref: vault/oci-compartment-id
  default_model: cohere.command-r-plus

capabilities:
  experiment-tracking:
    mcp_server: oci-datascience
    url: https://datascience.us-ashburn-1.oci.oraclecloud.com
  kubernetes:
    mcp_server: oci-container-engine
    url: https://containerengine.us-ashburn-1.oci.oraclecloud.com

runtimes:
  oci-agent-service:
    compartment_ref: vault/oci-compartment-id
    shape: VM.Standard.E4.Flex
```

### C.04: Agent Registry Service

FastAPI service backed by pgvector. Watches k8s ConfigMaps for agent/skill/env changes. Serves REST API, A2A agent cards, and MCP registry.

#### Schema

```sql
-- Agent definitions (from git via ArgoCD ConfigMaps)
CREATE TABLE agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT UNIQUE NOT NULL,
    version         TEXT NOT NULL,
    spec            JSONB NOT NULL,             -- full Agent Spec
    system_prompt   TEXT,                        -- extracted for search
    capabilities    TEXT[] NOT NULL DEFAULT '{}', -- abstract requirements
    skills          TEXT[] NOT NULL DEFAULT '{}', -- skill names
    runtime         TEXT NOT NULL DEFAULT 'n8n',
    tags            TEXT[] NOT NULL DEFAULT '{}',
    embedding       VECTOR(768),                -- semantic search
    git_sha         TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Skill definitions (from git via ArgoCD ConfigMaps)
CREATE TABLE skills (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT UNIQUE NOT NULL,
    version         TEXT NOT NULL,
    description     TEXT NOT NULL,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    capabilities    TEXT[] NOT NULL DEFAULT '{}', -- what capabilities this skill uses
    operations      TEXT[] NOT NULL DEFAULT '{}', -- tool operations exposed
    manifest        TEXT NOT NULL,               -- full SKILL.md content
    advertise       TEXT NOT NULL,               -- short description (~100 tokens)
    embedding       VECTOR(768),
    git_sha         TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Environment bindings (from git via ArgoCD ConfigMaps)
CREATE TABLE environment_bindings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    environment     TEXT NOT NULL,
    config          JSONB NOT NULL,             -- full env binding YAML as JSON
    capabilities    JSONB NOT NULL,             -- capability → server map
    llm_config      JSONB NOT NULL,
    runtimes        JSONB NOT NULL,
    UNIQUE(environment)
);

-- Deployment state (gateways report heartbeats)
CREATE TABLE deployments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name      TEXT NOT NULL REFERENCES agents(name),
    environment     TEXT NOT NULL,
    gateway_url     TEXT NOT NULL,
    agent_version   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'unknown', -- deployed, healthy, degraded, offline
    last_heartbeat  TIMESTAMPTZ,
    last_invocation TIMESTAMPTZ,
    error_count_1h  INTEGER DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    UNIQUE(agent_name, environment, gateway_url)
);

-- Capability catalog (aggregated from env bindings + MCP registries)
CREATE TABLE capabilities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT UNIQUE NOT NULL,
    description     TEXT,
    operations      JSONB DEFAULT '[]',         -- [{name, description, input_schema}]
    providers       JSONB DEFAULT '[]',         -- [{env, mcp_server, url}]
    embedding       VECTOR(768)
);

-- Evaluation results
CREATE TABLE eval_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name      TEXT NOT NULL,
    agent_version   TEXT NOT NULL,
    environment     TEXT NOT NULL,
    model           TEXT NOT NULL,
    skill           TEXT,
    task            TEXT,
    pass_rate       FLOAT,
    avg_latency_ms  FLOAT,
    results         JSONB,
    run_at          TIMESTAMPTZ DEFAULT now()
);
```

#### API

```
# Agents
GET    /agents                              # list all agents
GET    /agents/{name}                       # agent detail
GET    /agents/{name}/spec                  # export portable Agent Spec YAML
GET    /agents/{name}/spec?env={env}        # resolved spec (placeholders filled)
GET    /agents/{name}/versions              # version history
GET    /agents/search?q=...                 # semantic + keyword search
POST   /agents/sync                         # re-import from ConfigMaps

# Skills
GET    /skills                              # list all skills (advertise mode)
GET    /skills/{name}                       # full skill (SKILL.md content)
GET    /skills/{name}/advertise             # short description only
GET    /skills/search?q=...                 # search skills
GET    /skills/for-capability/{cap}         # skills that provide a capability
POST   /skills/sync                         # re-import from ConfigMaps

# Environments
GET    /envs                                # list all environments
GET    /envs/{env}                          # environment binding detail
GET    /envs/{env}/resolve/{agent}          # fully resolved agent for this env
GET    /envs/{env}/capabilities             # available capabilities in this env

# Deployments
POST   /deployments/heartbeat              # gateway reports agent status
GET    /deployments                         # all deployments across envs
GET    /deployments/{env}                   # deployments in one environment
GET    /deployments/{env}/{agent}           # specific agent deployment

# Capabilities
GET    /capabilities                        # catalog of all capabilities
GET    /capabilities/{name}                 # capability detail + providers per env
GET    /capabilities/search?q=...           # search by description
POST   /capabilities/sync                   # re-scan MCP registries

# Evaluation
GET    /agents/{name}/evals                 # eval history
GET    /agents/{name}/evals/baseline        # current baseline per skill/task
POST   /agents/{name}/evals                 # submit eval results

# A2A Discovery
GET    /.well-known/agent-card.json         # all agents as A2A agent cards
GET    /.well-known/agent-card/{name}.json  # single agent card

# MCP Registry (follows modelcontextprotocol/registry OpenAPI spec)
GET    /mcp/servers                         # list registered MCP servers
GET    /mcp/servers/{name}                  # server detail
GET    /mcp/servers/search?q=...            # search MCP servers
```

### C.05: Sandboxed Execution Runtime

For running coding agents (Claude Code, OpenHands, etc.) in ephemeral isolated environments.

#### Design

Adopts the `kubernetes-sigs/agent-sandbox` CRD pattern adapted for our stack (no gVisor — not available on ARM64/k3d).

```
User request → Gateway → Registry resolves agent
                         runtime = "sandbox"
                              │
                              ▼
                    ┌───────────────────┐
                    │  Sandbox Manager  │
                    │  (in gateway)     │
                    └────────┬──────────┘
                             │ creates
                             ▼
                    ┌───────────────────┐
                    │   K8s Job         │
                    │                   │
                    │  Container:       │
                    │  - agent runtime  │
                    │  - language tools │
                    │  - git client     │
                    │                   │
                    │  Mounts:          │
                    │  - task ConfigMap  │
                    │  - workspace PVC   │
                    │  - secrets         │
                    │                   │
                    │  NetworkPolicy:   │
                    │  - allow: LiteLLM │
                    │  - allow: MCP svcs│
                    │  - deny: all else │
                    │                   │
                    │  TTL: 1h          │
                    └───────────────────┘
```

#### Sandbox Image

```dockerfile
# images/agent-sandbox/Dockerfile
FROM python:3.12-slim

# Language runtimes and tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl jq nodejs npm && \
    rm -rf /var/lib/apt/lists/*

# Claude Agent SDK
RUN pip install --no-cache-dir claude-agent-sdk

# Workspace
RUN useradd -m -s /bin/bash agent
WORKDIR /home/agent/workspace
USER agent

# Entrypoint reads task from /task/config.yaml, executes, writes results to /output/
COPY entrypoint.py /usr/local/bin/entrypoint.py
ENTRYPOINT ["python", "/usr/local/bin/entrypoint.py"]
```

#### Sandbox Agent Spec

```yaml
# agents/sandbox-coder/agent.yaml
component_type: Agent
name: sandbox-coder
description: "Coding agent with full filesystem access in isolated sandbox"
agentspec_version: "26.2.0"

llm_config:
  component_type: OpenAiCompatibleConfig
  url: "{{llm_base_url}}"
  model_id: "{{llm_model}}"
  api_key: "{{llm_api_key}}"

system_prompt: |
  You are a software engineer working in an isolated sandbox environment.
  You have full filesystem access to /home/agent/workspace.
  You can run bash commands, read/write files, and use git.
  Complete the assigned task and write results to /output/result.json.

tools:
  - component_type: BuiltinTool
    name: bash
    tool_type: shell
    description: "Execute bash commands"
  - component_type: BuiltinTool
    name: read_file
    tool_type: filesystem_read
  - component_type: BuiltinTool
    name: write_file
    tool_type: filesystem_write

capabilities:
  - code-execution

metadata:
  runtime: sandbox
  sandbox:
    image: agent-sandbox:latest
    timeout: 3600
    resource_limits:
      cpu: "2"
      memory: 4Gi
  tags: ["coding", "sandbox"]
```

#### Sandbox Lifecycle

```
1. Gateway receives request for agent with runtime=sandbox
2. Gateway calls Registry: GET /envs/{env}/resolve/sandbox-coder
3. Registry returns resolved spec with concrete sandbox config
4. Gateway creates:
   a. ConfigMap: task description, input data
   b. PVC: workspace volume (or emptyDir for ephemeral)
   c. NetworkPolicy: restrict egress to LiteLLM + MCP servers only
   d. Job: sandbox image with mounts
5. Gateway polls Job status, streams logs via SSE
6. On completion:
   a. Read /output/result.json from PVC
   b. Return result to caller
   c. Job TTL controller cleans up pod
   d. PVC retained or deleted based on config
```

### C.06: GitOps Integration

#### Helm Chart: genai-agents

Templates agent definitions, skill definitions, and environment bindings as ConfigMaps.

```yaml
# charts/genai-agents/values.yaml
environment: local

# Agent registry watches these ConfigMaps
agents:
  mlops:
    enabled: true
  developer:
    enabled: true
  platform-admin:
    enabled: true
  sandbox-coder:
    enabled: true

skills:
  kubernetes-ops:
    enabled: true
  mlflow-tracking:
    enabled: true
  code-review:
    enabled: true
```

The chart reads agent.yaml and SKILL.md files from the repo and templates them into ConfigMaps with labels the registry watches.

#### ArgoCD ApplicationSet

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: agents
  namespace: platform
spec:
  generators:
    - list:
        elements:
          - environment: local
            namespace: genai
  template:
    metadata:
      name: agents-{{environment}}
    spec:
      project: genai
      source:
        repoURL: http://gitlab-ce.platform.svc.cluster.local/r/platform_monorepo.git
        path: charts/genai-agents
        helm:
          values: |
            environment: {{environment}}
      destination:
        server: https://kubernetes.default.svc
        namespace: "{{namespace}}"
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

#### Flow

```
1. Developer edits agents/mlops/agent.yaml, pushes to GitLab
2. ArgoCD detects change in charts/genai-agents path
3. ArgoCD renders Helm chart → ConfigMaps
4. ArgoCD applies ConfigMaps to cluster
5. Agent Registry detects ConfigMap change (k8s watch)
6. Registry imports updated agent definition
7. Registry updates pgvector embeddings for search
8. Registry regenerates A2A agent card
9. Gateway queries registry on next request → gets new definition
```

No manual sync. No MLflow writes. Git push is the only deploy mechanism.

### C.07: Migration from MLflow

MLflow stops being the agent/skill registry. Phased migration:

| Phase | MLflow Role | Registry Role |
|-------|------------|---------------|
| **Phase 0** (current) | Agent defs (prompt tags), skill defs (model tags) | Does not exist |
| **Phase 1** | Read-only (gateway reads from both, prefers registry) | Primary for agent/skill defs |
| **Phase 2** | Experiment tracking + eval results only | Full agent/skill/env/deployment lifecycle |
| **Phase 3** | Experiment tracking only | Everything else |

MLflow keeps: experiments, metrics, model artifacts, eval baselines.
MLflow loses: agent definitions, skill definitions, prompt templates (moved to git).

## Requirements

### Functional

| ID | Requirement | Component |
|----|-------------|-----------|
| FR-001 | Agent definitions in Oracle Agent Spec YAML format | C.01 |
| FR-002 | Agents portable across environments via placeholder resolution | C.01, C.03 |
| FR-003 | Skill definitions with SKILL.md manifest and progressive disclosure | C.02 |
| FR-004 | Skills declare abstract capabilities, environments resolve to MCP servers | C.02, C.03 |
| FR-005 | Environment binding YAML maps capabilities → concrete infra | C.03 |
| FR-006 | Agent registry service with REST API, A2A cards, MCP registry | C.04 |
| FR-007 | Registry watches k8s ConfigMaps for real-time sync | C.04, C.06 |
| FR-008 | Semantic search over agents, skills, capabilities via pgvector | C.04 |
| FR-009 | A2A agent card generation at `/.well-known/agent-card.json` | C.04 |
| FR-010 | MCP Registry API following `modelcontextprotocol/registry` spec | C.04 |
| FR-011 | Sandboxed execution via k8s Jobs for coding agents | C.05 |
| FR-012 | Sandbox NetworkPolicy restricts egress to LiteLLM + MCP only | C.05 |
| FR-013 | Sandbox results returned via Job completion + PVC read | C.05 |
| FR-014 | GitOps: agent/skill changes flow through git → ArgoCD → cluster | C.06 |
| FR-015 | Gateway resolves agents from registry instead of MLflow | C.04 |
| FR-016 | Deployment heartbeats track agent health per environment | C.04 |
| FR-017 | Capability catalog aggregated from MCP registries + env bindings | C.04 |
| FR-018 | Eval results stored in registry, baselines tracked per agent/skill | C.04 |

### Non-Functional

| ID | Requirement |
|----|-------------|
| NFR-001 | Registry startup < 5s with 50 agents, 100 skills |
| NFR-002 | ConfigMap watch latency < 2s from apply to registry update |
| NFR-003 | Agent card generation < 100ms |
| NFR-004 | Sandbox Job creation < 5s |
| NFR-005 | Sandbox cleanup automatic via TTL (default 1h) |
| NFR-006 | Registry survives restart (pgvector persistence) |
| NFR-007 | All images ARM64 native (no QEMU) |

## Data Flow

```
                    Git (definitions)
                         │
                    ArgoCD (sync)
                         │
                    ConfigMaps (k8s)
                         │
                    Registry (watch + import)
                         │
              ┌──────────┼──────────────┐
              ▼          ▼              ▼
          Gateway    A2A clients    MCP clients
          (resolve   (discover      (discover
           + exec)    agents)        tools)
              │
    ┌─────────┼─────────┬──────────────┐
    ▼         ▼         ▼              ▼
   n8n     direct    sandbox        A2A remote
  runtime   LLM      k8s Job        delegation
              │
              ▼
          LiteLLM → Ollama / cloud LLM
```

## Ontology Extension

Add to `platform.ttl`:

```turtle
:AgentRegistry rdfs:subClassOf :Service .
:Agent rdfs:subClassOf :Component .
:Skill rdfs:subClassOf :Component .
:Capability rdfs:subClassOf :Component .
:EnvironmentBinding rdfs:subClassOf :Component .
:SandboxRuntime rdfs:subClassOf :Service .
```

Add to `platform-instances.ttl`:

```turtle
:agent-registry a :AgentRegistry ;
    rdfs:label "Agent Registry" ;
    :port 8001 ;
    :protocol "http" ;
    :address "genai-agent-registry.genai.svc.cluster.local" ;
    :ingressHost "agent-registry.genai.127.0.0.1.nip.io" ;
    :dependsOn :pgvector .
```

Drift detector catches agents declared in git but not in registry, capabilities required but no MCP server providing them.

## Implementation Plan

### Phase 1: Foundations (agent + skill definitions in git)

1. Convert 3 existing agents to Agent Spec YAML in `agents/{name}/agent.yaml`
2. Convert existing skills to SKILL.md format in `skills/{name}/SKILL.md`
3. Write `envs/agents/local.yaml` environment binding
4. Validate all definitions parse correctly with pyagentspec

### Phase 2: Agent Registry service

5. Scaffold `services/agent-registry/` (FastAPI + pgvector)
6. Implement schema (agents, skills, env bindings, capabilities, deployments)
7. Implement ConfigMap watcher (kubernetes client, watch API)
8. Implement REST API (agents, skills, envs, capabilities)
9. Implement A2A agent card generation
10. Implement semantic search (pgvector embeddings via Ollama)

### Phase 3: Helm + GitOps

11. Create `charts/genai-agents/` (ConfigMaps from agent.yaml + SKILL.md)
12. Create `charts/genai-agent-registry/` (the registry service)
13. Add ArgoCD Application for both charts
14. Verify: git push → ArgoCD sync → ConfigMap → registry import

### Phase 4: Gateway integration

15. Add registry client to agent-gateway
16. Gateway resolves agents from registry (fallback to MLflow during migration)
17. Gateway sends deployment heartbeats to registry
18. Remove MLflow agent/skill sync code

### Phase 5: Sandboxed execution

19. Build `images/agent-sandbox/Dockerfile` (Claude Agent SDK + tools)
20. Implement sandbox manager in gateway (Job creation, status polling, result collection)
21. Add NetworkPolicy template to genai-agents chart
22. Create `sandbox-coder` agent definition
23. Test: submit coding task → sandbox Job → result returned

### Phase 6: Multi-environment

24. Write `envs/agents/oci-prod.yaml` environment binding
25. Add OCI runtime adapter to gateway
26. ArgoCD ApplicationSet for multi-env deployment
27. Test: same agent definition deployed to both local and OCI

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| pyagentspec doesn't map cleanly to current agent model | Phase 1 delay | Build thin adapter layer; don't force 1:1 mapping |
| ConfigMap watch misses updates | Stale agents | Periodic full re-sync (every 60s) as fallback |
| pgvector already at capacity (shared with other services) | Registry slow | Dedicated connection pool; monitor with DataHub |
| Sandbox Jobs not cleaned up | Resource leak | TTL controller + CronJob sweeper as safety net |
| ARM64 image for Claude Agent SDK not available | Sandbox blocked | Build from source; fallback to direct runtime |
| ArgoCD sync too slow for rapid iteration | Dev friction | `task agent-sync` manual override for dev workflow |
| Oracle Agent Spec changes breaking | Schema drift | Pin agentspec_version; adapter layer absorbs changes |

## Dependencies

| Dependency | Status | Required By |
|------------|--------|-------------|
| pgvector (genai namespace) | Running | C.04 |
| ArgoCD (platform namespace) | Running | C.06 |
| LiteLLM MCP registry | Config flag needed | C.04 (MCP registry) |
| Ollama nomic-embed-text | Running | C.04 (embeddings) |
| pyagentspec | Cloned at ~/work/clones/agent-spec | C.01 |
| kubernetes Python client | pip install | C.04 (ConfigMap watch) |
| Claude Agent SDK | pip install | C.05 |

## Open Questions

1. **Skill composition**: Should skills compose (skill A includes skill B), or keep flat?
2. **Agent versioning**: Semver from git tags, or auto-increment on each ConfigMap change?
3. **Sandbox persistence**: Should sandbox workspaces persist across invocations (PVC) or always start fresh (emptyDir)?
4. **Registry HA**: Single replica sufficient for local dev. What's the HA story for cloud?
5. **MCP Registry federation**: Should our registry aggregate from LiteLLM's MCP registry, or replace it?

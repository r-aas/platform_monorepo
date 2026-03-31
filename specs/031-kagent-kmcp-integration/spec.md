<!-- status: planned -->
# 031 — kagent + kmcp Native Integration

## Problem

We have a working agent platform but it's held together with glue:

- **Agents**: Custom YAML spec → Python transpiler → kagent CRDs → Helm chart → ArgoCD. Too many steps. The transpiler is a liability — every kagent schema change breaks it.
- **MCP servers**: 9 individual Helm charts with copy-pasted templates. Adding a server means writing a chart from scratch. No lifecycle management beyond "is the pod running?"
- **Scheduling**: CronJobs that shell out to curl. Fragile, no retry, no observability.

kagent and kmcp solve these problems natively. We should use them as intended.

## Solution

### Phase 1: kagent agents (replace transpiler + CronJobs)

**Delete the transpiler.** Write Agent CRDs directly — they're not complex enough to need code generation. The custom Agent Spec YAML was a prototype; kagent's schema is the production format.

| Current | Target |
|---------|--------|
| `agents/developer/agent.yaml` (custom format) | `agents/developer/agent.yaml` (kagent v1alpha2 CRD) |
| `scripts/agentspec-to-kagent.py` | Deleted |
| `charts/genai-kagent/templates/custom-agents.yaml` (generated) | `charts/genai-kagent/templates/agents.yaml` (hand-written) |
| CronJob → curl → A2A | kagent controller manages scheduling natively |
| n8n chat workflow as runtime | kagent Python ADK as runtime |

**What each agent needs:**

```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: platform-admin
  namespace: genai
spec:
  type: Declarative
  declarative:
    runtime: python
    modelConfig: litellm-config
    systemMessage: |
      You are the platform-admin agent...
    stream: true
    tools:
      - type: McpServer
        mcpServer:
          name: kubernetes-ops
          kind: RemoteMCPServer
          apiGroup: kagent.dev
          toolNames: [kubectl_get, kubectl_describe, kubectl_logs, kubectl_apply]
      - type: McpServer
        mcpServer:
          name: gitlab-ops
          kind: RemoteMCPServer
          apiGroup: kagent.dev
          toolNames: [list_projects, get_pipeline_status]
    memory:
      modelConfig: embedding-config
      ttlDays: 30
    a2aConfig:
      skills:
        - id: kubernetes-ops
          name: Kubernetes Operations
```

**Single ModelConfig for all agents** (they all use LiteLLM → Ollama):

```yaml
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: litellm-config
  namespace: genai
spec:
  provider: OpenAI
  model: glm-4.7-flash
  openAI:
    baseUrl: http://genai-litellm.genai.svc.cluster.local:4000/v1
  apiKeySecret: kagent-litellm
  apiKeySecretKey: api-key
```

**Embedding ModelConfig** (for agent memory):

```yaml
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

### Phase 2: kmcp MCP servers (replace 9 Helm charts)

**Replace 9 charts with 9 MCPServer CRDs.** kmcp controller creates the Deployments, Services, and ConfigMaps.

| Current | Target |
|---------|--------|
| `charts/genai-mcp-kubernetes/` (Chart.yaml, values.yaml, 3 templates) | One MCPServer CRD in `charts/genai-kmcp/templates/servers.yaml` |
| 9 charts × ~5 files each = ~45 files | 9 CRDs in 1 file + values |
| Manual `docker build` + `k3d image import` | kmcp controller pulls images |
| No health tracking beyond pod status | 4-phase status conditions (Accepted → ResolvedRefs → Programmed → Ready) |

**Example MCPServer CRD** (replacing genai-mcp-kubernetes chart):

```yaml
apiVersion: kmcp.io/v1alpha1
kind: MCPServer
metadata:
  name: mcp-kubernetes
  namespace: genai
spec:
  deployment:
    image: ghcr.io/r-aas/mcp-kubernetes:latest
    port: 3000
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 500m
        memory: 512Mi
    env:
      KUBECONFIG: /var/run/secrets/kubernetes.io/serviceaccount/token
    serviceAccount:
      annotations: {}
  transportType: http
  httpTransport:
    targetPort: 3000
    path: /mcp
  timeout: 30s
```

**RemoteMCPServer auto-created** by kmcp controller → kagent agents discover tools automatically.

### Phase 3: Wire it together

```
kmcp controller → manages MCPServer CRDs → creates Deployments + Services
                                          → creates RemoteMCPServer resources
                                                    ↓
kagent controller → reads Agent CRDs → discovers RemoteMCPServer tools
                 → creates agent Deployments (Python ADK)
                 → serves A2A API
                                                    ↓
agentgateway → federates all MCP endpoints → /mcp/all (243 tools)
            → routes A2A requests to agents
```

## Implementation Plan

### Step 1: Install kmcp controller

Add `kmcp` Helm chart to helmfile bootstrap tier or as an ArgoCD-managed chart.

```yaml
# charts/genai-kmcp/Chart.yaml
apiVersion: v2
name: genai-kmcp
dependencies:
  - name: kmcp
    version: "1.0.0"
    repository: "https://kagent-dev.github.io/kmcp/"
```

### Step 2: Convert MCP servers to MCPServer CRDs

For each existing chart in `charts/genai-mcp-*/`:
1. Extract image, port, env, secrets, resources from `values.yaml`
2. Write equivalent MCPServer CRD
3. Add to `charts/genai-kmcp/templates/servers.yaml`
4. Verify kmcp creates Deployment + Service + RemoteMCPServer
5. Delete old chart directory

### Step 3: Rewrite Agent CRDs

For each agent in `agents/*/agent.yaml`:
1. Rewrite in kagent v1alpha2 format directly (no transpiler)
2. Reference `litellm-config` ModelConfig
3. Reference RemoteMCPServer resources by name
4. Include tool names explicitly (required)
5. Configure memory with embedding ModelConfig
6. Add to `charts/genai-kagent/templates/agents.yaml`

### Step 4: Delete old infrastructure

- Delete `scripts/agentspec-to-kagent.py`
- Delete `agents/_shared/` (config now in ModelConfig CRDs)
- Delete `agents/envs/` (environment bindings now in values.yaml)
- Delete 9 `charts/genai-mcp-*` directories
- Delete CronJob manifests (kagent manages scheduling)
- Simplify `taskfiles/agents.yml` (no transpile step)

### Step 5: Verify

```bash
# All MCPServer CRDs should show Ready=True
kubectl get mcpservers -n genai

# All Agent CRDs should show Ready=True
kubectl get agents.kagent.dev -n genai

# All RemoteMCPServers should discover tools
kubectl get remotemcpservers -n genai -o jsonpath='{range .items[*]}{.metadata.name}: {.status.discoveredTools}{"\n"}{end}'

# A2A invocation should work
curl -X POST http://gateway.platform.127.0.0.1.nip.io/api/a2a/genai/platform-admin \
  -H 'Content-Type: application/json' \
  -d '{"message":{"role":"user","parts":[{"text":"what pods are unhealthy?"}]}}'

# MCP federation should still work
curl -X POST http://gateway.platform.127.0.0.1.nip.io/mcp/all \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## What we gain

| Before | After |
|--------|-------|
| 45+ files across 9 MCP charts | 9 CRDs in 1 template file |
| Python transpiler for agent specs | Direct CRD authoring |
| CronJob + curl for scheduling | kagent native scheduling |
| No agent memory persistence | pgvector memory via kagent |
| No tool discovery | Auto-discovery via RemoteMCPServer status |
| Manual image builds for MCP | ghcr.io images + kmcp lifecycle |
| 4 status conditions per MCP server | Built into kmcp |

## Risks

| Risk | Mitigation |
|------|------------|
| kmcp controller not ARM64 | Check image manifest before installing; fall back to manual install |
| kagent Python ADK image size | Pre-pull during `task up`; add to ghcr.io build pipeline |
| RemoteMCPServer auto-creation by kmcp may conflict with existing ones | Delete existing RemoteMCPServers before deploying kmcp-managed ones |
| Agent memory migration | Keep autonomy-schema.sql for pgvector tables; kagent uses its own database |
| agentgateway backend discovery | Verify agentgateway watches both MCPServer and RemoteMCPServer CRDs |

# 029 - Platform Consolidation: Research

## Agent Platforms Evaluated

| Platform | Language | K8s Native | A2A Support | MCP Support | Verdict |
|----------|----------|------------|-------------|-------------|---------|
| **kagent** | Python (AutoGen 0.4) | Yes (CRDs) | Yes | Yes (via tools) | **Selected** -- k8s-native, CRD-based, Memory CRD for state |
| AutoGen 0.4 | Python | No | No | Plugin | kagent wraps this; use kagent instead of raw AutoGen |
| CrewAI | Python | No | No | Plugin | Proprietary-leaning, no k8s primitives |
| LangGraph | Python | No | No | Via LangChain | Heavy framework lock-in, stateful graph model adds complexity |
| Letta (MemGPT) | Python | No | No | No | Memory-focused, not a general agent runtime |
| Semantic Kernel | C#/Python | No | Yes (planned) | Plugin | Microsoft ecosystem lock-in |
| Strands Agents | Python | No | Yes | Yes | AWS-native, no k8s CRDs |
| OpenAI Agents SDK | Python | No | No | Partial | Vendor lock-in |

### kagent Details
- **Repo**: `github.com/kagent-dev/kagent`
- **Architecture**: Go controller + Python agent runtime (AutoGen 0.4 AgentChat)
- **CRDs**: `Agent`, `Tool`, `ModelConfig`, `Memory`, `Team`
- **Key feature**: Agents are k8s resources. `kubectl get agents`. Memory persists across runs via Memory CRD.
- **A2A**: Native support. Agents expose A2A endpoints for inter-agent communication.
- **Concern**: Early project (pre-1.0). API may shift. Mitigated by phased rollout.

## MCP Gateway / Proxy Options

| Project | Language | MCP | A2A | LLM Proxy | K8s Controller | Verdict |
|---------|----------|-----|-----|-----------|----------------|---------|
| **agentgateway** | Rust | Yes | Yes | Yes | Yes (Gateway API) | **Selected** -- complete, CNCF sandbox, production-grade |
| ContextForge Gateway | Go | Yes | No | No | No | MCP-only, less mature |
| MetaMCP | TypeScript | Yes (proxy) | No | No | No | **Selected for namespace scoping** only |
| MS MCP Gateway | C# | Yes | No | No | No | .NET ecosystem, Windows-first |
| LiteLLM MCP | Python | Partial | No | Yes | No | MCP support is experimental add-on |
| mcp-proxy | Python | Yes | No | No | No | Simple stdio-to-SSE bridge only |

### agentgateway Details
- **Repo**: `github.com/agentgateway/agentgateway`
- **CNCF**: Sandbox project (Linux Foundation)
- **Protocols**: MCP (stdio, SSE, Streamable HTTP), A2A, OpenAI-compatible LLM
- **Security**: JWT, API keys, OAuth, CEL policy engine, RBAC, rate limiting
- **Observability**: OpenTelemetry metrics/logs/tracing built in
- **K8s**: Controller with Gateway API CRDs (`AgentGatewayBackend`, `AgentGatewayPolicy`, `AgentGatewayParameters`)
- **Helm**: Chart at `controller/install/helm/` in upstream repo
- **Config**: YAML-based. Each MCP server is a `listener` with transport config and optional auth.
- **ARM64**: Rust binary, should cross-compile. Verify published image architectures.
- **Key advantage**: Single binary replaces MCP proxy + A2A cards + LLM routing. CEL policies replace custom RBAC logic.

### MetaMCP Details
- **Repo**: `github.com/anthropics/metamcp` (community)
- **Purpose**: Namespace-scoped MCP proxy. Presents a filtered subset of tools to each client.
- **Architecture**: TypeScript server that connects to multiple MCP backends, exposes filtered tool lists per "workspace".
- **Use case**: Agent A sees tools {github, filesystem}. Agent B sees tools {postgres, mlflow}. Both connect to same MetaMCP instance with different workspace IDs.
- **Deployment**: Sits between kagent agents and agentgateway. Adds one hop but solves tool explosion problem.

## Registry Options

| Project | Language | Semantic Search | MCP Server Registry | Agent Registry | Skill Registry | Verdict |
|---------|----------|-----------------|---------------------|----------------|----------------|---------|
| **agentregistry** | Go | Yes (pgvector) | Yes | Yes | Yes | **Selected** -- unified catalog |
| MCP Registry (spec) | N/A | No | Yes (spec only) | No | No | Spec, not implementation |
| SKILL.md convention | Markdown | No (file grep) | No | No | Yes | Current approach; doesn't scale |
| Custom pgvector DB | Python | Yes | Partial | Partial | No | Current approach; replacing |

### agentregistry Details
- **Repo**: `github.com/agentregistry-dev/agentregistry`
- **CLI**: `areg` -- import, publish, search, deploy artifacts
- **Web UI**: Built-in catalog browser
- **Storage**: PostgreSQL + pgvector for semantic search over tool/skill descriptions
- **Artifact types**: MCP servers, agents, skills, prompts
- **Import sources**: npm, PyPI, Docker Hub, GitHub repos, URLs
- **Key feature**: `areg import` pulls an MCP server definition and registers it. `areg search "database query"` does semantic search.
- **ARM64**: Go binary. Verify published image or build from source.

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| agentgateway over custom MCP proxy | CNCF-backed, Rust performance, unified MCP+A2A+LLM, CEL policies. Our custom code was reimplementing this poorly. |
| agentregistry over custom pgvector registry | Purpose-built catalog with CLI, web UI, import pipeline. Our custom registry was schema + 3 endpoints. |
| kagent over raw AutoGen/CrewAI | K8s-native CRDs mean agents are first-class cluster resources. `kubectl get agents` > custom Job spawning. |
| MetaMCP for namespace scoping | Solves the project_mcp_namespace_scoping.md plan without custom code. Config-driven workspace filtering. |
| Keep LiteLLM | Already deployed, working, battle-tested. agentgateway has LLM routing but LiteLLM's model aliasing and budget controls are more mature for our use case. |
| Keep n8n for human-in-the-loop | n8n's visual workflow builder is irreplaceable for complex branching and human approval steps. Scheduled automation moves to CronJobs. |
| Phased rollout | Five independent phases. Each has a rollback path. No big-bang migration. |

## ARM64 Compatibility Matrix

| Component | Published ARM64 Image | Build from Source | Notes |
|-----------|-----------------------|-------------------|-------|
| agentgateway | TBD (verify ghcr.io) | Yes (Rust + musl) | Likely available; Rust cross-compile is straightforward |
| agentregistry | TBD (verify ghcr.io) | Yes (Go) | Go cross-compile trivial |
| kagent controller | TBD | Yes (Go) | Go controller |
| kagent agent runtime | TBD | Yes (Python) | Python + AutoGen |
| MetaMCP | TBD | Yes (Node.js) | TypeScript, platform-agnostic |

**Action**: Verify all published images before Phase 1. Build custom ARM64 images as needed and add to `build-images.sh`.

## References

- agentgateway docs: https://agentgateway.dev/docs/
- agentgateway K8s docs: https://agentgateway.dev/docs/kubernetes/latest
- agentregistry docs: https://aregistry.ai/docs/
- kagent docs: https://kagent.dev/ (if available)
- MetaMCP: https://github.com/anthropics/metamcp
- A2A protocol: https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/
- MCP protocol: https://modelcontextprotocol.io/introduction

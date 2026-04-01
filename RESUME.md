# Platform Monorepo — Session Resume

## Session: 2026-04-01 — Supply Chain Hardening + LiteLLM Replacement

### What Was Done

**1. Replace LiteLLM with agentgateway LLM Gateway (P0 — supply chain attack)**
- LiteLLM PyPI compromised March 24, 2026 (TeamPCP campaign, CVE-2026-33634 chain)
- Credential stealer harvested env vars, SSH keys, k8s secrets; created privileged pods
- Replaced with agentgateway (Rust, Linux Foundation) LLM Gateway:
  - New `AgentgatewayBackend` with `spec.ai` pointing at Ollama (192.168.5.2:11434)
  - New `Gateway` + `HTTPRoute` on port 4000 for `/v1/*` traffic
  - Ingress on `litellm.platform.127.0.0.1.nip.io` (backwards-compatible hostname)
  - Also exposed on `gateway.platform.127.0.0.1.nip.io/v1/*`
- Updated all consumers: n8n, agent-gateway, benchmark scripts, n8n-import scripts, env configs
- Deleted `charts/genai-litellm/` and `images/litellm/` entirely
- One fewer Python service, one fewer PostgreSQL database, one fewer supply chain risk

**2. Supply Chain Hardening (P0)**
- **Dockerfile digest pinning**: All 17 Dockerfiles now use `@sha256:` digest-pinned base images
  - python:3.12-slim@sha256:3d5ed973e...
  - node:22-slim@sha256:80fdb3f57c...
  - node:22-alpine@sha256:4d64b49e6c...
- **Package version pinning**: All npm and pip installs pinned to exact versions
  - npm: @modelcontextprotocol/server-gitlab@2025.4.25, mcp-server-kubernetes@1.1.1, etc.
  - pip: mcp[cli]==1.9.4, httpx==0.28.1, mcp-proxy==0.4.0, mlflow-mcp==0.2.0
- **Non-root containers**: All 17 Dockerfiles now have `USER 1001` (or `USER agent`)
- **curl|sh eliminated**: Replaced with `COPY --from=` multi-stage patterns
- **Secrets externalized**: Langfuse crypto (salt, encryptionKey, nextauth) moved from values.yaml to k8s secrets via existingSecret
  - Added langfuse-crypto, langfuse-clickhouse, langfuse-redis secrets to seed-secrets.sh
  - GitLab root password moved to existingSecret pattern

**3. Architecture Review**
- Confirmed: agentregistry = Solo.io → CNCF Sandbox (March 2026), real OSS
- No single OSS system unifies agent+MCP registry+eval — current stack is correct
- Identified triple-overlap: kagent CRDs + agentgateway CRDs + agentregistry + agent-gateway all maintain separate inventories
- agent-gateway should slim to ~600 LOC (sandbox + promotion only)

**4. Cluster State**
- Fixed agentgateway/kagent OutOfSync — CRD timing issue, force-synced
- agentgateway controller + MCP proxy pod running
- kagent synced, controller starting

### Platform State
- **Cluster**: UP — Docker Desktop, k3d "mewtwo", 3 nodes
- **ArgoCD**: 21/23 synced (kagent-dev/kagent-stage still syncing)
- **LiteLLM**: REMOVED — replaced by agentgateway LLM Gateway (Rust)
- **Healthy**: MLflow, n8n, agent-gateway, Langfuse, MinIO, pgvector, agentgateway
- **Supply chain**: All images digest-pinned, all deps version-pinned, non-root containers
- **Policy engine**: 28 policies (18 ISO + 10 OWASP), runtime checks working

### Next Steps
1. **W3: OTEL → Langfuse trace pipeline** — deploy OTEL Collector chart (gRPC→HTTP bridge), enable kagent tracing
2. **Verify LLM Gateway** — test /v1/chat/completions through agentgateway, verify n8n workflows work
3. **W10: Slim agent-gateway to ~600 LOC** — delete agent CRUD, chat, delegation, MCP discovery
4. **task up clean bootstrap** — verify full zero-to-running with new supply chain hardened images
5. **W5: Agent promotion pipeline** — genai-dev/stage namespaces + eval gates

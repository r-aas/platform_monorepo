# Platform Monorepo — Session Resume

## Session: 2026-04-01 — Supply Chain Hardening + LLM Gateway Verification

### What Was Done

**1. Supply Chain Hardening + LiteLLM Replacement (committed: e9012c1)**
- Full 80-file commit: agentgateway LLM Gateway, digest-pinned Dockerfiles, version-pinned deps, non-root containers, externalized secrets
- See previous session for full details

**2. Docker Desktop Host IP Fix (committed: baf547b)**
- Discovered `192.168.5.2` (Colima) was stale — Docker Desktop uses `192.168.65.254` (`host.k3d.internal`)
- Updated 24 files across charts, scripts, workflows, docs
- Ollama requires `OLLAMA_HOST=0.0.0.0:11434` (not localhost) for k3d access
- Updated k3d-networking skill, CLAUDE.md, memory

**3. LLM Gateway Verified End-to-End**
- agentgateway LLM Gateway on port 4000 → Ollama
- Both ingress paths working:
  - `litellm.platform.127.0.0.1.nip.io/v1/chat/completions` (backwards-compatible)
  - `gateway.platform.127.0.0.1.nip.io/v1/chat/completions` (new canonical)
- ArgoCD fully synced: Gateway, HTTPRoute, Ingress, AgentgatewayBackend all healthy

**4. Missing Secrets Created**
- `gitlab-root-password` (platform ns) — GitLab crashed without it after existingSecret change
- `langfuse-crypto`, `langfuse-clickhouse`, `langfuse-redis` (genai ns) — proactively created before ArgoCD syncs Langfuse chart
- Added all to `~/work/envs/secrets.env` for seed-secrets.sh

**5. AgentOps Dashboard Built**
- ReactFlow single-page app at `/tmp/agentops-dashboard/bundle.html` (439KB)
- 4 tabs: Overview (7 decision graphs), Promote (pipeline), Runtime (swim lanes), Agent Map

### Platform State
- **Cluster**: UP — Docker Desktop, k3d "mewtwo", 3 nodes
- **ArgoCD**: 22/23 synced (kagent-dev/kagent-stage still degraded — known)
- **LLM Gateway**: VERIFIED — agentgateway → Ollama, both ingress paths working
- **LiteLLM**: REMOVED
- **Supply chain**: All images digest-pinned, all deps version-pinned, non-root containers
- **Host IP**: 192.168.65.254 (Docker Desktop), all references updated
- **Ollama**: Must have `OLLAMA_HOST=0.0.0.0:11434` set

### Next Steps
1. **W3: OTEL → Langfuse trace pipeline** — deploy OTEL Collector chart, enable kagent tracing
2. **task up clean bootstrap test** — verify full zero-to-running with hardened images
3. **W10: Slim agent-gateway to ~500 LOC** — delete everything OSS components cover
4. **W4: Delete 5 redundant n8n workflows**
5. **W5: Agent promotion pipeline** — genai-dev/stage/prod namespaces + eval gates

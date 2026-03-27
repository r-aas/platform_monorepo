# Platform Monorepo — Session Resume

## Session: 2026-03-27 — Unified Agent Gateway (Plan Complete)

### What Was Built

**Unified Agent Gateway** — Merged agent-registry into agent-gateway as single service.
- PostgreSQL + pgvector replaces MLflow for agent/skill/environment CRUD
- MCP proxy aggregates 87 tools from 3 k8s backends (kubernetes: 22, gitlab: 44, n8n: 21)
- SSE response parsing, MCP session management, per-server auth tokens
- Tool name prefixing: `{server}.{tool}` (e.g., `kubernetes.kubectl_get`)
- Namespace-scoped MCP endpoints: `/mcp/proxy/ns/{namespace}`, `/mcp/proxy/server/{server}`
- 12 MCP management tools via gateway-mcp JSON-RPC
- Deleted `genai-agent-registry` chart + k8s deployment
- Skills registry converted to async (fixed `RuntimeError: no event loop in thread`)

**agent-platform v0.2.0** — Slimmed to models-only library (AgentSpec, SkillManifest, EnvironmentBinding). Deleted registry/, adapters/, sandbox/ subpackages. 30 deps removed.

**Migration script** — `scripts/migrate-mlflow-to-pg.py` (idempotent, reads MLflow → upserts via REST API)

### Current State

| Component | Status | Details |
|-----------|--------|---------|
| agent-gateway | Healthy | 3 agents, 0 skills, 1 env, 4 MCP servers |
| MCP proxy | 87 tools | platform: 66, orchestration: 21, data: 0 (datahub down) |
| datahub MCP | CrashLoopBackOff | Pre-existing issue |
| Langfuse | Deployed | Needs UI sign-up + API key wiring to LiteLLM |
| MLflow → PG migration | Not run | Script ready, needs verification |

### Pushed

- `platform_monorepo` → GitLab (`0a22832`)
- `agent-platform` → GitHub (`6e76d00`, v0.2.0)
- `genai-mlops` → GitLab (`2a1e608`, 5 commits)

### Known Issues

1. **genai-mcp-datahub CrashLoopBackOff**: DataHub MCP server issue (pre-existing)
2. **Langfuse keys**: Need UI sign-up → create project → set LANGFUSE_PUBLIC_KEY/SECRET_KEY in LiteLLM
3. **kagent MCP tools**: RemoteMCPServer returns `None` for tools → Pydantic crash

### Next Commands

```bash
# Run MLflow → PG migration
AGW_URL=http://agent-gateway.genai.127.0.0.1.nip.io \
MLFLOW_TRACKING_URI=http://mlflow.genai.127.0.0.1.nip.io \
python scripts/migrate-mlflow-to-pg.py

# Complete Langfuse setup
open http://langfuse.genai.127.0.0.1.nip.io

# Verify n8n chat through new MCP proxy
# chat-v1 workflow with mcp_tools: 'all' → agent-gateway proxy

# Fix datahub MCP
kubectl logs -n genai deployment/genai-mcp-datahub --tail=20
```

# Platform Monorepo — Session Resume

## Session: 2026-03-27 — AgenticOps Reference System + Benchmark Matrix

### Built

**Security Audit** — All hardcoded secrets removed, gitleaks clean (tree + 186 commits)
- GitLab PATs, DataHub JWTs, MetaMCP default password, personal email
- `.gitleaks.toml` allowlist for n8n encryption key name
- Git remote URLs stripped of embedded PATs

**Benchmark Pipeline** — 3-model matrix complete (246 cases)
- qwen2.5:7b: 78% (86/109) ← best performer
- mistral:7b-instruct: 69% (67/97)
- qwen2.5:14b: 55% (22/40) — fewer cases due to earlier process kill
- Fixed json.loads AttributeError bug (non-dict JSON responses)
- All logged to MLflow `__benchmarks` experiment

**Langfuse (LLM Observability)** — Deployed via ArgoCD
- Chart: `genai-langfuse`, Langfuse v3.161.0
- External pgvector (DB: langfuse) + External MinIO (bucket: langfuse)
- ClickHouse + Valkey subcharts
- LiteLLM wired: `success_callback: ["langfuse"]`
- URL: http://langfuse.genai.127.0.0.1.nip.io

**kagent (K8s Agent Platform, CNCF Sandbox)** — Deployed via ArgoCD
- Chart: `genai-kagent`, kagent v0.8.0
- 5 agents: mlops, developer, platform-admin (custom) + k8s, helm (built-in)
- ModelConfig: OpenAI → LiteLLM → qwen2.5:14b
- 5 RemoteMCPServers registered
- URL: http://kagent.genai.127.0.0.1.nip.io

**Agent Registry** — Chart + Dockerfile created
- Chart: `genai-agent-registry`, agent-platform FastAPI service
- URL: http://agent-registry.genai.127.0.0.1.nip.io (CrashLoopBackOff — needs image build)

**agent-platform** — Public GitHub repo: https://github.com/r-aas/agent-platform
- README with quickstart, agent spec format, SKILL.md, environment bindings

### Known Issues

1. **genai-agent-registry CrashLoopBackOff**: No image built yet — needs `agent-platform` code packaged
2. **genai-mcp-datahub CrashLoopBackOff**: DataHub MCP server issue
3. **kagent MCP tools**: RemoteMCPServer returns `None` for tools → Pydantic crash. Custom agents deployed WITHOUT tools
4. **gemma3:12b benchmark**: Never completed (process killed). Model pulled and ready.
5. **Langfuse keys**: Need UI sign-up → create project → set LANGFUSE_PUBLIC_KEY/SECRET_KEY in LiteLLM

### Next Commands

```bash
# Run gemma3:12b benchmark [local]
cd ~/work/repos/genai-mlops && uv run python scripts/benchmark.py --type agent --runtime direct --matrix --model gemma3:12b --log-mlflow

# Build + deploy agent-registry [local]
cd ~/work/repos/platform_monorepo && bash scripts/build-images.sh agent-registry
k3d image import agent-registry:latest -c mewtwo

# Complete Langfuse setup
open http://langfuse.genai.127.0.0.1.nip.io  # sign up, create project, get API keys

# Remaining work
# - ConfigMap watcher for real-time agent sync
# - Sandbox runtime (k8s Jobs for Claude Code SDK / OpenHands)
# - Promotion workflow (shadow → canary → primary)
```

# Platform Monorepo — Session Resume

## Session: 2026-04-01 — Bootstrap Test + Benchmarks + Tailscale + Autoresearch

### What Was Done

**1. Full Bootstrap from Zero**
- `task up` end-to-end: 106+ pods across 6 namespaces
- Fixed: seed-secrets for dev/stage, CRD installation, database creation, custom image builds
- LiteLLM base image → `main-stable` (upstream removed `1.82.6.dev1` tag)

**2. Multi-Model Benchmarks**
- glm-4.7-flash vs qwen3:32b: 5x faster (8.4s vs 42.0s avg, 39 vs 8 tok/s)

**3. Tailscale Remote Access**
- lan-ingress Helm chart with Tailscale IP, `task urls-tailscale`, `task lan-ingress-update`

**4. Autoresearch: Ollama Throughput Optimization**
- 13 experiments: 50.5 → 63.2 tok/s (+25.1%) on M4 Max with glm-4.7-flash
- Winning config: `OLLAMA_FLASH_ATTENTION=1`, `num_ctx=1024`, `num_batch=1024`
- Key insight: M4 Max memory bandwidth is the wall (~66 tok/s ceiling)

**5. Applied Autoresearch Insights**
- `Taskfile.yml`: `ensure-ollama` now sets `OLLAMA_MAX_LOADED_MODELS=1`, creates tuned Modelfile with `num_ctx=1024 num_batch=1024`
- `envs/global.env`: added `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=4`
- `scripts/preflight.sh`: checks flash attention is enabled
- `apple-silicon-dev` skill: added Ollama Inference Tuning section with all findings
- `~/work/CLAUDE.md`: added AUTORESEARCH section documenting the convention

### Platform State
- **106+ pods** across 6 namespaces, all healthy
- **Tailscale**: remote access working via lan-ingress
- **Experiment branch**: `autoresearch/ollama-throughput-20260331` (13 runs, can be deleted)

### Next Steps
1. **Commit + push** the apply-insights changes
2. **Bootstrap hardening** — init-db jobs in kagent/agentregistry charts, CRD install in bootstrap script
3. **Unified Agent Gateway** — plan at `~/.claude/plans/polymorphic-watching-tarjan.md`

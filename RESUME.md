# Platform Monorepo — Session Resume

## Session: 2026-03-28 (continued) — Infrastructure Hardening & DataOps

### What Was Built / Fixed

**DataHub Ingestion (Fixed)**
- Recreated 3 PostgreSQL ingestion sources with JSON recipes (YAML recipes caused "Invalid recipe json" on execution)
- Sources: postgres-n8n, postgres-mlflow, postgres-langfuse — all triggered and RUNNING
- Updated `scripts/datahub-ingest.sh` to use `python3 -c json.dumps()` for proper JSON recipe generation
- Sources run every 6 hours via DataHub managed ingestion

**Consolidated Secrets Management**
- `scripts/seed-secrets.sh` — single script creates all k8s secrets from `~/work/envs/secrets.env`
- Auto-generates secrets.env with defaults if missing
- Idempotent (skips existing, `--force` to recreate)
- Covers: PostgreSQL (n8n, mlflow, plane), n8n encryption, MLflow flask, MinIO, LiteLLM, GitLab PAT, Plane API, Langfuse, DataHub MySQL, n8n API

**Dashboard k3d Mode Fixes**
- Created `_n8n_origin()` helper — replaced 10+ hardcoded `localhost:5678` references
- Rewrote `_fetch_agents_from_registry()` — queries agent-gateway `/agents` endpoint (not MLflow)
- Langfuse traces now use real API keys from k8s secret

**Plane↔GitLab Bidirectional Sync**
- `n8n-data/workflows/plane-to-gitlab.json` — cron-based polling every 5 min
- Anti-loop: filters out GitLab-originated issues, tracks `external_source=gitlab`
- State mapping: Plane state IDs → GitLab labels + open/close

**Benchmark Framework**
- `task benchmark-smoke` — quick 1-agent, 3-case smoke test
- `task benchmark-agents` — full agent benchmarks with k3d env vars
- `--limit` flag on `agent-benchmark.py` for limiting test cases
- Benchmark runs and logs to MLflow (run f784668a). Judge eval fails due to LLM timeout on qwen2.5:14b — model quality issue, not infra.

**Agent Gateway Image Rebuild**
- Rebuilt and imported into k3d — picks up all store/ and registry code changes
- Health: 4 agents, 10 skills, 1 environment, 5 MCP servers

**A2A Agent Cards**
- `/.well-known/agent-card.json` returns 4 agent cards with skills
- Per-agent cards work: `/.well-known/agent-card/{name}.json`
- Protocol version 0.2.5

**Spec 015: DataOps**
- Spec drafted at `specs/015-dataops/spec.md`
- Phase 1 (ingestion) complete, Phases 2-4 planned (lineage, quality, domain tags)

**n8n Credentials**
- Only 2 credentials exist (Ollama Local, LiteLLM) — no duplicates to clean

### Verified Working

- DataHub: 3 ingestion sources created, all RUNNING ✓
- DataHub: system-update Job completed, app Synced+Healthy ✓
- Agent gateway: rebuilt, deployed, healthy (4 agents, 10 skills, 5 MCP servers) ✓
- A2A cards: 4 agents with skills at /.well-known/agent-card.json ✓
- Benchmark: framework executes end-to-end, logs to MLflow ✓
- n8n: 15 workflows (12 active), 2 credentials (no dupes) ✓
- ArgoCD: 24/24 apps Synced and Healthy ✓

**Autonomous Continuity System**
- `/continue` command reads RESUME.md + BACKLOG.md, health-checks cluster, picks next task, executes
- `BACKLOG.md` — persistent prioritized task queue (P0-P3)
- Session-start hook detects RESUME.md, suggests `/continue`
- Memory entry saved for cross-session awareness

**Sandbox Fix — Git Clone Auth**
- `sandbox_default_git_host` changed from nip.io to `gitlab-ce.platform.svc.cluster.local`
- Clone script reads PAT from `/git-creds/token` and injects into URL
- `gitlab-pat` secret updated with both `token` and `.git-credentials` keys (internal URL)
- `seed-secrets.sh` updated to create secret with both keys
- Verified: sandbox clone + complete works end-to-end

### Known Issues

1. **Benchmark judge fails** — eval webhook returns empty body for judge calls. LLM (qwen2.5:14b) times out or returns non-JSON. Need faster model or simpler judge prompt.
2. **n8n credentials API** — v1.123.21 returns 405 on GET /api/v1/credentials (not supported in public API)
3. **Plane CE no webhooks** — stable image lacks webhook management API; using polling-based sync
4. **qwen2.5:14b responds in Thai/Chinese** — LLM hallucination with many tools

### Commits This Session (platform_monorepo)

- `aaebbc9` feat: add benchmark-agents and benchmark-smoke tasks to Taskfile
- `c8f4b7c` feat: add Plane and GitLab env vars to n8n chart
- `ca6d9f5` feat: DataHub ingestion sources for n8n, MLflow, Langfuse PostgreSQL
- `3e9d2cc` feat: consolidated secrets management with seed-secrets.sh

### Commits This Session (genai-mlops)

- `095895a` feat: add --limit flag to agent-benchmark.py for smoke tests
- `6bb8b74` feat: add Plane→GitLab bidirectional sync workflow
- `7bd39b5` fix: dashboard k3d mode — use ingress URLs and agent-gateway for data
- `04c8acd` feat: eval CI stage, dashboard k3d config, import script cleanup

### Platform State

| Component | Count | Status |
|-----------|-------|--------|
| ArgoCD apps | 24 | All Synced/Healthy |
| Agents | 4 | mlops, developer, platform-admin, mlops-shadow |
| Skills | 10 | Across all agents |
| MCP servers | 5 | kubernetes, gitlab, n8n, datahub, plane |
| n8n workflows | 15 | 12 active, 3 inactive |
| n8n credentials | 2 | Ollama Local, LiteLLM |
| DataHub sources | 4 | 3 postgres + GC (all running) |

**/continue session (same day)**

**Benchmark Judge Fixed**
- Replaced n8n eval webhook judge with direct LiteLLM call (qwen2.5:7b)
- 66.7% pass rate (2/3 cases), up from 0%. Judge returns clean JSON scores.
- Added `LITELLM_URL` and `LITELLM_API_KEY` to Taskfile benchmark tasks

**DataOps Phase 2: Lineage**
- `scripts/datahub-lineage.py` — emits 5 cross-service lineage edges via GMS REST API
- n8n→MLflow, n8n→Langfuse, MLflow→Langfuse, MLflow→n8n
- `task datahub-lineage` added to Taskfile

**DataOps Phase 3: Quality Checks**
- `scripts/datahub-quality.py` — validates data directly against PostgreSQL pods
- 5/5 checks pass: 15 workflows, 2814 executions, 5 experiments, 464 runs, 48 models
- DataHub assertion upsert works; result reporting has eventual consistency issue (non-blocking)
- `task datahub-quality` added to Taskfile

### Next

1. **DataOps Phase 4** — domain tags on datasets (agent, eval, trace, workflow)
2. **Dashboard topology** — wire DataHub lineage into ReactFlow graph
3. **n8n credential rotation** — move hardcoded tokens from values.yaml to existingSecret
4. **Benchmark tuning** — tune prompts or test cases for >70% baseline
5. **Spec 015 ship** — all phases done, mark shipped

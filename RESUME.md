# Platform Monorepo — Session Resume

## Session: 2026-03-28 — Full Roadmap Sweep: Plane + Canary + Eval + Benchmarks

### What Was Built

**Canary Traffic Routing**
- `registry.get_agent()` checks for `{name}-canary` variant at canary stage
- Routes `canary_weight%` of traffic to canary version transparently
- `X-Agent-Variant` and `X-Agent-Stage` response headers for observability
- `store/agents.py`: `get_canary_variant()` DB query
- Promotion workflow: `shadow → canary → primary` with weight control

**Agent Eval Framework — Shadow + Live Benchmarks**
- Shadow execution dispatch: chat router fires `{agent}-shadow` variant in parallel (fire-and-forget)
- Shadow results persisted to `eval_runs` table for later comparison
- `benchmark/runner.py`: live gateway mode — sends eval cases via HTTP, measures real latency
- `benchmark/results.py`: persists `EvalRunRow` to PostgreSQL alongside MLflow
- `store/deployments.py`: `insert_eval_run()` for DB persistence
- Skills benchmark endpoint now uses `gateway_url` for live mode (vs stub)

**Runtime Benchmarking — POST /factory/benchmark/compare**
- Same task + same spec + different runtime = comparable metrics
- Creates ephemeral agent variants (`{agent}-bench-{runtime}`) per runtime
- Runs eval cases concurrently across runtimes
- Returns comparison table sorted by pass_rate/latency
- 5 eval datasets across 3 skills: kubernetes-ops, mlflow-tracking, n8n-workflow-ops

**Plane MCP Server — Helm Chart (ArgoCD-managed)**
- FastMCP server at `images/mcp-plane/` wrapping Plane CE REST API
- 13 tools: list_projects, get_project, list_states, list_labels, create_label, list_issues, get_issue, create_issue, update_issue, list_comments, add_comment, list_cycles, add_issue_to_cycle
- Helm chart at `charts/genai-mcp-plane/` — auto-discovered by ArgoCD ApplicationSet
- Uses `existingSecret: plane-api-token` (never secrets in values.yaml)
- Internal API URL: `http://genai-plane-api.genai.svc.cluster.local:8000`

**Claude Code Credential Refresh Hook**
- SessionStart hook wired in `~/.claude/settings.json` → runs `scripts/refresh-claude-credentials.sh`
- Syncs OAuth token from current session to k8s `claude-credentials` secret at every session start
- launchd plist runs every 30min for background refresh

**Claude Code Plugin Taskfile**
- `taskfiles/claude.yml`: install, list, sync, uninstall, catalog, diff
- Workaround for `claude plugin install` CLI resolver bug (copies from marketplace → cache)

**Plane CE — Fully Operational with File Uploads** (earlier this session)
- Project "Platform Monorepo" (PLAT) created in workspace `r-aas`
- MinIO fix: `USE_MINIO=1`, browser-reachable endpoint, ingress path
- Admin: `r@appliedaisystems.com` / `Plane-k3d-Dev!2026`

**Previous Sessions** (still deployed):
- Unified Agent Gateway: all 4 phases complete (PG+pgvector, MCP proxy, Helm, cleanup)
- n8n: 13 workflows imported, 10 active
- Claude Code Agent Runtime: Docker image, OAuth flow, CronJob scheduler
- Sandbox: pre-warmed pool, PVC, artifacts

### Verified Working

- Canary routing: `X-Agent-Variant`/`X-Agent-Stage` headers on chat responses ✓
- Shadow dispatch: `asyncio.create_task(_run_shadow(...))` fires without blocking ✓
- Factory health shows 5 eval datasets across 3 skills ✓
- Helm chart `genai-mcp-plane` deployed, pod Running ✓
- Credential refresh hook syncs token to k8s on session start ✓
- Gateway health: 3 agents, 1 environment, 5 MCP servers ✓
- All chat/schedule/sandbox/factory endpoints working ✓
- GitLab→Plane webhook: push event creates issue in Plane ✓
- Both GitLab repos (platform_monorepo, genai-mlops) have active webhooks ✓

### Known Issues

1. **Plane cover image upload** — chart deploys unused local MinIO pod (harmless)
2. **ArgoCD OutOfSync** — `genai-plane` app needs resync after Helm values push
3. **Token refresh rate limiting** — Anthropic OAuth endpoint rate limits launchd job
4. **qwen2.5:14b responds in Thai/Chinese** — LLM hallucination with many tools
5. **openAiApi credential broken in n8n** — LangChain sub-nodes can't use openAiApi

### Key Technical Details

**Canary routing convention:**
- Primary agent: `mlops` (promotion_stage=primary)
- Canary variant: `mlops-canary` (promotion_stage=canary, canary_weight=10)
- Shadow variant: `mlops-shadow` (promotion_stage=shadow, runs in parallel)
- `get_agent("mlops")` checks for canary, routes randomly by weight

**Runtime comparison flow:**
```
POST /factory/benchmark/compare
  → loads eval dataset from skills/eval/{skill}/{task}.json
  → creates ephemeral agents: {agent}-bench-n8n, {agent}-bench-http, etc.
  → runs cases concurrently via gateway
  → returns comparison table: pass_rate, avg_latency per runtime
```

**Plane-GitLab Webhook Integration**
- Enabled `allow_local_requests_from_web_hooks_and_services` in GitLab CE admin settings
- Created webhooks on both GitLab repos (platform_monorepo ID=2, genai-mlops ID=1)
- n8n workflow `gitlab-to-plane-v1` receives push/issue/MR/comment events
- Routes events to Plane CE REST API — creates issues with mapped states and priorities
- `PLANE_API_TOKEN` env var set on n8n deployment
- Webhook token: `gitlab-plane-webhook-secret`

**Commits this session:**
- `932cab2` feat: Helm chart for mcp-plane + credential refresh hook + plugin taskfile
- `1ef256a` feat: canary traffic routing with weighted random selection
- `ce5c25d` feat: agent eval framework — live benchmarks, shadow execution, DB persistence
- `2f5c2bb` feat: runtime benchmarking — POST /factory/benchmark/compare
- `de3b34d` docs: update RESUME.md — full roadmap sweep complete
- `d42b301` fix: add Plane to MCP seed, factory health reports real tool count (107)
- `391a048` feat: gitlab-to-plane webhook workflow (genai-mlops repo)

### Next

1. **Dashboard rework** — observatory should query k8s API directly (predates k3d-only architecture)
2. **Plane-GitLab bidirectional sync** — currently one-way (GitLab→Plane); add Plane→GitLab for issue close/update
3. **n8n credential cleanup** — 22+ duplicate Ollama credentials from repeated imports

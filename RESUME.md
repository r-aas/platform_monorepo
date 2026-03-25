# Platform Monorepo — Session Resume

## Session: 2026-03-24 — Bootstrap Reliability + Benchmarkable Agents

### Built
- `task up` works zero-to-healthy in one command (19/19 smoke)
- `task down` → `task up` verified end-to-end
- `task stop` → `task start` verified (19/19 smoke)
- Session continuity: multi-turn conversations with recall
- Custom `mcp-kubernetes` Docker image (pre-installed npm package)
- `sync-if-needed` skips helmfile when ArgoCD already deployed
- Docker-compose GitLab fully removed — k8s only

### Key Architecture Changes
- `cluster-up` split into `cluster-create` (idempotent) + `cluster-configure` (always runs)
- `cluster-configure`: fix-node-dns → CoreDNS restart → fix-local-path
- CoreDNS restart after DNS fix (root cause of all DNS cascade failures)
- `ensure-colima` adds FallbackDNS=8.8.8.8 to Colima VM systemd-resolved
- `sync-if-needed` checks argocd-server deploy existence (not app sync status)
- `wait-healthy` timeout is non-fatal (exit 0)
- GitLab CE runs as StatefulSet in k3d (no docker-compose)
- Session append uses native n8n HTTP Request nodes (Code node sandbox blocks ALL outbound HTTP)

### Critical Gotchas
- **n8n task runner sandbox blocks ALL outbound HTTP from Code nodes.** fetch, require('http'), axios, $helpers.httpRequest — all fail silently. Use native HTTP Request nodes.
- **CoreDNS must be restarted after DNS fix.** Adding 8.8.8.8 to node resolv.conf is not enough — CoreDNS caches the old upstream config.
- **ArgoCD app sync status is "Unknown" during startup.** Don't check app sync to decide whether to run helmfile — check if argocd-server deploy exists.

### Benchmarkable Agents (added late in session)
- 3 agents with real system prompts: mlops, developer, platform-admin
- 12 prompts seeded into MLflow (3 agents × 1 SYSTEM + 3 TASK each)
- 45 benchmark test cases across 9 files (data/benchmarks/*.json)
- Native agent-eval workflow at `/webhook/agent-eval` — no standalone scripts
- LLM-as-judge scoring (relevance, helpfulness) with structured JSON output
- Available models: qwen2.5:14b, qwen2.5:7b, mistral:7b-instruct

### Next Steps
- [local] Migrate prompt-eval-v1 from axios to native HTTP Request nodes (broken in k3d sandbox)
- [local] Upload benchmark test cases as MLflow datasets (via /webhook/datasets)
- [local] Model matrix comparison via agent-eval (same test cases, different models)
- [local] Langfuse trace logging (needs HTTP Request nodes in Trace Logger)
- [local] Evolve genai-mlops-workflows skill with sandbox/session learnings

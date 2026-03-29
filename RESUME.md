# Platform Monorepo — Session Resume

## Session: 2026-03-29 — Single-Command Lifecycle + Post-Restart Recovery

### What Was Built / Fixed

**Single-Command Lifecycle (verified working)**
- `task stop` — stops k3d cluster (~21s), preserves all state
- `task start` — full resume: colima → ollama → k3d start → DNS fix → local-path fix → secrets → image import → wait-healthy → smoke → urls (~7 min)
- `task up` — full bootstrap from scratch (unchanged)
- `task down` — destroy cluster (unchanged)

**Post-Restart Platform Recovery**
- Root cause: DNS failure inside k3d nodes (192.168.5.2 unreachable after restart)
- Fix: `"dns": ["8.8.8.8", "8.8.4.4"]` in Docker daemon.json inside Colima VM
- Fix: k3d agent-1 node password hash mismatch — must use `k3d cluster stop/start`, never raw `docker restart`
- Fix: n8n encryption key secret renamed by chart upgrade — created missing secret
- Fix: n8n postgres password drift — added `postgresPassword: n8n` to chart values (prevents Bitnami random generation)
- Fix: Local images lost from k3d nodes — `--import-only` flag re-imports without rebuilding
- Fix: smoke test n8n→LiteLLM auth header quoting bug

**Autonomous Agent Infrastructure (committed as 2c62293)**
- `agents/*/agent.yaml` — autonomy blocks (schedule, signals, memory, collaborators, guardrails)
- `scripts/signal-collector.py` — polls k8s, ArgoCD, service health
- `scripts/agent-autonomy-schema.sql` — pgvector tables (fixed partial index NOW() bug)
- `taskfiles/agents.yml` — agent management tasks

**Cold-Start Resilience Scripts**
- `scripts/ensure-colima.sh` — Docker daemon DNS config in both start paths
- `scripts/ensure-secrets.sh` — creates missing secrets + syncs n8n postgres password
- `scripts/build-images.sh` — `--import-only` flag, added mcp-plane + open-ontologies

### Verified Working (after stop/start cycle)

- All 3 k3d nodes: Ready
- 57 pods running (+ 3 Completed jobs)
- Smoke: 22 passed, 0 failures, 2 warnings
- n8n: healthy, postgres password in sync
- MLflow: healthy
- Agent gateway: healthy (4 agents, 10 skills, 5 MCP servers)
- LiteLLM: healthy, n8n can reach it
- Ollama: running with OLLAMA_NUM_PARALLEL=4, OLLAMA_FLASH_ATTENTION=1

### Known Issues

1. **k3d agent-1 fragility** — node password hash mismatch after `docker restart`. Must use `k3d cluster stop/start`.
2. **lan-ingress ArgoCD app** — OutOfSync/Missing (cosmetic, no impact)
3. **agent-gateway e2e smoke** — requires n8n workflows imported + 60s Ollama inference timeout. Not a startup health issue.
4. **Benchmark full suite** — general cases need tool-calling, not chat-only (16.7% pass rate)

### Commits This Session (platform_monorepo)

- `8c38e9b` feat: ontology update + Agent Spec → kagent transpiler
- `b4fe105` chore: mark dashboard topology + spec 015 complete
- `2c62293` feat: autonomous agent infrastructure + cold-start resilience
- `8efe3be` fix: n8n postgres password drift (postgresPassword in chart values)
- (uncommitted) fix: smoke test LiteLLM auth header quoting

### Platform State

| Component | Count | Status |
|-----------|-------|--------|
| k3d nodes | 3 | All Ready |
| Pods | 57 | All Running |
| ArgoCD apps | 24/25 | Healthy (lan-ingress cosmetic) |
| Agents | 4 | mlops, developer, platform-admin, mlops-shadow |
| Skills | 10 | Across all agents |
| MCP servers | 5 | kubernetes, gitlab, n8n, datahub, plane |

### Next

1. **Agent Gateway merge** — execute plan at `~/.claude/plans/polymorphic-watching-tarjan.md`
2. **Signal-to-task router** — n8n workflow or gateway endpoint
3. **Memory API** — agent-gateway endpoints for read/write agent_memory with embeddings
4. **Autonomous loop wiring** — signal collector → task router → agent invocation → verification

# Platform Backlog

Persistent task queue for autonomous Claude Code sessions. Ordered by priority.
Tasks move to RESUME.md "completed" section when done.

## Format

```
- [ ] P{0-3} {task} — {one-line context}
```

P0 = blocking/broken, P1 = high value, P2 = planned, P3 = nice-to-have

## Active

- [x] P1 Activate autonomous loop — runner on :7777, claude-autonomous workflow active (4h cron), MLflow logging (2026-03-29)
- [x] P2 Benchmark tuning — smoke 100% (3/3), glm-4.7-flash judge, scoring guide, relaxed criteria (2026-03-29)
- [x] P2 DataOps Phase 4: domain tags — 5 domains, 22 datasets tagged (agent, eval, trace, workflow, research) (2026-03-29)
- [ ] P2 Dashboard topology — wire DataHub lineage into ReactFlow graph
- [x] P2 n8n credential rotation — LITELLM_API_KEY, PLANE_API_TOKEN, GITLAB_PAT moved to n8n-env-secrets; encryption key + pg password via existingSecret (2026-03-29)
- [x] P2 Benchmark baseline — smoke 100%, avg score 0.88, MLflow run f05eaa5a (2026-03-29)
- [ ] P3 Spec 015 ship — finish all phases, mark shipped

## Completed (recent)

- [x] yt-pipeline end-to-end — 50 videos, 50 transcripts, LLM analysis with glm-4.7-flash, pgvector storage (2026-03-29)
- [x] glm-4.7-flash pulled + LiteLLM registered — 19GB model, reasoning mode, 4000 max_tokens for analysis (2026-03-29)
- [x] LAN access to platform services — lan-ingress chart, 15 services on 192.0.0.2.nip.io, task urls-lan (2026-03-29)
- [x] Export YouTube cookies — cookies.txt exported, yt-ingest verified with Watch Later access (2026-03-29)
- [x] YouTube ETL pipeline — yt-ingest service, n8n workflow, pgvector schema, DataHub governance (2026-03-28)
- [x] Agent Runner generalized — Claude + OpenClaw + generic CLI runtimes, MCP config, skills support (2026-03-28)
- [x] Default model → glm-4.7-flash — global.env, LiteLLM config, gpt-4o alias updated (2026-03-28)
- [x] Claude Runner + n8n autonomous orchestrator — headless Claude CLI sessions triggered by n8n cron (2026-03-28)
- [x] DataOps Phase 3: quality checks — 5/5 pass (workflows, executions, experiments, runs, models) (2026-03-28)
- [x] DataOps Phase 2: lineage — 5 cross-service edges emitted to DataHub (2026-03-28)
- [x] Fix benchmark judge — direct LLM judge via LiteLLM, 66.7% pass rate (2026-03-28)
- [x] Sandbox git clone fix — internal URL + PAT token injection (2026-03-28)
- [x] Autonomous /continue command + BACKLOG.md system (2026-03-28)
- [x] Fix DataHub OutOfSync — self-resolved (2026-03-28)
- [x] n8n credential cleanup — only 2 creds, no dupes (2026-03-28)
- [x] DataHub ingestion sources — JSON recipes, 3 sources running (2026-03-28)
- [x] Agent-gateway image rebuild — 4 agents, 10 skills, 5 MCP (2026-03-28)
- [x] A2A agent cards — 4 cards at /.well-known/agent-card.json (2026-03-28)
- [x] Spec 015 DataOps drafted — Phase 1 complete (2026-03-28)
- [x] Consolidated secrets management — seed-secrets.sh (2026-03-28)
- [x] Dashboard k3d mode fixes — _n8n_origin() helper (2026-03-28)
- [x] Plane↔GitLab bidirectional sync — polling-based (2026-03-28)
- [x] Benchmark framework — smoke + full tasks in Taskfile (2026-03-28)

## Blocked

<!-- Items waiting on external dependency or decision -->

## Personal

- [x] P1 Find faster internet for new house — going with Xfinity (2026-03-29)
- [ ] P2 Tailscale integration — tunnel platform services for remote access + mesh networking
- [ ] P3 Onboard Maria to Tailscale — add her devices to the network when ready

## Ideas

<!-- Not yet prioritized — move to Active when ready -->
- Agent-gateway: add rate limiting per agent
- Plane→n8n: auto-create n8n workflows from Plane issues tagged "automation"
- Neo4j GraphRAG: knowledge graph for agent context
- Multi-model benchmark matrix: compare glm-4.7-flash vs qwen3:32b vs nemotron-cascade-2

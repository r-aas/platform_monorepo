# Platform Backlog

Persistent task queue for autonomous Claude Code sessions. Ordered by priority.
Tasks move to RESUME.md "completed" section when done.

## Format

```
- [ ] P{0-3} {task} — {one-line context}
```

P0 = blocking/broken, P1 = high value, P2 = planned, P3 = nice-to-have

## Active

- [ ] P2 Benchmark tuning — 66.7% pass rate, threshold 70%; tune prompts or test cases for baseline
- [ ] P2 DataOps Phase 4: domain tags — tag datasets by domain (agent, eval, trace, workflow)
- [ ] P2 Dashboard topology — wire DataHub lineage into ReactFlow graph
- [ ] P2 n8n credential rotation — move hardcoded tokens from values.yaml to existingSecret refs
- [ ] P2 Benchmark baseline — establish passing baseline with working judge, store in MLflow
- [ ] P3 Spec 015 ship — finish all phases, mark shipped

## Completed (recent)

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

## Ideas

<!-- Not yet prioritized — move to Active when ready -->
- Agent-gateway: add rate limiting per agent
- Plane→n8n: auto-create n8n workflows from Plane issues tagged "automation"
- Neo4j GraphRAG: knowledge graph for agent context
- Multi-model benchmark matrix: compare qwen2.5:7b vs 14b vs gemma3:12b

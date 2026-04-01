# Platform Backlog

Persistent task queue for autonomous Claude Code sessions. Ordered by priority.
Tasks move to RESUME.md "completed" section when done.

## Format

```
- [ ] P{0-3} {task} — {one-line context}
```

P0 = blocking/broken, P1 = high value, P2 = planned, P3 = nice-to-have

## Active

- [x] P0 Fix kagent agent CrashLoopBackOff — added toolNames to all Agent CRD tool refs (2026-03-30)
- [x] P0 Fix CronJob→A2A failures — shell quoting fix + fire-and-forget, HTTP 200 verified (2026-03-30)
- [x] P1 CRD bootstrap script — manifests/crds/ + scripts/bootstrap-crds.sh (2026-03-30)
- [x] P1 Slim agent-gateway — deleted registry, MCP proxy, skills registry; -2679 lines (2026-03-30)
- [x] P1 Replace MetaMCP with agentgateway — Gateway API + HTTPRoutes, 8/8 backends verified, ingress live (2026-03-30)
- [x] P2 Seed agentregistry — 6 agents, 9 MCP servers, 21 skills published via v0 API (2026-03-30)
- [x] P1 Wire n8n MCP Client to agentgateway — mcp-all backend, 243 tools aggregated, chat.json updated (2026-03-30)
- [x] P1 Merge genai-mlops into platform_monorepo — single repo, 139 files, genai-mlops deleted (2026-03-30)
- [x] P1 Unify ingress to *.platform.127.0.0.1.nip.io — ~90 files across repos (2026-03-30)
- [x] P1 Unify gateway — single hostname, path-based routing for MCP proxy (2026-03-30)
- [x] P1 GitHub Actions CI — 12/14 images on ghcr.io, chart linting, release workflow (2026-03-30)
- [x] P1 v0.1.0 release — tagged images, GitHub Release with install instructions (2026-03-30)
- [x] P2 README rewrite — AgentOps reference framing, full system docs (2026-03-30)
- [x] P1 Replace DataHub with ODD Platform — removed 8-container stack, added 1-container ODD Platform + mcp-odd-platform MCP server (2026-03-31)
- [x] P1 Agent tool count gate — agent-lint.py --strict blocks >20 tools per agent, trimmed all 6 agents (374→103 tools) (2026-03-31)
- [x] P1 CEL policies — 4 AgentgatewayPolicy CRDs: deny-dangerous-tools, deny-model-mutation, kubernetes-read-only, gitlab-write-protection (2026-03-31)
- [x] P0 Replace LiteLLM with agentgateway LLM Gateway — supply chain attack remediation, Rust proxy replaces Python (2026-04-01)
- [x] P0 Supply chain hardening — digest-pinned images, pinned deps, non-root containers, secrets externalized (2026-04-01)
- [ ] P1 task up clean bootstrap test — verify ghcr.io pulls work end-to-end from zero
- [ ] P1 W3: OTEL → Langfuse trace pipeline — enable kagent otel, deploy OTEL Collector, route to Langfuse
- [x] P1 W1: MCP server secrets — seed-secrets.sh already creates all 5, MCPServer CRDs wired, old charts deleted (2026-04-01)
- [x] P1 W2: Delete transpiler + custom agent format — all three artifacts already gone (2026-04-01)
- [x] P1 W11: GitLab CI/CD Catalog — 5 components scaffolded in ci-catalog/ (2026-04-01)
- [x] P1 W12: GitOps × AgentOps lifecycle — spec, skill, components.yaml updated with graph→executor mapping (2026-04-01)
- [ ] P2 W4: Delete 5 redundant n8n workflows — chat, a2a, eval, claude-auto, prompt-resolve
- [ ] P2 W5: Agent promotion pipeline — genai-dev/stage/prod namespaces + eval gates
- [x] P2 W6: Taxonomy-aware policy engine — --type flag, --scope-doc for ISO 42001 Clause 4.3 (2026-04-01)
- [x] P2 W7: OWASP Agentic Top 10 policies — P-050 through P-059, --standard owasp flag, compliance map (2026-04-01)
- [ ] P2 W8: Admission policies — CEL/Kyverno for agent CRD validation
- [ ] P2 W9: Compliance dashboard — MLflow + Langfuse metrics
- [ ] P2 W10: Slim agent-gateway to ~500 LOC — delete everything OSS components cover
- [ ] P2 Tailscale integration — tunnel platform services for remote access
- [ ] P2 Multi-model benchmark — compare glm-4.7-flash vs qwen3:32b
- [ ] P3 NIST COSAiS overlay — tracking only, nist-cosais.yml
- [x] P1 Activate autonomous loop — runner on :7777, claude-autonomous workflow active (4h cron), MLflow logging (2026-03-29)
- [x] P2 Benchmark tuning — smoke 100% (3/3), glm-4.7-flash judge, scoring guide, relaxed criteria (2026-03-29)
- [x] P2 DataOps Phase 4: domain tags — 5 domains, 22 datasets tagged (agent, eval, trace, workflow, research) (2026-03-29)
- [x] P2 Dashboard topology — modernized for k3d, DataHub lineage edges, stale services removed (2026-03-29)
- [x] P2 n8n credential rotation — LITELLM_API_KEY, PLANE_API_TOKEN, GITLAB_PAT moved to n8n-env-secrets; encryption key + pg password via existingSecret (2026-03-29)
- [x] P2 Benchmark baseline — smoke 100%, avg score 0.88, MLflow run f05eaa5a (2026-03-29)
- [x] P3 Spec 015 ship — all 4 phases complete, status: shipped (2026-03-29)

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

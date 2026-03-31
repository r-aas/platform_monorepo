# Platform Monorepo — Session Resume

## Session: 2026-03-30 — Monorepo Consolidation + GitHub CI + v0.1.0 Release

### What Was Done

**1. Unified Ingress Domains**
- All services moved to `*.platform.127.0.0.1.nip.io` (~90 files across both repos)
- Replaced `.mewtwo.`, `.genai.`, `.dev.` subdomain patterns

**2. Unified Gateway**
- Consolidated agent-gateway + agentgateway MCP proxy into single hostname
- `gateway.platform.127.0.0.1.nip.io` — Python agent-gateway at `/`, Rust MCP proxy at `/mcp/*`
- nginx path priority handles routing (Prefix `/mcp` > Prefix `/`)

**3. Monorepo Merge**
- genai-mlops fully absorbed into platform_monorepo (139 files, 25,587 insertions)
- 17 workflow JSONs → `n8n-data/workflows/`
- 24 specs, 23 scripts, 5 taskfile includes, 6 MCP Dockerfiles, seed data, docs
- Workflow promotion Helm hook updated to clone from platform_monorepo
- genai-mlops repo deleted from GitHub and GitLab

**4. README Rewrite**
- Framed as AgentOps end-to-end reference implementation
- Covers: all 6 agents, 17 workflows, 9 MCP servers, prompt lifecycle, troubleshooting
- Hardware requirements calculated: minimum 64 GB Apple Silicon Mac
- Model: glm-4.7-flash (19 GB) + nomic-embed-text (274 MB)

**5. GitHub Actions CI**
- `build-images.yml`: builds ARM64 images on push, pushes to `ghcr.io/r-aas/*`
- `lint-charts.yml`: helm lint + template validation on chart changes
- `release.yml`: builds all images with semver tags, creates GitHub Release
- 12/14 images on ghcr.io (litellm-mlflow and open-ontologies built locally only)
- `build-images.sh` updated: pulls from ghcr.io first, falls back to local build

**6. GitHub Polish**
- v0.1.0 release live with tagged images
- Issue templates (bug report with `task doctor` output, feature request by layer)
- CONTRIBUTING.md (how to add charts, workflows, agents, MCP servers)
- PR template with layer checklist
- Dependabot for GHA actions, Dockerfiles, pip deps
- 12 repo topics for discoverability
- CI badges in README
- Consistent `imagePullPolicy: IfNotPresent` across all charts

### Platform State

- **35 ArgoCD apps**: All Synced
- **~80 pods** in genai namespace (DataHub hooks + agent schedule pods have pre-existing failures)
- **Smoke test**: 27/27 pass (10 services, 9 MCP backends, 7 webhooks, E2E chat)
- **ghcr.io**: 12 images published, v0.1.0 tagged
- **Single repo**: platform_monorepo is sole source of truth

### Commits This Session

```
328b272 feat: self-healing n8n workflow promotion
d738ee4 refactor: unify all ingress URLs to *.platform.127.0.0.1.nip.io
2135a10 refactor: unify gateway URLs — gateway.platform.127.0.0.1.nip.io with /mcp prefix
471c4d1 feat: merge genai-mlops into monorepo — single repo for all platform code
7c2c2e0 docs: rewrite README as AgentOps reference implementation guide
7681518 docs: add hardware requirements with calculated resource needs
96da9b0 docs: simplify hardware to assume glm-4.7-flash, minimum 64 GB
e4f47cd feat: GitHub Actions CI — image builds, chart linting, releases
0beb0dc fix: exclude litellm-mlflow and open-ontologies from CI builds
0d5f9b9 chore: CI polish — dependabot, contributing guide, consistent pull policy
```

### Next Steps

1. **CEL policies** — AgentgatewayPolicy for per-agent tool filtering
2. **Tailscale integration** — tunnel platform services for remote access
3. **Multi-model benchmark** — compare glm-4.7-flash vs qwen3:32b
4. **DataHub hook fix** — datahub-system-update keeps crashing, blocking ArgoCD sync
5. **task up end-to-end test** — verify a clean bootstrap from zero works with ghcr.io pulls

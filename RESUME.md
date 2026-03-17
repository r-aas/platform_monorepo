# Platform Monorepo — Session Resume

## Session: 2026-03-17 — ArgoCD ApplicationSet + Agent Gateway

### Built

- **ApplicationSet pattern** — Replaced individual ArgoCD Application manifests with two ApplicationSets (`workloads-git`, `workloads-helm`). Inspired by danmanners/homelab-kube-cluster (cloned to `~/work/clones/homelab/homelab-kube-cluster/`).
- **Agent-gateway Helm chart** — `charts/agent-gateway/` (FastAPI 8080, SQLite PVC, Ollama via host.docker.internal). Built from `~/work/repos/homelab/services/agent-gateway/`, imported via `k3d image import`.
- **Ingress-nginx values** — `charts/ingress-nginx/` version-controlled; `k3d:install-ingress` uses values files.
- **GitLab omnibus config fix** — `envFrom: configMapRef` truncated multiline → switched to `configMapKeyRef`.

### ArgoCD Applications (all via ApplicationSet)

| App | Status | Namespace |
|-----|--------|-----------|
| genai-infra | OutOfSync/Missing | genai |
| genai-apps | OutOfSync/Missing | genai |
| gitlab-ce | Synced/Healthy | platform |
| agent-gateway | Synced/Healthy | dev |

### Bugs Fixed This Session

1. GitLab `GITLAB_OMNIBUS_CONFIG` truncated to first line (`envFrom` → `configMapKeyRef`)
2. `local-path-provisioner` ImagePullBackOff (docker pull + k3d image import)

### Known Issues

- **GitLab registry push from Docker CLI** — Colima VM resolves nip.io to 127.0.0.1 (VM-local). Workaround: `k3d image import`. CI Runner on bridge network can reach registry directly.
- **Agent-gateway Ollama unavailable** — Chart sets OpenAI env vars but agent-gateway uses its own config. Check `~/work/repos/homelab/services/agent-gateway/src/` for actual env var names.

### Next Steps

- [local] Configure agent-gateway Ollama connection
- [local] Add Keycloak to `workloads-helm` ApplicationSet (Bitnami chart)
- [local] Investigate Colima DNS workaround for registry push
- [local] Test full GitOps loop: edit values → push → ArgoCD detects drift → sync

### Commits

```
003e88f Fix GitLab omnibus config injection, set agent-gateway pullPolicy
07fa61f Fix agent-gateway chart port and data path to match Dockerfile
74488ee Add agent-gateway Helm chart and ApplicationSet entry
91adb4e Switch to ApplicationSet pattern for ArgoCD workload management
```

---

## Prior Session — n8n Platform Infrastructure

### What Was Built

### n8n Platform Infrastructure (complete)
- Independent n8n + PostgreSQL per namespace (dev, stage, prod)
- Envsubst-templated manifests, idempotent secret generation
- Full Taskfile lifecycle: `task n8n:deploy-all`, `task n8n:teardown-all`, `task n8n:health`, `task n8n:status`
- Preflight memory guard prevents deploying when VM is memory-starved

### n8n API Automation (complete)
- `scripts/n8n-setup-api.sh` — headless owner creation + API key generation per namespace
- API keys stored in k8s secrets (`n8n-secrets.api-key` per namespace)
- Owner passwords stored in k8s secrets (`n8n-secrets.owner-password` per namespace)
- `task n8n:setup` runs the script; `task n8n:deploy-all` calls setup automatically after deploy
- MCP config (`~/.claude/settings.json`) updated to point at k3d dev instance
- Idempotent: skips if API key already exists and is valid

### GitLab CE (complete, from prior sessions)
- docker-compose on host, k8s ingress proxy in platform namespace
- Runner with Kaniko for CI builds
- 2 repos with passing pipelines: counter-app (6-stage), genai-mlops (4-stage)

## Current State

All 6 pods Running, 0 restarts, health checks passing:
```
task n8n:health
# ✓ dev: healthy (200)
# ✓ stage: healthy (200)
# ✓ prod: healthy (200)
```

URLs:
- http://n8n.dev.127.0.0.1.nip.io
- http://n8n.stage.127.0.0.1.nip.io
- http://n8n.prod.127.0.0.1.nip.io
- http://gitlab.mewtwo.127.0.0.1.nip.io

n8n Owner: admin@platform.local (all 3 instances)

## Key Gotchas Discovered

1. **Postgres on virtiofs**: macOS reports all PVC files as UID 501, chown is no-op. Fix: `runAsUser: 501, fsGroup: 501` in securityContext.

2. **n8n v2.x memory**: Always spawns JS Task Runner subprocess (can't disable). `NODE_OPTIONS` inherited by child = two V8 heaps. Set `NODE_OPTIONS=--max-old-space-size=256` + `N8N_RUNNERS_MAX_OLD_SPACE_SIZE=256`, container limit 2Gi.

3. **8GB VM contention**: GitLab CE (3.1GB) + genai-mlops stack (~2.3GB) + deathco (~450MB) + k3d nodes (~1.1GB) = 7GB. Must stop non-essential containers before n8n deploy. `task n8n:preflight` gates on 1500MB available.

4. **n8n startup probes**: DB migrations take >30s. Needs startupProbe (failureThreshold: 30, periodSeconds: 10 = 5min window).

5. **n8n REST API body parser**: Passwords containing `!` crash the login endpoint body parser (500 Internal Server Error). Use alphanumeric passwords only for headless setup.

6. **n8n v2.10 login field name**: Login uses `emailOrLdapLoginId` not `email`. Owner setup uses `email`.

7. **n8n v2.10 API key creation**: Requires both `scopes` (array) and `expiresAt` (epoch ms number) fields.

8. **macOS sed vs GNU sed**: `sed 's/^./\U&/'` (uppercase first char) doesn't work on macOS. Use `tr '[:lower:]' '[:upper:]'` for char transforms.

## What Broke and Why

- Postgres CrashLoopBackOff: virtiofs UID mismatch (fixed with UID 501)
- n8n OOMKilled repeatedly: two V8 heaps exceeding container limit (fixed with heap caps)
- n8n OOMKilled even with heap caps: VM had only 147MB free due to competing containers (fixed by stopping deathco containers)
- CoreDNS CrashLoopBackOff: cascading OOM pressure (fixed with rollout restart)
- Liveness probe killing n8n during migration (fixed with startupProbe)
- n8n login 500 with `!` in password: body parser bug (fixed by using alphanumeric passwords)
- kubectl port-forward/exec/logs 502: kubelet proxy broken on agent-1 under memory pressure (transient)

## Next Steps

- [local] Restart Claude Code to pick up new MCP config pointing at k3d n8n dev
- [local] Verify n8n-knowledge and n8n-manager MCP tools connect to live instance
- [local] Consider increasing Rancher Desktop VM from 8GB to 12-16GB
- [local] Start building n8n workflows for genai-mlops integration
- [local] Skill evolution: capture n8n API automation patterns
- [local] Commit new scripts/n8n-setup-api.sh and taskfile changes

## Credentials

- GitLab root: `KiyJ8NT+6crbf2/3MYjkqL9DbCfKhvyjkJAILkQXCD4=`
- GitLab PAT: `glpat-S6IC_PVgbqr_TQK77kmj_W86MQp1OjEH.01.0w1bw9arp`
- Runner token: `glrt-anRtfWuxcks9Z0IqqpxPG286MQp0OjEKdToxCw.01.120459lym`
- k3d API port: 58841
- n8n owner: admin@platform.local
- n8n passwords: PlatformN8n{Dev,Stage,Prod}2024 (note: Stage/Prod used `Ustage`/`Uprod` due to macOS sed quirk)
- n8n API keys: stored in k8s secrets (`kubectl get secret n8n-secrets -n <ns> -o jsonpath='{.data.api-key}' | base64 -d`)

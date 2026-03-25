<!-- status: shipped -->

# 020: Platform Bootstrap Lifecycle

## Overview
One-command platform lifecycle management: `task up` bootstraps from zero to all services healthy, `task down` tears down cleanly, `task start`/`task stop`/`task restart` handle the paused/resumed lifecycle.

## User Stories
- As a developer, I run `task up` on a fresh machine and get a fully working platform with all services healthy in one command
- As a developer, I run `task stop` to free resources, then `task start` to resume exactly where I left off
- As a developer, I run `task down` to tear down the cluster while preserving PV data for next bootstrap
- As a developer, I run `task restart` to recover from any crash state (Colima stuck, image cache lost, stale DNS)
- As a developer, I run `task smoke` to verify all services are reachable at any time

## Functional Requirements

### FR-001: Full Bootstrap (`task up`)
The system SHALL execute these steps in order:
1. Preflight checks (tools, Docker, Ollama, disk space) — 15 checks
2. Ensure Colima VM is running (with FallbackDNS=8.8.8.8)
3. Create k3d cluster if not exists (idempotent)
4. Configure cluster: fix node DNS → restart CoreDNS → fix local-path provisioner
5. Sync helmfile releases (ingress-nginx, namespace-init, gitlab-ce, argocd, argocd-root) — skip if ArgoCD already deployed
6. Bootstrap GitLab (PAT, runner, ArgoCD creds, push repo)
7. Build and import custom Docker images into k3d
8. Wait for ArgoCD to sync all workloads (soft timeout — non-fatal)
9. Setup n8n (owner account, API key)
10. Import n8n workflows from genai-mlops (patch URLs, activate, create __sessions experiment)
11. Sync agent definitions to MLflow
12. Run smoke tests (19 checks)
13. Print all URLs and credentials

### FR-002: Clean Teardown (`task down`)
The system SHALL:
- Destroy all helmfile releases
- Delete the k3d cluster
- Preserve PV data at ~/work/data/k3d/mewtwo/

### FR-003: Pause/Resume (`task stop` / `task start`)
- `task stop` SHALL stop the k3d cluster without deleting it
- `task start` SHALL: ensure Colima → start cluster → configure DNS/local-path → build images → sync-if-needed → smoke

### FR-004: Recovery (`task restart`)
- `task restart` SHALL handle: Colima crash, image cache loss, stale DNS, overlay2 errors
- Implemented as `task stop` → `task start`

### FR-005: Health Verification (`task smoke`)
The smoke test SHALL check:
- ArgoCD application health (all apps Healthy/Synced)
- Ingress endpoints (ArgoCD, GitLab, n8n, MLflow, LiteLLM, MinIO)
- Internal service connectivity (LiteLLM → Ollama, n8n → LiteLLM, n8n → MLflow)
- Agent gateway e2e (user → agent-gateway → n8n → LiteLLM → Ollama)
- Database connectivity (pg-n8n, pg-mlflow, pgvector)
- Pod health (genai + platform namespaces)
- Host Ollama availability

## Acceptance Criteria
- SC-001: `task down && task up` completes with 19/19 smoke tests passing
- SC-002: `task stop && task start` completes with 19/19 smoke tests passing
- SC-003: `task up` is idempotent — running twice produces same result
- SC-004: Cold bootstrap (no cached images) completes in under 60 minutes
- SC-005: Warm bootstrap (cached images) completes in under 10 minutes
- SC-006: Preflight fails fast with actionable error messages
- SC-007: DNS is functional before any Helm releases are installed

## Key Decisions
- Split `cluster-up` into `cluster-create` (has status check) + `cluster-configure` (always runs) to prevent DNS fixes from being skipped on retry
- CoreDNS restart after DNS fix — adding 8.8.8.8 to node resolv.conf alone is insufficient
- `sync-if-needed` checks for argocd-server deployment existence (not app sync status which is "Unknown" during startup)
- `wait-healthy` timeout is non-fatal (exit 0) — cold image pulls can exceed 600s
- GitLab CE uses `wait: false` in helmfile — 3GB image pull would block all other releases
- `ensure-colima` adds FallbackDNS=8.8.8.8 to Colima VM systemd-resolved config

## Dependencies
- Colima VM (8 CPU, 32 GB RAM, 200 GB disk)
- k3d, kubectl, helm, helmfile CLI tools
- Ollama running natively on Mac host
- genai-mlops repo at ~/work/repos/genai-mlops (for n8n workflow import)

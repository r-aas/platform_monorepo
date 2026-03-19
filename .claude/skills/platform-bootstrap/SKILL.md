---
name: platform-bootstrap
description: |
  Full cluster bootstrap from zero to all services healthy. Use when setting up the platform
  from scratch, recovering from cluster deletion, onboarding, or verifying the full stack.
  Covers the exact sequence, timing, verification gates, and common failure modes.
version: 1.0.0
---

# Platform Bootstrap

## Prerequisites

| Requirement | Check | Fix |
|-------------|-------|-----|
| Colima running | `colima status` | `colima start --cpu 8 --memory 32 --disk 200` |
| Ollama running | `ollama ps` | `brew services start ollama` |
| Docker socket | `docker ps` | Colima provides this |
| Helm + helmfile | `helm version && helmfile --version` | `brew install helm helmfile` |
| k3d | `k3d version` | `brew install k3d` |
| task | `task --version` | `brew install go-task` |

## Full Bootstrap Sequence

```
Phase 1: Infrastructure (task up)
  1. k3d cluster create (k3d-mewtwo.yaml)     ~30s
  2. Patch local-path provisioner              ~5s (CRITICAL — see below)
  3. helmfile sync                              ~12 min
     ├── ingress-nginx                          ~1 min
     ├── namespace-init                         ~5s
     ├── gitlab-ce (first boot)                 ~2 min (M4 Max, overlay FS)
     ├── argocd                                 ~2 min
     └── argocd-root (ApplicationSets)          ~30s

Phase 2: GitLab Setup (task gitlab-setup)
  4. Wait for GitLab healthy                    ~2 min (after helm)
  5. Create root PAT (GitLab 18+)              ~5s (hashed PATs, must use create! not set_token)
  6. Register GitLab Runner (new flow)          ~30s (POST /api/v4/user/runners → glrt-* token)
  7. Push platform_monorepo to GitLab           ~10s
  8. Configure ArgoCD repo credentials          ~5s (repo-creds Secret, NOT configs.cm)

Phase 3: ArgoCD Takes Over (automatic)
  9. ArgoCD detects ApplicationSets             ~30s
  10. ArgoCD syncs all workloads                ~5 min
     ├── gitlab-ce (self-managed now)
     ├── gitlab-runner
     ├── genai-infra (LiteLLM, postgres, etc.)
     ├── genai-apps
     ├── n8n-dev, n8n-stage, n8n-prod
     ├── airflow
     └── argocd (self-upgrade)

Phase 4: Post-deploy (manual / task-driven)
  11. n8n secrets provisioning                  task n8n-secrets
  12. n8n API setup (owner + key)               task n8n-setup
  13. Workflow import                            (per genai-mlops)
  14. Smoke tests                               task doctor
```

**Total time**: ~20 minutes from zero to all services.

## Task Commands

From `~/work`:

```bash
task up              # Phase 1 + 2 (full bootstrap)
task down            # Tear down (PV data preserved on host)
task stop            # Pause (colima stop, preserves state)
task start           # Resume (colima start + k3d start)
task status          # Full overview (nodes, pods, ingress, apps)
task doctor          # Health check (Colima, Docker, k3d, Ollama, services)
task urls            # Print all service URLs
```

## Verification Gates

After each phase, verify before continuing:

### After Phase 1 (helmfile sync)
```bash
kubectl get nodes                                    # 1 node, Ready
kubectl get pods -A | grep -v Running | grep -v Completed  # no stuck pods
kubectl get ingress -A                               # ingress-nginx active
```

### After Phase 2 (GitLab setup)
```bash
curl -sf http://gitlab.mewtwo.127.0.0.1.nip.io/-/health  # GitLab healthy
task gitlab-password                                      # root password works
```

### After Phase 3 (ArgoCD sync)
```bash
task argocd-apps                                     # all apps Synced/Healthy
kubectl get pods -n genai                            # genai services running
kubectl get pods -n dev                              # n8n-dev running
```

## GitLab CE in k3d

### ARM64 Multi-Arch Support
- GitLab CE multi-arch (ARM64) Docker images start at **18.1.0-ce.0**
- ALL 17.x tags are amd64-only — they will either fail to pull or run under QEMU (very slow)
- Always use 18.1.0+ when running on Apple Silicon

### GitLab 18.x PAT Changes
- GitLab 18.x hashes PATs on storage — cannot use `set_token()` to set a known token value
- Must use `create!` method which auto-generates the token and returns it once
- Bootstrap scripts must capture the token from the creation response

### Omnibus Chef Reconfigure
- GitLab Omnibus runs Chef reconfigure on boot, which needs `chown` on `/etc/gitlab`
- This REQUIRES overlay FS — fails on sshfs bind-mounts
- First boot: ~2 min on M4 Max with overlay FS (much slower on sshfs/QEMU)

## GitLab Runner in k3d (GitLab 16+ Flow)

### Old Registration Tokens Removed
The old runner registration token flow (`registration_token` from GitLab settings) was
removed in GitLab 18.0. New flow:

1. `POST /api/v4/user/runners` with PAT (scope: `create_runner`) → returns `glrt-*` token
2. Runner Helm chart uses init container to inject `glrt-*` token into config.toml from k8s Secret
3. Kubernetes executor: runner creates CI job pods in-cluster (not Docker containers)

### Runner Helm Chart Config
```yaml
# Key values for gitlab-runner Helm chart
gitlabUrl: http://gitlab-ce.platform.svc.cluster.local
runnerToken: glrt-xxxxxxxxxxxxxxxxxxxx  # from API, stored in Secret
runners:
  executor: kubernetes
  config: |
    [[runners]]
      [runners.kubernetes]
        namespace = "platform"
```

## CRITICAL: Local-Path Provisioner Fix

**Must run immediately after cluster creation, BEFORE any helmfile sync.**

k3d's default local-path provisioner uses `/var/lib/rancher/k3s/storage` which is an sshfs
bind-mount from the Mac host via Colima. sshfs does NOT support `chown`. All Bitnami
PostgreSQL charts (and GitLab CE Omnibus) fail with "wrong ownership" on data dirs.

Fix: change to `/var/lib/rancher/k3s/local-storage` (overlay FS, supports chown):

```bash
kubectl get configmap local-path-config -n kube-system -o json | \
  python3 -c "
import json, sys
cm = json.load(sys.stdin)
config = json.loads(cm['data']['config.json'])
config['nodePathMap'][0]['paths'] = ['/var/lib/rancher/k3s/local-storage']
cm['data']['config.json'] = json.dumps(config)
json.dump(cm, sys.stdout)
" | kubectl apply -f - && \
kubectl rollout restart deploy local-path-provisioner -n kube-system
```

**Trade-off**: Data on overlay FS does NOT survive node re-creation (only cluster restart).
This is acceptable for local dev — data is ephemeral and will be reprovisioned.

**If you see CrashLoopBackOff on any PostgreSQL pod**: check the PV path. If it's
`/var/lib/rancher/k3s/storage/...` (old path), delete the PVC and let it recreate.
The StatefulSet will get a new PVC on the correct overlay path.

## Common Failure Modes

### GitLab CE takes >15 minutes
- Colima VM too small. Need ≥4 CPU, 8 GB RAM.
- Check storage: local-path provisioner must use overlay FS, not sshfs (see platform-helm-authoring skill)
- First boot runs DB migrations + asset compilation. Subsequent boots are faster.

### ArgoCD can't reach GitLab
- Uses internal DNS: `gitlab-ce.platform.svc.cluster.local` (NOT nip.io)
- Check: `kubectl exec -n platform deploy/argocd-server -- curl -s http://gitlab-ce.platform.svc.cluster.local/-/health`
- If PAT expired: re-run `task gitlab-setup`
- If credentials changed: restart argocd-server AND argocd-repo-server to clear cache

### Pods stuck in Pending
- Check node resources: `kubectl describe node | grep -A5 Allocated`
- Check PVC: `kubectl get pvc -A` — Pending PVCs mean storage provisioner issue
- Check taints: `kubectl describe node | grep Taint`

### genai-infra OutOfSync
- Chart.lock stale: `cd charts/genai-infra && helm dependency update`
- Missing dependency chart: check `Chart.yaml` dependencies exist in `charts/`

### Disk pressure after restart
- `kubectl taint nodes $(kubectl get nodes -o name) node.kubernetes.io/disk-pressure-`
- Free Colima disk: `colima ssh -- df -h` → `docker system prune -af`

### NodePort allocation full
- `docker restart k3d-mewtwo-server-0` to rebuild bitmap

## Recovery (non-destructive)

If things are broken but you want to keep data:

```bash
# Option 1: Restart nodes (keeps PVs, re-applies /etc/hosts)
docker restart $(docker ps --filter name=k3d-mewtwo -q)

# Option 2: Full cluster recreation (PV data preserved on host)
task down && task up

# Option 3: Just re-bootstrap ArgoCD
helmfile -l tier=platform sync
```

## Service URLs (when healthy)

| Service | URL | Credentials |
|---------|-----|-------------|
| GitLab | http://gitlab.mewtwo.127.0.0.1.nip.io | root / `task gitlab-password` |
| ArgoCD | http://argocd.platform.127.0.0.1.nip.io | admin / `task argocd-password` |
| n8n (dev) | http://n8n.dev.127.0.0.1.nip.io | set during setup |
| LiteLLM | http://litellm.genai.127.0.0.1.nip.io | API key in secrets |
| Ollama | http://localhost:11434 | none (host-native) |

## Helmfile Architecture Pattern

Helmfile is **bootstrap-only**. It installs the minimum to get ArgoCD running:

```
helmfile sync
  → ingress-nginx       (tier: infra)
  → namespace-init       (tier: infra)
  → gitlab-ce            (tier: platform)
  → argocd               (tier: platform)
  → argocd-root          (tier: platform) — seeds ApplicationSets
```

After bootstrap, ArgoCD manages ALL day-2 operations via ApplicationSets, including
upgrading itself. Never use helmfile for day-2 changes.

### Multi-Arch Support
`PLATFORM_ARCH` env var selects arch-specific values files:
```bash
PLATFORM_ARCH=arm64 helmfile sync  # default on Apple Silicon
PLATFORM_ARCH=amd64 helmfile sync  # for Intel/cloud
```

Helmfile references: `values-{{ env "PLATFORM_ARCH" | default "arm64" }}.yaml`

## Rationalizations to Reject

- "I'll skip helmfile and just kubectl apply" — NO, ordering and dependencies matter
- "GitLab isn't ready yet but I'll push anyway" — NO, wait for health check
- "I'll helm install after ArgoCD is running" — NO, ArgoCD will fight manual installs
- "The cluster is broken, I'll delete everything" — NO, try restart/re-bootstrap first
- "I'll use helmfile to update this service" — NO, helmfile is bootstrap-only, push to GitLab for ArgoCD

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
  2. helmfile sync                              ~12 min
     ├── ingress-nginx                          ~1 min
     ├── namespace-init                         ~5s
     ├── gitlab-ce (first boot)                 ~8 min ← slowest
     ├── argocd                                 ~2 min
     └── argocd-root (ApplicationSets)          ~30s

Phase 2: GitLab Setup (task gitlab-setup)
  3. Wait for GitLab healthy                    ~2 min (after helm)
  4. Create root PAT                            ~5s
  5. Configure GitLab Runner                    ~30s
  6. Push platform_monorepo to GitLab           ~10s
  7. Configure ArgoCD repo credentials          ~5s

Phase 3: ArgoCD Takes Over (automatic)
  8. ArgoCD detects ApplicationSets             ~30s
  9. ArgoCD syncs all workloads                 ~5 min
     ├── gitlab-ce (self-managed now)
     ├── gitlab-runner
     ├── genai-infra (LiteLLM, postgres, etc.)
     ├── genai-apps
     ├── n8n-dev, n8n-stage, n8n-prod
     ├── airflow
     └── argocd (self-upgrade)

Phase 4: Post-deploy (manual / task-driven)
  10. n8n secrets provisioning                  task n8n-secrets
  11. n8n API setup (owner + key)               task n8n-setup
  12. Workflow import                            (per genai-mlops)
  13. Smoke tests                               task doctor
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

## Common Failure Modes

### GitLab CE takes >15 minutes
- Colima VM too small. Need ≥4 CPU, 8 GB RAM.
- First boot runs DB migrations + asset compilation. Subsequent boots are faster.

### ArgoCD can't reach GitLab
- Uses internal DNS: `gitlab-ce.platform.svc.cluster.local` (NOT nip.io)
- Check: `kubectl exec -n platform deploy/argocd-server -- curl -s http://gitlab-ce.platform.svc.cluster.local/-/health`
- If PAT expired: re-run `task gitlab-setup`

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

## Rationalizations to Reject

- "I'll skip helmfile and just kubectl apply" — NO, ordering and dependencies matter
- "GitLab isn't ready yet but I'll push anyway" — NO, wait for health check
- "I'll helm install after ArgoCD is running" — NO, ArgoCD will fight manual installs
- "The cluster is broken, I'll delete everything" — NO, try restart/re-bootstrap first

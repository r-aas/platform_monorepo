---
name: platform-argocd
description: |
  ArgoCD GitOps patterns for the platform monorepo. Use when adding workloads to ArgoCD,
  debugging sync issues, understanding bootstrap vs day-2, configuring ApplicationSets,
  or troubleshooting OutOfSync/Missing/Degraded states. Covers the helmfile→ArgoCD handoff.
version: 1.0.0
---

# Platform ArgoCD

## Architecture: Bootstrap vs Day-2

```
helmfile sync (one-time)
  → ingress-nginx
  → namespace-init
  → gitlab-ce
  → argocd (seed install)
  → argocd-root (ApplicationSets)
      → ArgoCD now owns EVERYTHING including itself
```

After bootstrap, NEVER use helmfile for day-2 changes. Push to GitLab → ArgoCD syncs.

## ApplicationSet Structure

`charts/argocd-root/values.yaml` defines three workload types:

### gitWorkloads (charts in this repo)
```yaml
gitWorkloads:
  - appName: my-service
    project: workloads          # platform-apps | genai | workloads
    path: charts/my-service     # relative to repo root
    namespace: dev
    syncWave: "0"               # ordering within tier
    extraValueFile: ""          # optional per-instance values file
```

### helmWorkloads (external Helm repos)
```yaml
helmWorkloads:
  - appName: argocd
    project: platform-apps
    repoUrl: https://argoproj.github.io/argo-helm
    chart: argo-cd
    chartVersion: "9.4.10"
    valuesPath: charts/argocd   # local values dir
    namespace: platform
```

### crossRepoWorkloads (other GitLab repos)
```yaml
crossRepoWorkloads:
  - appName: orchestration
    project: workloads
    repoUrl: http://gitlab-ce.platform.svc.cluster.local/root/genai-mlops.git
    path: charts/orchestration
    namespace: dev
```

## Adding a New Service

1. Create chart: `charts/{name}/` with Chart.yaml, values.yaml, templates/
2. Add to `charts/argocd-root/values.yaml` under appropriate workload type
3. Commit and push to GitLab
4. ArgoCD auto-detects via ApplicationSet and creates Application
5. Verify: `kubectl get app -n platform {name}`

## Sync Wave Ordering

Within each tier, `syncWave` controls deploy order:
- `"0"` = infrastructure (databases, message queues)
- `"1"` = applications (depend on infra)
- `"2"` = post-deploy (migrations, smoke tests)

## Debugging Sync Issues

### OutOfSync
```bash
# See what differs
kubectl get app -n platform {name} -o yaml | yq '.status.sync'

# Force sync
kubectl patch app -n platform {name} --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'

# Or via CLI
argocd app sync {name} --server argocd.platform.127.0.0.1.nip.io --insecure
```

### Missing (app exists but resources don't)
Usually means: namespace doesn't exist, or chart has template errors.
```bash
# Check ArgoCD app status
kubectl get app -n platform {name} -o yaml | yq '.status.conditions'

# Check for Helm render errors
helm template charts/{name} --debug 2>&1 | head -50
```

### Degraded
Pod-level issue. Check pod events:
```bash
kubectl get pods -n {namespace} -l app.kubernetes.io/name={name}
kubectl describe pod -n {namespace} {pod-name}
kubectl logs -n {namespace} {pod-name} --previous
```

## ArgoCD Credentials

ArgoCD needs a GitLab PAT to pull from the in-cluster GitLab.

**Setup** (done by `scripts/gitlab-bootstrap.sh`):
```bash
# Create PAT in GitLab, then:
argocd repo add http://gitlab-ce.platform.svc.cluster.local/root/platform_monorepo.git \
  --username root --password $GITLAB_PAT \
  --insecure-skip-server-verification \
  --server argocd.platform.127.0.0.1.nip.io --insecure
```

**Note**: ArgoCD uses internal DNS (`gitlab-ce.platform.svc.cluster.local`), NOT nip.io.
This avoids the nip.io trap (see platform-k3d-networking skill).

## ArgoCD Self-Management

After bootstrap, ArgoCD manages its own upgrades:
- `charts/argocd/values.yaml` and `values-k3d.yaml` are version-controlled
- Changing `chartVersion` in `argocd-root/values.yaml` triggers ArgoCD to upgrade itself
- This is safe because ArgoCD handles rolling upgrades gracefully

## URLs

| Service | URL |
|---------|-----|
| ArgoCD UI | `http://argocd.platform.127.0.0.1.nip.io` |
| ArgoCD password | `task argocd-password` (from ~/work) |
| ArgoCD apps | `task argocd-apps` (list all) |

## Rationalizations to Reject

- "I'll just `helm install` directly" — NO, ArgoCD detects drift and will fight you
- "I'll use helmfile for this change" — NO, helmfile is bootstrap-only
- "The app is Missing, I'll delete and recreate" — NO, check template errors first
- "I'll skip syncWave, order doesn't matter" — NO, apps depending on DBs will crashloop

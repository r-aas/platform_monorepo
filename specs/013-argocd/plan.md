# Implementation Plan: ArgoCD GitOps Deployment

**Branch**: `013-argocd` | **Date**: 2026-03-15 | **Spec**: `specs/013-argocd/spec.md`

## Summary

Deploy ArgoCD to the k3d shared cluster using the official `argo/argo-cd` Helm chart. ArgoCD manages all Helm releases declaratively — genai-infra, genai-apps, and gitlab-ce — syncing from GitLab repos. Manual sync for local dev (no auto-sync surprises during active development). Bootstrap order: k3d cluster → ArgoCD (Helm CLI) → GitLab CE (Helm CLI) → ArgoCD Application for GitLab (self-managing going forward).

## Technical Context

**Language/Version**: YAML (Helm values, ArgoCD Application manifests), Bash (Taskfile tasks)
**Primary Dependencies**: `argo/argo-cd` Helm chart (~v7.x), `argocd` CLI
**Storage**: ArgoCD uses Redis (bundled) + in-cluster ConfigMaps. No PVCs needed.
**Testing**: `argocd app list`, `argocd app sync`, UI at `argocd.platform.127.0.0.1.nip.io`
**Target Platform**: k3d cluster "mewtwo" on Apple Silicon Mac
**Constraints**: ~500 MB RAM total (server + repo-server + app-controller + Redis)
**Scale/Scope**: 3-5 Applications (genai-infra, genai-apps, gitlab-ce, optionally argocd itself)

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| VI. Infra as Config | PASS | ArgoCD Application manifests are declarative, version-controlled |
| VII. Local-First | PASS | All in k3d, GitLab as local repo source |
| XI. Open-Source | PASS | Official CNCF project, well-documented |
| Minimize Moving Parts | JUSTIFIED | ArgoCD adds 4 pods (~500 MB) but replaces manual `helm upgrade` workflow with drift detection + audit trail |

## Decision: ArgoCD vs Flux vs Manual Helm

| Criterion | ArgoCD | Flux | Manual Helm |
|-----------|--------|------|-------------|
| UI Dashboard | Yes (built-in) | No (separate Weave GitOps) | No |
| Multi-source | Yes (v2.6+) | Yes | N/A |
| App-of-apps pattern | Yes | Yes (Kustomization) | N/A |
| Resource overhead | ~500 MB | ~300 MB | 0 |
| Learning curve | Medium | Medium | Low |
| Drift detection | Yes (real-time) | Yes (reconcile loop) | No |
| CLI | `argocd` (full CRUD) | `flux` (limited) | `helm` |
| R's stack alignment | Helm-native | Kustomize-native | Already have |

**Decision**: ArgoCD. Built-in UI is valuable for observability (see Architecture tab in dashboard). Helm-native (our charts work as-is). `argocd` CLI is more powerful than Flux for manual operations. Observatory dashboard can query ArgoCD API for deployment status.

## Project Structure

### Source Code (platform_monorepo)

```text
charts/
└── argocd/
    ├── values.yaml              # defaults (disable Dex, insecure mode, resources)
    └── values-k3d.yaml          # k3d overrides (ingress, admin password)

manifests/
├── namespace-init.yaml          # EXISTING (platform namespace)
├── argocd-appprojects.yaml      # NEW: genai + platform AppProjects
├── argocd-apps-genai.yaml       # NEW: Application for genai-infra + genai-apps
├── argocd-apps-platform.yaml    # NEW: Application for gitlab-ce
└── argocd-repo-secret.yaml      # NEW: GitLab PAT for repo access

taskfiles/
└── argocd.yml                   # NEW: deploy, teardown, status, sync, password, open
```

### Key Files

| File | Action | Purpose |
|------|--------|---------|
| `charts/argocd/values.yaml` | CREATE | ArgoCD Helm chart configuration |
| `charts/argocd/values-k3d.yaml` | CREATE | k3d ingress + local settings |
| `manifests/argocd-appprojects.yaml` | CREATE | AppProject isolation (genai, platform) |
| `manifests/argocd-apps-genai.yaml` | CREATE | Applications for genai-infra + genai-apps |
| `manifests/argocd-apps-platform.yaml` | CREATE | Application for gitlab-ce |
| `manifests/argocd-repo-secret.yaml` | CREATE | Template for GitLab PAT Secret |
| `taskfiles/argocd.yml` | CREATE | Taskfile tasks for ArgoCD lifecycle |
| `Taskfile.yml` | EDIT | Add `argocd:` include |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  k3d cluster "mewtwo"                                   │
│                                                         │
│  namespace: platform                                    │
│  ┌─────────────────────────────────────────────────┐   │
│  │  ArgoCD                                         │   │
│  │  ┌────────────┐ ┌──────────┐ ┌───────────────┐ │   │
│  │  │   server    │ │ repo-srv │ │ app-controller│ │   │
│  │  │ (UI + API)  │ │ (git     │ │ (reconcile   │ │   │
│  │  │ port 8080   │ │  clone)  │ │  loop)       │ │   │
│  │  └─────┬───────┘ └────┬─────┘ └──────┬───────┘ │   │
│  │        │              │               │         │   │
│  │  ┌─────▼──────────────▼───────────────▼──────┐  │   │
│  │  │              Redis (bundled)               │  │   │
│  │  └───────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────┐    polls    ┌──────────────────────┐ │
│  │  Ingress      │◄──────────│  GitLab CE (platform) │ │
│  │  argocd.mewtwo│           │  gitlab-ce.platform   │ │
│  └──────────────┘            └──────────────────────┘ │
│                                                         │
│  namespace: genai  ← managed by ArgoCD                  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  genai-infra (Helm)    genai-apps (Helm)         │  │
│  │  PG, MinIO, Neo4j...   n8n, MLflow, Langfuse...  │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: ArgoCD Helm Values (FR-001)

No custom chart needed — use official `argo/argo-cd` chart directly from repo.

**`charts/argocd/values.yaml`** (key settings):
```yaml
# Disable components not needed for local dev
dex:
  enabled: false
notifications:
  enabled: false
applicationSet:
  enabled: false  # can enable later for app-of-apps

# Server config
server:
  extraArgs:
    - --insecure  # HTTP behind ingress-nginx, no TLS termination
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi

# Repo server
repoServer:
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi

# App controller
controller:
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi

# Redis (bundled)
redis:
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 128Mi

configs:
  params:
    # Poll GitLab every 3 minutes
    timeout.reconciliation: 180s
```

**`charts/argocd/values-k3d.yaml`**:
```yaml
server:
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - argocd.platform.127.0.0.1.nip.io
    annotations:
      nginx.ingress.kubernetes.io/backend-protocol: HTTP
```

**Install command** (in Taskfile):
```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm upgrade --install argocd argo/argo-cd \
  -f charts/argocd/values.yaml \
  -f charts/argocd/values-k3d.yaml \
  --namespace platform --create-namespace \
  --wait --timeout 300s
```

### Phase 2: GitLab Repository Connection (FR-002)

Create a k8s Secret with GitLab PAT for ArgoCD to clone repos:

**`manifests/argocd-repo-secret.yaml`** (template — PAT added at runtime):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-repo
  namespace: platform
  labels:
    argocd.argoproj.io/secret-type: repository
type: Opaque
stringData:
  type: git
  url: http://gitlab-ce.platform.svc.cluster.local  # in-cluster DNS
  username: root
  password: GITLAB_PAT_HERE  # replaced by task argocd:setup
```

ArgoCD repo-server connects to GitLab via in-cluster Service DNS — no ingress needed for git clones. This is a major simplification over the docker-compose proxy model.

**Alternative** (if Spec 012 not yet shipped): Use `http://gitlab.platform.127.0.0.1.nip.io` via ingress. Works but adds a network hop.

### Phase 3: AppProjects (FR-006)

**`manifests/argocd-appprojects.yaml`**:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: genai
  namespace: platform
spec:
  description: GenAI MLOps platform applications
  sourceRepos:
    - 'http://gitlab-ce.platform.svc.cluster.local/root/genai-mlops.git'
    - 'http://gitlab-ce.platform.svc.cluster.local/root/platform_monorepo.git'
  destinations:
    - namespace: genai
      server: https://kubernetes.default.svc
  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
---
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: platform
  namespace: platform
spec:
  description: Platform infrastructure (GitLab, ArgoCD)
  sourceRepos:
    - 'http://gitlab-ce.platform.svc.cluster.local/root/platform_monorepo.git'
  destinations:
    - namespace: platform
      server: https://kubernetes.default.svc
  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
    - group: apiextensions.k8s.io
      kind: CustomResourceDefinition
```

### Phase 4: ArgoCD Applications (FR-003, FR-004, FR-005)

**`manifests/argocd-apps-genai.yaml`**:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: genai-infra
  namespace: platform
spec:
  project: genai
  source:
    repoURL: http://gitlab-ce.platform.svc.cluster.local/root/platform_monorepo.git
    targetRevision: HEAD
    path: charts/genai-infra
    helm:
      valueFiles:
        - values.yaml
        - values-k3d.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: genai
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
    # Manual sync — no automated block
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: genai-apps
  namespace: platform
  annotations:
    argocd.argoproj.io/sync-wave: "1"  # after infra
spec:
  project: genai
  source:
    repoURL: http://gitlab-ce.platform.svc.cluster.local/root/platform_monorepo.git
    targetRevision: HEAD
    path: charts/genai-apps
    helm:
      valueFiles:
        - values.yaml
        - values-k3d.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: genai
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
```

**`manifests/argocd-apps-platform.yaml`** (GitLab CE — after Spec 012):
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: gitlab-ce
  namespace: platform
spec:
  project: platform
  source:
    repoURL: http://gitlab-ce.platform.svc.cluster.local/root/platform_monorepo.git
    targetRevision: HEAD
    path: charts/gitlab-ce
    helm:
      valueFiles:
        - values.yaml
        - values-k3d.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: platform
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
```

### Phase 5: Taskfile Integration (FR-007)

**`taskfiles/argocd.yml`**:
```yaml
version: "3"

vars:
  ARGOCD_NS: platform
  ARGOCD_URL: 'http://argocd.platform.127.0.0.1.nip.io'
  CHARTS_DIR: '{{.ROOT_DIR}}/charts'
  MANIFESTS_DIR: '{{.ROOT_DIR}}/manifests'

tasks:
  deploy:
    desc: Install ArgoCD via Helm
    cmds:
      - helm repo add argo https://argoproj.github.io/argo-helm --force-update
      - >-
        helm upgrade --install argocd argo/argo-cd
        -f {{.CHARTS_DIR}}/argocd/values.yaml
        -f {{.CHARTS_DIR}}/argocd/values-k3d.yaml
        --namespace {{.ARGOCD_NS}} --create-namespace
        --wait --timeout 300s
      - echo "ArgoCD deployed at {{.ARGOCD_URL}}"
      - task: password

  teardown:
    desc: Uninstall ArgoCD
    prompt: "Remove ArgoCD from cluster?"
    cmds:
      - helm uninstall argocd --namespace {{.ARGOCD_NS}} --ignore-not-found

  status:
    desc: Show ArgoCD Application sync status
    cmds:
      - argocd app list --server {{.ARGOCD_URL}} --plaintext 2>/dev/null || kubectl get applications -n {{.ARGOCD_NS}}

  sync:
    desc: "Trigger sync for an app (usage: task argocd:sync -- genai-infra)"
    cmds:
      - argocd app sync {{.CLI_ARGS}} --server {{.ARGOCD_URL}} --plaintext

  password:
    desc: Get ArgoCD admin password
    cmds:
      - |
        kubectl -n {{.ARGOCD_NS}} get secret argocd-initial-admin-secret \
          -o jsonpath="{.data.password}" | base64 -d
        echo ""

  setup:
    desc: Apply AppProjects + Application manifests + repo secret
    cmds:
      - kubectl apply -f {{.MANIFESTS_DIR}}/argocd-appprojects.yaml
      - kubectl apply -f {{.MANIFESTS_DIR}}/argocd-apps-genai.yaml
      - kubectl apply -f {{.MANIFESTS_DIR}}/argocd-apps-platform.yaml
      - echo "Applications created. Sync manually: task argocd:sync -- genai-infra"

  open:
    desc: Print ArgoCD URL
    cmds:
      - echo "ArgoCD UI: {{.ARGOCD_URL}}"
      - echo "Login: admin / $(task argocd:password 2>/dev/null)"
```

### Phase 6: CLI Access (FR-008)

```bash
# Install
brew install argocd

# Login (after deploy)
argocd login argocd.platform.127.0.0.1.nip.io --plaintext --username admin --password $(task argocd:password)
```

Add to `task doctor`:
```yaml
- command -v argocd > /dev/null && echo "✓ argocd CLI" || echo "✗ argocd CLI (brew install argocd)"
- curl -sf http://argocd.platform.127.0.0.1.nip.io/healthz > /dev/null 2>&1 && echo "✓ ArgoCD healthy" || echo "○ ArgoCD not deployed"
```

## Bootstrap Sequence

```
1. task k3d:cluster-up          # k3d cluster + ingress-nginx
2. task argocd:deploy           # ArgoCD via Helm CLI (direct)
3. task gitlab:deploy           # GitLab CE via Helm CLI (direct, Spec 012)
4. task argocd:setup            # Create repo secret + AppProjects + Applications
5. task argocd:sync -- genai-infra   # First sync (manual)
6. task argocd:sync -- genai-apps    # Second sync (depends on infra)
```

After bootstrap, ArgoCD manages all releases. Future updates:
- Push to GitLab → ArgoCD detects drift → manual sync (or auto-sync if enabled)

## Fallback

All existing Helm CLI tasks continue to work:
- `task genai-helm:deploy` still does direct `helm upgrade --install`
- `task gitlab:deploy` still works
- ArgoCD is additive — if removed, everything still deploys manually

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| ArgoCD can't reach GitLab (chicken-and-egg) | Certain at bootstrap | Low | Bootstrap GitLab first via Helm CLI, ArgoCD manages it after |
| Auto-sync surprises during development | Medium | Medium | Default to manual sync; auto-sync is opt-in via values |
| ArgoCD Secret leaks GitLab PAT | Low | Medium | Secret not in git; created by `task argocd:setup` |
| App-controller OOM on large charts | Low | Low | Resource limits set; genai charts are moderate size |
| Repo polling misses fast commits | Low | Low | Manual `argocd app sync` or `argocd app refresh` |

## Estimated Effort

| Phase | Hours | Complexity |
|-------|-------|------------|
| 1. Helm values | 1h | Low (official chart, just values) |
| 2. Repo connection | 0.5h | Low (Secret template) |
| 3. AppProjects | 0.5h | Low (2 YAML manifests) |
| 4. Applications | 1h | Low-Medium (3 Application manifests, test sync) |
| 5. Taskfile | 1h | Low |
| 6. CLI + doctor | 0.5h | Trivial |
| **Total** | **4-5h** | |

## Dashboard Integration (Future)

The Observatory dashboard (`scripts/dashboard.py`) can query ArgoCD API for real-time sync status:
```
GET /api/v1/applications → sync status, health, revision
```
Add to `poll_platform()` alongside Helm and Terraform status. Show ArgoCD sync state on topology nodes.

## Open Questions (Resolved)

1. **Chicken-and-egg?** → Bootstrap GitLab via Helm CLI first. ArgoCD manages it after initial setup.
2. **Auto-sync?** → Manual by default. Add `--auto-sync` flag to `task argocd:setup` for opt-in.
3. **Image Updater?** → Not now. Overkill for local dev. Add later if needed.
4. **Depends on Spec 012?** → Partially. ArgoCD can be installed without GitLab (just uses different repo URL). Application manifests for GitLab CE require Spec 012 chart to exist.

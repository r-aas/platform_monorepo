# Implementation Plan: GitLab CE Helm Deployment

**Branch**: `012-gitlab-ce-helm` | **Date**: 2026-03-15 | **Spec**: `specs/012-gitlab-ce-helm/spec.md`

## Summary

Move GitLab CE from docker-compose on the Docker host into k3d via a custom Helm chart. The official `gitlab/gitlab` chart deploys ~20 microservices (webservice, sidekiq, gitaly, registry, kas, pages, etc.) requiring 8+ GB RAM minimum — far too heavy for local k3d. Instead, wrap the `gitlab/gitlab-ce:latest` omnibus image in a custom StatefulSet chart, matching the current docker-compose behavior. GitLab Runner gets its own Deployment using the official `gitlab/gitlab-runner` Helm chart with `kubernetes` executor (CI jobs run as pods).

## Technical Context

**Language/Version**: YAML (Helm templates), Bash (Taskfile tasks)
**Primary Dependencies**: `gitlab/gitlab-ce:latest` (omnibus), `gitlab/gitlab-runner` Helm chart
**Storage**: PVCs for GitLab config/data/logs (local-path provisioner → hostPath)
**Testing**: `task gitlab:status`, `curl readiness`, CI pipeline smoke test
**Target Platform**: k3d cluster "mewtwo" on Apple Silicon Mac (Colima 8 CPU / 32 GB / 100 GB)
**Constraints**: GitLab CE pod ~4 GB RAM, ~2.5 GB image, 5-minute startup time
**Scale/Scope**: Single-node local dev (1 GitLab instance, 1 Runner)

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Workflow-First | N/A | Infrastructure, not workflow logic |
| II. Test-First | PASS | Runner registration verified via CI pipeline test |
| III. Integration-First | PASS | End-to-end: push → CI → deploy → verify |
| VI. Infra as Config | PASS | Helm chart + values files, reproducible via `task gitlab:deploy` |
| VII. Local-First | PASS | All in k3d, no cloud dependencies |
| XI. Open-Source | PASS | Clone-and-run with `task gitlab:deploy` |

## Decision: Custom Chart vs Official Chart

**Official `gitlab/gitlab` chart** (REJECTED):
- Deploys 15-20 separate pods (webservice, sidekiq, gitaly, registry, migrations, kas, etc.)
- Minimum 8 GB RAM for small profile
- Complex RBAC, cert-manager, shared-secrets job
- Overkill for single-user local dev

**Custom omnibus wrapper chart** (CHOSEN):
- One StatefulSet running `gitlab/gitlab-ce:latest` (same as docker-compose)
- ConfigMap for `gitlab.rb` performance tuning
- Simple Service + Ingress
- Matches current behavior exactly — just moves from Docker host into k3d
- ~2 CPU / 4 GB RAM (same as docker-compose resource allocation)

**GitLab Runner**: Use official `gitlab/gitlab-runner` Helm chart (lightweight, well-maintained) with `kubernetes` executor instead of `docker` executor.

## Project Structure

### Source Code (platform_monorepo)

```text
charts/
├── gitlab-ce/
│   ├── Chart.yaml
│   ├── values.yaml            # defaults (image, resources, gitlab.rb)
│   ├── values-k3d.yaml        # k3d overrides (ingress hosts, storage class)
│   └── templates/
│       ├── _helpers.tpl
│       ├── statefulset.yaml    # GitLab CE omnibus
│       ├── service.yaml        # ClusterIP: web (8929→80), ssh (2222→22), registry (5050)
│       ├── ingress.yaml        # gitlab.mewtwo + registry.mewtwo
│       ├── configmap.yaml      # gitlab.rb performance tuning
│       ├── secret.yaml         # initial root password
│       └── pvc.yaml            # config, data, logs (if not using volumeClaimTemplates)
├── gitlab-runner/              # (optional wrapper or just direct dependency)
│   ├── Chart.yaml              # depends on official gitlab/gitlab-runner
│   ├── values.yaml
│   └── values-k3d.yaml

taskfiles/
└── gitlab.yml                  # UPDATED: Helm commands replace docker-compose

manifests/
└── gitlab-proxy.yaml           # DELETED (no longer needed)
```

### Key Files Changed

| File | Action | Purpose |
|------|--------|---------|
| `charts/gitlab-ce/` | CREATE | Custom Helm chart for omnibus GitLab |
| `charts/gitlab-runner/` | CREATE | Runner chart (wraps official or standalone values) |
| `taskfiles/gitlab.yml` | REWRITE | Replace docker-compose with helm upgrade/uninstall |
| `manifests/gitlab-proxy.yaml` | DELETE | Proxy no longer needed (GitLab is in-cluster) |
| `docker-compose.gitlab.yml` | KEEP (deprecated) | Keep as fallback, add deprecation comment |

## Architecture

```
                    k3d cluster "mewtwo"
┌─────────────────────────────────────────────────┐
│  namespace: platform                            │
│                                                 │
│  ┌──────────────────────┐  ┌──────────────────┐│
│  │  gitlab-ce           │  │  gitlab-runner    ││
│  │  (StatefulSet)       │  │  (Deployment)     ││
│  │                      │  │                   ││
│  │  omnibus image:      │  │  k8s executor:    ││
│  │  - web (80)          │  │  - spawns CI pods ││
│  │  - ssh (22)          │  │  - in platform ns ││
│  │  - registry (5050)   │  │  - Kaniko builds  ││
│  │  - sidekiq           │  │                   ││
│  │  - gitaly            │  └──────────────────┘│
│  │  - postgres (builtin)│                       │
│  └──────────┬───────────┘                       │
│             │                                   │
│  ┌──────────▼───────────┐                       │
│  │  Service: gitlab-ce  │                       │
│  │  80, 22, 5050        │                       │
│  └──────────┬───────────┘                       │
│             │                                   │
│  ┌──────────▼───────────┐                       │
│  │  Ingress (nginx)     │                       │
│  │  gitlab.mewtwo.nip.io│                       │
│  │  registry.mewtwo...  │                       │
│  └──────────────────────┘                       │
└─────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: GitLab CE Chart (FR-001)

Create `charts/gitlab-ce/` with:

**StatefulSet** (not Deployment — needs stable storage identity):
- Image: `gitlab/gitlab-ce:latest`
- 1 replica
- Ports: 80 (web), 22 (SSH), 5050 (registry)
- `volumeClaimTemplates`: config (1Gi), data (10Gi), logs (1Gi)
- `storageClassName: local-path`
- Resources: requests 1 CPU / 2Gi, limits 2 CPU / 4Gi
- Liveness/readiness: `GET /-/readiness` on port 80
- `initialDelaySeconds: 180` (omnibus takes 3-5 min to boot)
- Environment from ConfigMap (`GITLAB_OMNIBUS_CONFIG`)

**ConfigMap** (`gitlab.rb` as environment variable):
```ruby
external_url 'http://gitlab.platform.127.0.0.1.nip.io'
registry_external_url 'http://registry.platform.127.0.0.1.nip.io'
nginx['listen_port'] = 80
nginx['listen_https'] = false
registry_nginx['listen_port'] = 80
registry_nginx['listen_https'] = false
puma['workers'] = 2
sidekiq['concurrency'] = 5
postgresql['shared_buffers'] = '256MB'
prometheus_monitoring['enable'] = false
gitlab_rails['gitlab_shell_ssh_port'] = 2222
```

**Service**: ClusterIP exposing 80, 22, 5050

**Ingress** (class: nginx):
- `gitlab.platform.127.0.0.1.nip.io` → port 80
- `registry.platform.127.0.0.1.nip.io` → port 5050
- Annotations: `proxy-body-size: "0"`, `proxy-read-timeout: "900"`

**Secret**: Initial root password (auto-generated or from values)

### Phase 2: GitLab Runner (FR-002)

Two approaches — evaluate both:

**Option A**: Use official `gitlab/gitlab-runner` chart as dependency
- Add to `Chart.yaml` dependencies: `gitlab/gitlab-runner` from `https://charts.gitlab.io`
- Configure via `values.yaml`:
  ```yaml
  gitlab-runner:
    gitlabUrl: http://gitlab-ce.platform.svc.cluster.local
    runnerToken: ""  # set via Secret or values-k3d.yaml
    runners:
      executor: kubernetes
      kubernetes:
        namespace: platform
        image: alpine:latest
        privileged: false  # no DinD
        pullPolicy: IfNotPresent
  ```

**Option B**: Separate `charts/gitlab-runner/` wrapper chart
- More flexible, can include RBAC for kubernetes executor
- Recommended if we need custom ServiceAccount / ClusterRole for CI pods

**Recommendation**: Option A (dependency in gitlab-ce chart). Simpler. Runner auto-starts with GitLab.

**Runner auto-registration**: Runner needs a registration token. Options:
1. Pre-create via GitLab API after GitLab is healthy (init container or post-install hook)
2. Use `runnerRegistrationToken` in `gitlab.rb` (deprecated but works for CE)
3. Manual step: `task gitlab:runner-register -- TOKEN` (current approach, simplest for local dev)

**Recommendation**: Option 3 for now. Auto-registration adds complexity. Document the manual step in `task gitlab:setup`.

### Phase 3: Remove Docker-Compose Proxy (FR-003)

- Delete `manifests/gitlab-proxy.yaml` (Service + Endpoints + Ingress proxy)
- Add deprecation comment to `docker-compose.gitlab.yml`:
  ```yaml
  # DEPRECATED: GitLab now runs in k3d via Helm (task gitlab:deploy).
  # This file is retained as a fallback only.
  ```
- Do NOT delete docker-compose file yet — keep as documented fallback

### Phase 4: Registry Access (FR-004)

With GitLab in-cluster, the registry Service (`gitlab-ce.platform.svc.cluster.local:5050`) is directly reachable from all pods. No more:
- `/etc/hosts` hacks on k3d nodes
- `registries.yaml` TLS skip
- Static Endpoints with Docker gateway IP

**For k3d nodes pulling images**: The registry ingress at `registry.platform.127.0.0.1.nip.io` resolves to the ingress controller. k3d nodes can reach it directly via the cluster network. Still need `registries.yaml` to skip TLS (HTTP registry), but no `/etc/hosts` entry needed.

Update `task gitlab:setup-registry`:
```yaml
setup-registry:
  desc: Configure k3d nodes for GitLab registry (TLS skip only)
  cmds:
    - |
      # registries.yaml already handles TLS skip
      echo "Registry accessible via ingress — no /etc/hosts needed"
      kubectl get svc -n platform gitlab-ce
```

### Phase 5: CI Pipeline Compatibility (FR-005)

With kubernetes executor:
- CI jobs run as pods in `platform` namespace
- Kaniko builds: use `gcr.io/kaniko-project/executor:debug` image, same as before
- kubectl access: ServiceAccount with RBAC, no `host.docker.internal` needed
- Registry push: `registry.platform.127.0.0.1.nip.io` via ingress (same hostname, different route)

**Test**: Run counter-app CI pipeline after migration. Must pass:
- `secret-detection` (gitleaks)
- `build` (Kaniko)
- `deploy` (kubectl apply)
- `smoke-test` (curl via ingress)

### Phase 6: Taskfile Rewrite (FR-006)

Rewrite `taskfiles/gitlab.yml`:

| Task | Old (docker-compose) | New (Helm) |
|------|---------------------|------------|
| `deploy` | `docker compose up -d` + `kubectl apply proxy` | `helm upgrade --install gitlab-ce charts/gitlab-ce -n platform` |
| `stop` | `docker compose down` | `helm uninstall gitlab-ce -n platform` |
| `status` | `docker compose ps` + `kubectl get proxy` | `helm status gitlab-ce -n platform` + `kubectl get pods -n platform` |
| `logs` | `docker compose logs gitlab` | `kubectl logs -n platform -l app.kubernetes.io/name=gitlab-ce -f` |
| `password` | `docker exec gitlab grep Password ...` | `kubectl exec -n platform sts/gitlab-ce -- grep Password ...` |
| `runner-register` | `docker exec gitlab-runner ...` | `kubectl exec -n platform deploy/gitlab-runner -- ...` |
| `setup-registry` | `/etc/hosts` on k3d nodes | Verify ingress reachable (no hacks) |

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| GitLab omnibus too large for k3d ephemeral storage | Medium | High | Pre-pull image, ensure Colima disk has 20+ GB free |
| PVC data loss on cluster recreate | Low | High | local-path provisioner backs to host disk; verify persistence |
| Runner k8s executor needs RBAC | Certain | Low | Create ServiceAccount + Role for CI pods |
| GitLab 5-min startup blocks pipeline | Low | Medium | `--wait --timeout 600s` + readiness probe |
| Registry HTTP (no TLS) rejected by containerd | Low | Medium | `registries.yaml` TLS skip (already proven pattern) |

## Estimated Effort

| Phase | Hours | Complexity |
|-------|-------|------------|
| 1. GitLab CE chart | 3-4h | Medium (StatefulSet + ConfigMap + Ingress) |
| 2. Runner | 1-2h | Low (official chart as dependency) |
| 3. Remove proxy | 0.5h | Trivial |
| 4. Registry access | 1h | Low (verify, remove old hacks) |
| 5. CI compatibility | 2-3h | Medium (test full pipeline) |
| 6. Taskfile rewrite | 1h | Low |
| **Total** | **8-11h** | |

## Open Questions (Resolved)

1. **Official chart vs custom?** → Custom omnibus wrapper. Official chart is ~20 microservices, 8+ GB RAM.
2. **Runner executor?** → `kubernetes` (CI jobs as pods). Docker executor won't work inside k3d.
3. **Auto-registration?** → Manual for now. Document in `task gitlab:setup`.
4. **Keep docker-compose?** → Yes, as documented fallback. Don't delete yet.

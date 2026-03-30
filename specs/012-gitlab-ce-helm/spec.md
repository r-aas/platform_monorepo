<!-- status: shipped -->
<!-- note: Implemented in platform_monorepo charts/gitlab-ce/, deployed as Helm release rev 5 -->
# Spec 012: GitLab CE Helm Deployment

## Problem

GitLab CE currently runs via docker-compose on the Docker host (platform_monorepo), separate from the k3d cluster. A k8s ingress proxy with static Endpoints routes traffic from cluster to docker-compose. This works but creates operational friction:

- Two deployment models to manage (docker-compose + k3d Helm)
- Static Endpoints break when the Docker gateway IP changes after cluster recreate
- GitLab Runner config requires manual `extra_hosts` entries for registry access
- Registry access from k3d nodes requires `/etc/hosts` hacks on every node
- No GitOps integration — GitLab is unmanaged infrastructure

Moving GitLab CE into k3d via Helm chart unifies deployment, eliminates the proxy layer, and enables ArgoCD GitOps management (Spec 013).

## Constraints

- **Storage**: GitLab needs ~4GB for the omnibus image. k3d nodes need sufficient ephemeral storage. May require bumping k3d server node disk allocation.
- **PV data**: GitLab data (repos, registry, uploads) must persist across `helm uninstall` / cluster recreation via PVCs bound to `~/work/data/k3d/mewtwo/`.
- **Omnibus image**: `gitlab/gitlab-ce:latest` is large (~2.5GB). Pre-pull to avoid timeout during Helm install.
- **Performance tuning**: Same as current docker-compose — 2 puma workers, 5 sidekiq concurrency, 256MB shared buffers. Apply via `gitlab.rb` ConfigMap or Helm values.
- **Registry**: Built-in container registry must remain accessible from k3d nodes for CI image pulls.

## Requirements

### FR-001: GitLab CE Helm Chart
Create a Helm chart in `charts/gitlab-ce/` (platform_monorepo) that deploys GitLab CE as a StatefulSet in the `platform` namespace. Must include:
- GitLab CE container with persistent volumes for config, data, logs
- Service exposing web (8929), SSH (2222), registry (5050)
- Ingress rules for `gitlab.platform.127.0.0.1.nip.io` and `registry.platform.127.0.0.1.nip.io`
- ConfigMap for `gitlab.rb` performance tuning (puma workers, sidekiq, shared_buffers)
- values-k3d.yaml with local development defaults

### FR-002: GitLab Runner as Sidecar Deployment
Deploy GitLab Runner as a separate Deployment in the same namespace, configured to use the in-cluster GitLab instance. Runner must:
- Use `kubernetes` executor (not `docker`) since it's now inside k3d
- Auto-register with GitLab using a registration token Secret
- Support Kaniko builds (no Docker-in-Docker)
- Access the registry via in-cluster Service DNS

### FR-003: Remove Docker-Compose GitLab
Remove `docker-compose.gitlab.yml` from platform_monorepo and the `gitlab-proxy.yaml` ingress proxy manifest. Update all Taskfile tasks (`gitlab:deploy`, `gitlab:stop`, etc.) to use `helm upgrade --install`.

### FR-004: Registry Access Simplification
With GitLab in-cluster, k3d nodes access the registry via cluster-internal Service DNS — no more `/etc/hosts` hacks or registries.yaml TLS skip. Update `k3d-mewtwo.yaml` if needed.

### FR-005: CI Pipeline Compatibility
Existing `.gitlab-ci.yml` pipelines (e.g., counter-app) must continue working. GitLab Runner with kubernetes executor means CI jobs run as pods — verify:
- Kaniko image builds
- kubectl access to k3d API
- Smoke test execution
- Secret detection (gitleaks)

### FR-006: Taskfile Integration
Update `taskfiles/gitlab.yml` to replace docker-compose commands with Helm commands:
- `gitlab:deploy` → `helm upgrade --install`
- `gitlab:stop` → `helm uninstall`
- `gitlab:status` → `helm status` + `kubectl get pods`
- `gitlab:logs` → `kubectl logs`
- `gitlab:password` → `kubectl exec` to read initial root password

## Acceptance Scenarios

### SC-001: Fresh Install
Given a clean k3d cluster, when `task gitlab:deploy` runs, GitLab CE is accessible at `http://gitlab.platform.127.0.0.1.nip.io` within 5 minutes.

### SC-002: Data Persistence
Given a running GitLab with repos, when `helm uninstall gitlab-ce` then `helm install gitlab-ce`, all repos and users survive.

### SC-003: Registry Push/Pull
Given a CI pipeline, Kaniko can push images to `registry.platform.127.0.0.1.nip.io` and k3d pods can pull them without `/etc/hosts` workarounds.

### SC-004: Runner Registration
Given a fresh GitLab install, the runner auto-registers and can execute CI jobs within 2 minutes.

## Non-Functional Requirements

### NFR-001: Resource Limits
GitLab CE pod: 2 CPU / 4GB RAM limits. Runner pods: 1 CPU / 2GB RAM per CI job.

### NFR-002: Startup Time
GitLab CE must be healthy and serving requests within 5 minutes of `helm install`.

### NFR-003: No Breaking Changes
Existing genai-mlops stack (docker-compose) continues to work independently. GitLab migration is platform_monorepo scope only.

---
name: platform-helm-authoring
description: |
  Author Helm charts for the platform monorepo's k3d cluster. Use when creating new charts,
  adding services to ArgoCD, fixing chart failures, or debugging Helm template issues.
  Covers ARM64/amd64 awareness, Bitnami gotchas, values layering, and resource limits.
version: 1.0.0
---

# Platform Helm Chart Authoring

## Chart Location

All charts live in `charts/{name}/` in the platform monorepo. Each chart is an ArgoCD Application
managed by the `argocd-root` ApplicationSet.

## Values Layering

Every chart uses this file structure:

```
charts/{name}/
  Chart.yaml
  values.yaml           # defaults (arch-independent)
  values-arm64.yaml     # ARM64 overrides (Apple Silicon)
  values-amd64.yaml     # amd64 overrides (Intel/cloud/CI)
  values-k3d.yaml       # k3d-specific (local dev, lower resources)
  templates/
```

Helmfile applies them in order: `values.yaml` → `values-{arch}.yaml` → `values-k3d.yaml`.
ArgoCD ApplicationSets use `ignoreMissingValueFiles: true` so optional files are safe.

## ARM64 Compatibility Checklist

Before adding ANY image to a chart:

1. **Check ARM64 support**: `docker manifest inspect <image> | grep arm64`
2. **Known broken (use `platform: linux/amd64`)**:
   - `opensearchproject/opensearch:2.x` — JRE SIGILL (SVE on M4)
   - `docker.elastic.co/elasticsearch/elasticsearch:8.x` — same
   - Any image bundling OpenJDK 21.0.3–21.0.5 ARM64
3. **Known good**: postgres:16, apache/airflow:3, n8nio/n8n, bitnami/* (most), eclipse-temurin:21-jre-noble

When forcing amd64 in k8s, there is no `platform:` field. Instead:
```yaml
nodeSelector:
  kubernetes.io/arch: amd64
# OR use an init container / annotation for QEMU
```

For k3d (single-arch cluster), import pre-pulled amd64 images: `k3d image import <image>`

## Bitnami Image Deprecation

Bitnami removed human-readable tags from Docker Hub. Charts referencing specific tags like
`26.3.3-debian-12-r0` WILL fail.

**Fix**: Override image tag to `latest` in values, or use the Bitnami OCI registry:
```yaml
image:
  registry: registry-1.docker.io
  repository: bitnami/postgresql
  tag: latest  # or pin to a known-good digest
```

## Resource Limits

Always set resource requests/limits. k3d nodes have limited resources (8 CPU / 32 GB shared).

```yaml
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

**Known minimums**:
- Neo4j: 500m CPU, 2Gi memory (chart enforces)
- GitLab CE: 2 CPU, 4Gi (practical minimum)
- Airflow: 500m CPU, 1Gi per component

## sshfs / PVC Gotcha

k3d bind-mounts from Mac via Colima's sshfs. sshfs does NOT support `chown`.

**Impact**: Bitnami PostgreSQL (and any chart that chowns data dirs) fails. GitLab Omnibus
also fails (Chef reconfigure needs chown on /etc/gitlab).

**Fix**: Reconfigure local-path provisioner to use overlay FS instead of sshfs:

```bash
# 1. Create the directory on ALL k3d nodes first
for node in $(docker ps --filter name=k3d-mewtwo --format '{{.Names}}'); do
  docker exec $node mkdir -p /var/lib/rancher/k3s/local-storage
done

# 2. Patch the configmap
kubectl patch configmap local-path-config -n kube-system --type merge \
  -p '{"data":{"config.json":"{\"nodePathMap\":[{\"node\":\"DEFAULT_PATH_FOR_NON_LISTED_NODES\",\"paths\":[\"/var/lib/rancher/k3s/local-storage\"]}]}"}}'

# 3. Restart the provisioner
kubectl rollout restart deployment local-path-provisioner -n kube-system
```

**Trade-off**: Data on overlay FS doesn't survive node re-creation (vs sshfs which persists to host).

For charts needing persistent data across node recreation, use the bind-mount path BUT
set `containerSecurityContext.readOnlyRootFilesystem: false` and skip chown via
`volumePermissions.enabled: false` or `primary.podSecurityContext.fsGroup: null`.

## pgvector with Bitnami Chart

`pgvector/pgvector:pg16` is non-Bitnami. Needs:
```yaml
containerSecurityContext:
  readOnlyRootFilesystem: false
extraVolumes:
  - name: pg-run
    emptyDir: {}
extraVolumeMounts:
  - name: pg-run
    mountPath: /var/run/postgresql
```

## Adding a New Chart to ArgoCD

1. Create `charts/{name}/` with Chart.yaml, values.yaml, templates/
2. Add entry to `charts/argocd-root/values.yaml` under `gitWorkloads:`
3. Push to GitLab — ArgoCD auto-syncs

```yaml
# charts/argocd-root/values.yaml
gitWorkloads:
  - appName: my-service
    project: workloads        # platform-apps | genai | workloads
    path: charts/my-service
    namespace: dev            # dev | stage | prod | platform | genai
    syncWave: "0"
```

## ApplicationSet Gotchas

### Empty valueFiles
Empty string in `valueFiles` resolves to directory path → "is a directory" error.

**Fix**: Use `ignoreMissingValueFiles: true` with a fallback placeholder filename:
```yaml
ignoreMissingValueFiles: true
valueFiles:
  - values.yaml
  - values-{{ env "PLATFORM_ARCH" | default "arm64" }}.yaml
  - values-k3d.yaml
```

### Nested Go Templates
ArgoCD ApplicationSets use Go templates rendered in two passes: Helm renders outer templates,
ArgoCD renders inner (backtick-escaped) templates. Go template conditionals inside
backtick-escaped ApplicationSet templates break Helm YAML parsing.

**Fix**: Keep inner templates simple (variable substitution only). Move complex logic to
the values file or use separate value files per variant.

### PLATFORM_ARCH for Multi-Arch
Use `PLATFORM_ARCH` env var to select arch-specific values:
```yaml
valueFiles:
  - values.yaml
  - 'values-{{ env "PLATFORM_ARCH" | default "arm64" }}.yaml'
```

## Rationalizations to Reject

- "I'll just use the default Bitnami tag" — NO, check if it still exists on Docker Hub
- "ARM64 should work, it's Linux" — NO, verify with `docker manifest inspect`
- "I don't need resource limits for local dev" — NO, k3d shares 8 CPU / 32 GB across all services
- "I'll add the image and fix errors later" — NO, JRE SIGILL crashes show no useful error
- "I'll put conditionals in the backtick-escaped template" — NO, Helm can't parse nested Go template logic

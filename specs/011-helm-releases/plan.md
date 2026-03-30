# Implementation Plan: Helm Chart Packaging for k3d Deployment

**Branch**: `011-helm-releases` | **Date**: 2026-03-15 | **Spec**: [spec.md](spec.md)

## Summary

Package the genai-mlops stack as Helm charts for deployment to the shared k3d cluster "mewtwo". Two-tier umbrella architecture (infra + apps) using official community charts as dependencies where available. Charts and k3d overlays live in the platform monorepo. Both docker-compose and k8s deployments coexist. Phased migration: infra first, then observability, then applications.

## Technical Context

**Language/Version**: YAML (Helm templates), Bash (Taskfile automation)
**Primary Dependencies**: Helm v3, k3d, ingress-nginx, community Helm charts (see research.md)
**Storage**: k3s Local Path Provisioner → hostPath PVs under ~/work/data/k3d/mewtwo/
**Testing**: Smoke tests retargeted via BASE_URL; `helm test` for chart-level validation
**Target Platform**: k3d cluster "mewtwo" on macOS (Apple Silicon, Colima)
**Project Type**: Infrastructure-as-code (Helm charts + Taskfile automation)
**Constraints**: Ollama must stay bare-metal (GPU); both compose and k8s must coexist; Colima VM shared resources

## Constitution Check

| Gate | Status | Notes |
|------|--------|-------|
| VI. Infrastructure as Configuration | PASS | Helm charts are declarative config; `task helm:deploy` reproduces from scratch |
| VII. Local-First | PASS | All k3d, Ollama via host.docker.internal |
| II. Test-First | PASS | Each phase includes test verification before proceeding |
| III. Integration-First, No Mocking | PASS | Tests hit real k8s services |
| VIII. Component Selection | PASS | Helm charts are infrastructure glue → monorepo is correct home |
| I. Workflow-First | N/A | No n8n workflow changes |

## Project Structure

### Charts (platform monorepo)

```text
~/work/repos/platform_monorepo/
  charts/
    genai-infra/                    # Umbrella: infrastructure tier
      Chart.yaml                    # deps: minio, postgresql (x3), pgvector, neo4j
      values.yaml                   # production defaults
      values-k3d.yaml               # k3d local overrides (reduced resources, local-path PVs)
      templates/
        _helpers.tpl
        shared-secrets.yaml         # secrets consumed by app tier
        create-buckets-job.yaml     # post-install hook: minio buckets
        NOTES.txt
    genai-apps/                     # Umbrella: application tier
      Chart.yaml                    # deps: n8n, mlflow, litellm, langfuse, streaming-proxy, mcp-gateway
      values.yaml                   # production defaults
      values-k3d.yaml               # k3d local overrides
      templates/
        _helpers.tpl
        n8n-import-job.yaml         # post-install hook: workflow import
        n8n-workflows-configmap.yaml
        seed-prompts-job.yaml       # post-install hook: prompt seeding
        ingress.yaml                # nip.io ingress rules for all web services
        NOTES.txt
    litellm/                        # Local chart (custom config needed)
      Chart.yaml
      values.yaml
      templates/
        deployment.yaml
        service.yaml
        configmap.yaml              # litellm_config.yaml
    streaming-proxy/                # Local chart
      Chart.yaml
      values.yaml
      templates/
        deployment.yaml
        service.yaml
    mcp-gateway/                    # Local chart
      Chart.yaml
      values.yaml
      templates/
        deployment.yaml
        service.yaml
        rbac.yaml                   # needs Docker socket access
  taskfiles/
    helm.yml                        # existing — general helm tasks
    genai-helm.yml                  # NEW — genai-specific helm lifecycle
```

### Taskfile Hierarchy

```text
~/work/Taskfile.yml (symlink → platform_monorepo/Taskfile.yml)
  includes:
    k3d:        ~/work/taskfiles/k3d.yml          # cluster lifecycle
    helm:       ~/work/taskfiles/helm.yml          # generic helm tasks
    genai-helm: ~/work/taskfiles/genai-helm.yml    # NEW: genai deploy/status/teardown
    gitlab:     ~/work/taskfiles/gitlab.yml        # gitlab lifecycle
    ...

Per-repo (genai-mlops/Taskfile.yml):
  includes:
    uv:      ~/work/taskfiles/uv.yml
    compose: ~/work/taskfiles/compose.yml
    # genai-helm tasks accessed from platform level, not per-repo
```

**Design decision**: genai-helm tasks live at platform level because they operate on charts in the monorepo, not in genai-mlops. The genai-mlops repo owns compose; the monorepo owns k8s.

### Key Tasks (genai-helm.yml)

```yaml
tasks:
  deploy:
    desc: Deploy full genai stack to k3d (infra + apps)
    cmds:
      - task: infra-up
      - task: apps-up

  infra-up:
    desc: Deploy genai infrastructure tier
    cmds:
      - helm dependency update charts/genai-infra
      - >-
        helm upgrade --install genai-infra charts/genai-infra
        -f charts/genai-infra/values.yaml
        -f charts/genai-infra/values-k3d.yaml
        --namespace genai --create-namespace
        --wait --timeout 300s

  apps-up:
    desc: Deploy genai application tier
    cmds:
      - helm dependency update charts/genai-apps
      - >-
        helm upgrade --install genai-apps charts/genai-apps
        -f charts/genai-apps/values.yaml
        -f charts/genai-apps/values-k3d.yaml
        --namespace genai
        --wait --timeout 300s

  status:
    desc: Show genai Helm release status
    cmds:
      - helm list --namespace genai
      - kubectl get pods --namespace genai

  teardown:
    desc: Uninstall genai stack from k3d
    cmds:
      - helm uninstall genai-apps --namespace genai --ignore-not-found
      - helm uninstall genai-infra --namespace genai --ignore-not-found

  install:
    desc: Install a single stack (e.g., task genai-helm:install -- langfuse)
    cmds:
      - echo "Per-stack install not yet implemented for {{.CLI_ARGS}}"
```

## Chart Dependency Map

### genai-infra Chart.yaml dependencies

| Name | Repository | Condition | Notes |
|------|-----------|-----------|-------|
| minio | https://charts.min.io | minio.enabled | Single-node, 2 buckets (mlflow, langfuse) |
| n8n-postgresql | oci://bitnami/postgresql | n8n-postgresql.enabled | Aliased name |
| mlflow-postgresql | oci://bitnami/postgresql | mlflow-postgresql.enabled | Aliased name |
| langfuse-postgresql | oci://bitnami/postgresql | langfuse-postgresql.enabled | Aliased name |
| pgvector | oci://bitnami/postgresql | pgvector.enabled | Custom image: pgvector/pgvector, initdb extension |
| neo4j | https://helm.neo4j.com/neo4j | neo4j.enabled | Standalone mode |

### genai-apps Chart.yaml dependencies

| Name | Repository | Condition | Notes |
|------|-----------|-----------|-------|
| n8n | https://community-charts.github.io/helm-charts | n8n.enabled | Points to infra-tier postgres |
| mlflow | https://community-charts.github.io/helm-charts | mlflow.enabled | Points to infra-tier postgres + minio |
| langfuse | https://langfuse.github.io/langfuse-k8s | langfuse.enabled | Bundled ClickHouse+Redis; external postgres from infra |
| litellm | file://../litellm | litellm.enabled | Local chart |
| streaming-proxy | file://../streaming-proxy | streaming-proxy.enabled | Local chart |
| mcp-gateway | file://../mcp-gateway | mcp-gateway.enabled | Local chart |

### Global Values Pattern

```yaml
# genai-apps/values.yaml
global:
  inference:
    baseUrl: "http://host.docker.internal:11434/v1"
    apiKey: "ollama"
  minio:
    endpoint: "genai-infra-minio.genai.svc.cluster.local:9000"
    existingSecret: genai-minio-credentials
  langfuse:
    host: "http://genai-apps-langfuse.genai.svc.cluster.local:3000"
  mlflow:
    trackingUri: "http://genai-apps-mlflow.genai.svc.cluster.local:5050"
```

## Ingress Configuration

All web-facing services get ingress rules via nip.io:

| Service | Hostname | Backend Port |
|---------|----------|-------------|
| n8n | n8n.platform.127.0.0.1.nip.io | 5678 |
| MLflow | mlflow.platform.127.0.0.1.nip.io | 5050 |
| Langfuse | langfuse.platform.127.0.0.1.nip.io | 3000 |
| LiteLLM | litellm.platform.127.0.0.1.nip.io | 4000 |
| MinIO | minio.platform.127.0.0.1.nip.io | 9000 |
| MinIO Console | minio-console.platform.127.0.0.1.nip.io | 9001 |
| Neo4j | neo4j.platform.127.0.0.1.nip.io | 7474 |

Namespace: `genai` (not `dev` — dedicated namespace for this stack).

## Migration Phases

### Phase 1: Infrastructure Tier

Create `genai-infra` umbrella chart. Deploy PostgreSQL (x3) + MinIO + pgvector + Neo4j.

**Verification**: All pods Ready. `psql` connectivity. MinIO buckets created. pgvector extension loaded.

### Phase 2: Observability Tier

Add MLflow and Langfuse to `genai-apps` chart. Point at infra-tier databases.

**Verification**: MLflow UI via ingress. Langfuse health endpoint. LiteLLM callback logging works to both.

### Phase 3: Application Tier

Add n8n, LiteLLM, streaming-proxy, MCP gateway. Create local charts for custom services. Implement hook Jobs for n8n-import and prompt seeding.

**Verification**: n8n webhooks responding via ingress. Full smoke test suite passing against k8s endpoints. Dashboard topology showing k8s pods.

## Keeping Compose and k8s in Sync

| Aspect | docker-compose (genai-mlops repo) | Helm (platform monorepo) |
|--------|----------------------------------|-------------------------|
| Service definitions | docker-compose.yml | Chart values.yaml |
| Environment vars | .env / .env.example | values.yaml + Secrets |
| Health checks | healthcheck: in compose | livenessProbe/readinessProbe in chart |
| Resource limits | deploy.resources.limits | resources.requests/limits in chart |
| Init tasks | depends_on + init containers | Helm hooks (post-install Jobs) |
| Persistent data | Docker volumes | PVCs (local-path provisioner) |
| Port exposure | ports: mapping | Service + Ingress |
| Network | mlops-net bridge | k8s Service DNS |

**Sync strategy**: When a service config changes in docker-compose.yml, the corresponding Helm values.yaml must be updated in the same PR. The spec for each migration phase documents the mapping explicitly. `task doctor` checks both environments.

## Complexity Tracking

No constitution violations. This is infrastructure-as-configuration (Principle VI) deployed to the existing k3d cluster (Principle VII). All charts use community dependencies where available.

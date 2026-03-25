# Implementation Plan: DataHub Metadata Platform Integration

<!-- status: planned -->

**Branch**: `022-datahub-integration` | **Date**: 2026-03-25 | **Spec**: [spec.md](./spec.md)

## Summary

Deploy DataHub to the mewtwo k3d cluster via Helm (ArgoCD-managed), configure MLflow native ingestion via the built-in datahub-ingestion-cron subchart, build a FastAPI n8n-datahub bridge service for lineage emission, register the DataHub MCP server in the LiteLLM MCP mesh, and wire everything into the bootstrap lifecycle (build-images, smoke, urls).

## Technical Context

**Language/Version**: Python 3.12 (bridge service), YAML (Helm values, ingestion recipes), Bash (smoke/build scripts)
**Primary Dependencies**: datahub Helm chart v0.8.24 (appVersion v1.4.0.3), acryldata/mcp-server-datahub
**Storage**: Elasticsearch (search index), Kafka (event bus), MySQL (metadata SQL store) — all via datahub-prerequisites chart v0.2.3
**Testing**: Smoke tests (DataHub GMS /health, frontend reachable, MLflow entities ingested); unit tests for bridge service emitter
**Target Platform**: k3d ARM64 native (acryldata images publish linux/arm64 variants)
**Constraints**: Total DataHub RAM budget ~8Gi; prerequisites MySQL uses overlay FS PV (not sshfs bind-mount) to support fsGroup chown

## Constitution Check

- ARM64 native images only — verify acryldata images before deploying
- Overlay FS PV for MySQL (same pattern as genai-pg-*) — sshfs does not support chown
- All AI clients use LiteLLM proxy, not direct Ollama — DataHub MCP server registered in genai-litellm config
- No new per-project clusters — everything in genai namespace on mewtwo
- Custom images built via build-images.sh and imported into k3d — never pulled from public registry with pullPolicy: Always

## Design Decisions

### D1: Prerequisites — bundled vs shared databases
**Decision**: Use datahub-prerequisites chart (Elasticsearch, Kafka, MySQL) as a dedicated Helm release (`genai-datahub-prereqs`). Do not share existing postgres instances.
**Rationale**: DataHub's MySQL schema is version-locked. Sharing breaks on migrations. MySQL is not interchangeable with PostgreSQL for DataHub's JPA layer.

### D2: Search engine — Elasticsearch vs OpenSearch
**Decision**: Elasticsearch (prerequisites chart default, `elasticsearch-master` service name).
**Rationale**: OpenSearch on ARM64 has known SVE/JRE crashes (CLAUDE.md). Elasticsearch ARM64 is stable in the prerequisites chart version.

### D3: ArgoCD app registration
**Decision**: No explicit Application manifests needed. ArgoCD auto-discovers `charts/genai-datahub-prereqs/` and `charts/genai-datahub/` via the existing `applicationset-git.yaml` generator.
**Rationale**: The `workloads-git` ApplicationSet already watches `charts/*`. Both charts follow the `genai-*` naming convention → genai namespace, genai project.
**Sync-wave gap**: The ApplicationSet assigns wave 0 only to `genai-pg-*`, `genai-minio`, `genai-pgvector`. `genai-datahub-prereqs` is infrastructure but won't auto-get wave 0. Fix: add `genai-datahub-prereqs` to the wave-0 condition in `applicationset-git.yaml`.

### D4: Ingestion — datahub-ingestion-cron subchart (built-in)
**Decision**: Use the `datahub-ingestion-cron` subchart already bundled in the datahub chart. Enable it in `charts/genai-datahub/values.yaml` with the MLflow recipe inline.
**Rationale**: Avoids a separate chart. The subchart manages its own CronJob and ConfigMap. Custom ingestion image (`datahub-ingestion-mlflow:latest`) with `datahub[mlflow]` pre-installed is built via `build-images.sh`.

### D5: Bridge service architecture
**Decision**: FastAPI service at `services/n8n-datahub-bridge/`. Deployed as `charts/genai-datahub-bridge/`. Uses the same pattern as `services/agent-gateway` + `charts/genai-litellm`.
**Rationale**: Receives n8n webhook events (workflow execution metadata), translates to DataHub DataJob/DataProcessInstance MCPs via the `acryl-datahub` REST emitter SDK.

### D6: MCP server registration
**Decision**: Deploy `acryldata/mcp-server-datahub` as `charts/genai-mcp-datahub/`. Register as `datahub_metadata` in `charts/genai-litellm/values.yaml` `config.mcp_servers`.
**Rationale**: LiteLLM is the MCP mesh gateway. Same pattern as `kubernetes_ops`, `n8n_workflow_ops`, `gitlab_ops`. Agents query DataHub via LiteLLM tool routing.

## Project Structure

```text
charts/
├── genai-datahub-prereqs/       # Wrapper chart — datahub-prerequisites v0.2.3
│   ├── Chart.yaml               # dep: datahub-prerequisites from datahub Helm repo
│   ├── values.yaml              # Resource-constrained: ES 2Gi, Kafka 1Gi, MySQL 1Gi
│   └── values-k3d.yaml          # nip.io ingress overrides (if any)
├── genai-datahub/               # Wrapper chart — datahub v0.8.24
│   ├── Chart.yaml               # dep: datahub from datahub Helm repo
│   ├── values.yaml              # GMS 2Gi, frontend 1Gi, ingestion-cron enabled, MLflow recipe
│   └── values-k3d.yaml          # nip.io ingress for frontend (datahub.genai.127.0.0.1.nip.io)
├── genai-datahub-bridge/        # Wrapper chart — n8n-datahub bridge FastAPI service
│   ├── Chart.yaml
│   ├── values.yaml              # image: datahub-bridge:latest, pullPolicy: Never
│   ├── values-k3d.yaml
│   └── templates/               # Deployment, Service, Ingress, ConfigMap
├── genai-mcp-datahub/           # Wrapper chart — acryldata/mcp-server-datahub
│   ├── Chart.yaml
│   ├── values.yaml              # image, GMS_URL env var
│   └── templates/               # Deployment, Service

services/
└── n8n-datahub-bridge/          # FastAPI bridge service source
    ├── src/bridge/
    │   ├── __init__.py
    │   ├── main.py              # FastAPI app, /webhook/n8n endpoint
    │   ├── emitter.py           # acryl-datahub REST emitter, DataJob/DataProcessInstance MCPs
    │   ├── models.py            # Pydantic models — n8n execution event → DataHub MCP
    │   └── config.py            # Settings (DATAHUB_GMS_URL, DATAHUB_TOKEN)
    ├── tests/
    │   ├── test_emitter.py      # Unit tests (mock GMS)
    │   └── test_models.py       # Unit tests (n8n payload translation)
    ├── Dockerfile
    └── pyproject.toml           # uv-managed, Python 3.12

images/
└── datahub-ingestion-mlflow/    # Custom ingestion image
    └── Dockerfile               # FROM acryldata/datahub-ingestion-slim + pip install datahub[mlflow]

datahub/
└── recipes/
    └── mlflow.yml               # MLflow ingestion recipe (also inlined in values.yaml cron config)
```

## Changed Files (existing)

| File | Change |
|------|--------|
| `charts/argocd-root/templates/applicationset-git.yaml` | Add `genai-datahub-prereqs` to wave-0 condition |
| `charts/genai-litellm/values.yaml` | Add `datahub_metadata` MCP server entry |
| `scripts/build-images.sh` | Add `datahub-bridge` and `datahub-ingestion-mlflow` image entries |
| `scripts/smoke.sh` | Add DataHub GMS + frontend conditional checks |
| `Taskfile.yml` urls task | Add DataHub URL to printed list |

## Implementation Phases

### Phase 1: Infrastructure (Prerequisites + Core DataHub)
Charts for prerequisites and DataHub itself. Sync-wave fix in ApplicationSet. Verify all pods reach Running.

### Phase 2: MLflow Ingestion
Enable datahub-ingestion-cron subchart with MLflow recipe. Build custom ingestion image. Verify MLflow entities appear in DataHub.

### Phase 3: n8n-DataHub Bridge
FastAPI service with DataHub REST emitter. Unit tests for MCP translation. Helm chart + ArgoCD deployment.

### Phase 4: DataHub MCP Server
Deploy acryldata/mcp-server-datahub. Register in LiteLLM MCP mesh. Verify agents can search DataHub metadata.

### Phase 5: Bootstrap Integration
Update build-images.sh, smoke.sh, and Taskfile urls. Verify `task down && task up` completes with DataHub healthy.

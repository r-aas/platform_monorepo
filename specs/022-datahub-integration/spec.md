<!-- status: shipped -->

# Feature Specification: DataHub Metadata Catalog Integration

**Feature Branch**: `022-datahub-integration`
**Created**: 2026-03-25
**Status**: Planned

## Overview

Deploy DataHub as the platform's metadata catalog, wiring it into the mewtwo k3d cluster via Helm (ArgoCD-managed). The integration has four observable capabilities: MLflow entities are automatically ingested on a schedule, n8n workflow executions produce DataHub lineage records, agents can search the catalog via MCP tools, and DataHub is part of the standard `task up` bootstrap lifecycle.

**Why now**: The platform has MLflow for experiment tracking and n8n for workflow orchestration, but no unified metadata layer connecting them. DataHub provides the lineage graph, search, and catalog UI that ties those systems together. It also gives agents a structured data source to answer questions like "what models exist and what data trained them?"

## User Scenarios & Testing

### User Story 1 — MLflow Catalog Search (Priority: P1)

As a data scientist, I can search DataHub and find all my MLflow experiments, runs, and registered models — so I have a single place to discover what's been trained and tracked.

**Why this priority**: This is the primary value delivered by the integration. Without MLflow ingestion, DataHub is an empty catalog.

**Independent Test**: Trigger an ingestion CronJob manually, then search the DataHub UI for a known MLflow experiment name.

**Acceptance Scenarios**:

1. **Given** MLflow has at least one experiment with runs, **When** the ingestion CronJob completes, **Then** those entities appear in DataHub search with correct names and metadata
2. **Given** a new MLflow experiment is created, **When** the next scheduled ingestion runs (hourly), **Then** the experiment appears in DataHub within 65 minutes
3. **Given** the DataHub UI is open, **When** a user searches for an MLflow model name, **Then** the model's version history and associated runs are returned

---

### User Story 2 — n8n Lineage Tracking (Priority: P1)

As a platform engineer, every n8n workflow execution is recorded in DataHub as a DataProcessInstance — so I can trace which workflows ran, when, and what data they produced or consumed.

**Why this priority**: n8n workflows are the primary agentic workload on the platform. Without lineage, there's no audit trail for what agents did.

**Independent Test**: Trigger a workflow in n8n with a POST to the bridge webhook, then query the DataHub GMS REST API for a DataProcessInstance entity.

**Acceptance Scenarios**:

1. **Given** n8n posts an execution event to the bridge, **When** the bridge processes it, **Then** a DataProcessInstance entity exists in DataHub GMS within 10 seconds
2. **Given** a workflow execution has a parent workflow, **When** lineage is emitted, **Then** the DataJob → DataProcessInstance relationship is correctly set in the DataHub graph
3. **Given** the bridge is unreachable, **When** n8n attempts to post an event, **Then** n8n does not crash — the bridge failure is non-blocking

---

### User Story 3 — Agent Metadata Queries (Priority: P2)

As a platform engineer, the `agent:mlops` agent can answer questions about what's in the metadata catalog — so I can ask "what experiments ran last week?" or "what datasets feed model X?" without opening the UI.

**Why this priority**: Agents are the primary interaction surface. MCP tool access makes the catalog queryable conversationally.

**Independent Test**: Send a chat completion request to agent-gateway with a question about DataHub entities; verify the response references actual catalog content.

**Acceptance Scenarios**:

1. **Given** the DataHub MCP server is registered in LiteLLM, **When** `agent:mlops` receives a query about catalog contents, **Then** it uses the `datahub_metadata` MCP tool and returns a factual answer
2. **Given** DataHub is empty, **When** the agent queries for entities, **Then** it correctly reports "no entities found" rather than hallucinating

---

### User Story 4 — Zero-Touch Bootstrap (Priority: P1)

As a platform engineer, `task up` brings up DataHub automatically with no manual steps — so a fresh cluster has a working catalog after a single command.

**Why this priority**: Every service on the platform must survive `task down && task up`. Manual post-bootstrap steps are a maintenance debt that accumulates until something breaks.

**Independent Test**: Run `task down && task up && task smoke` on a clean state. Verify DataHub GMS and UI pass smoke checks without any manual intervention.

**Acceptance Scenarios**:

1. **Given** a fresh k3d cluster, **When** `task up` completes, **Then** `task smoke` shows DataHub GMS and UI as passing
2. **Given** cluster is destroyed and recreated, **When** `task up` runs, **Then** DataHub reaches healthy state with no manual steps
3. **Given** `task urls` is run, **When** output is printed, **Then** DataHub URL is included

---

### Edge Cases

- What if Elasticsearch fails to start due to ARM64 JRE issues? → Plan specifies Elasticsearch from the prerequisites chart — verify ARM64 compatibility before deploying. Known alternative: use the chart's bundled version which is tested against acryldata images.
- What if the MySQL PVC fails due to sshfs chown? → Use overlay FS storage class (`local-path`) for the prerequisites MySQL PV, same as genai-pg-*.
- What if the ingestion CronJob image is missing after cluster recreation? → `build-images.sh` must build and k3d-import `datahub-ingestion-mlflow:latest` before ArgoCD deploys the CronJob. This is enforced by the bootstrap order in `task up`.
- What if `mcp-server-datahub` doesn't publish an ARM64 image? → Add `platform: linux/amd64` to the chart values to force QEMU emulation.
- What if n8n cannot reach the bridge? → Bridge failures must be non-blocking for n8n. The n8n workflow posts to the bridge in a best-effort manner; failure is logged but does not fail the workflow.

## Requirements

### Functional Requirements

- **FR-001**: System MUST deploy DataHub prerequisites (Elasticsearch, Kafka, MySQL) as `genai-datahub-prereqs` Helm release in the `genai` namespace
- **FR-002**: System MUST deploy DataHub GMS and frontend as `genai-datahub` Helm release in the `genai` namespace
- **FR-003**: DataHub GMS MUST be reachable at `http://datahub-gms.genai.127.0.0.1.nip.io` and respond `{"status":"UP"}` at `/health`
- **FR-004**: DataHub frontend MUST be reachable at `http://datahub.genai.127.0.0.1.nip.io`
- **FR-005**: System MUST ingest MLflow experiments, runs, and registered models into DataHub on an hourly schedule via `datahub-ingestion-cron` subchart
- **FR-006**: Ingestion MUST use a custom image (`datahub-ingestion-mlflow:latest`) with `datahub[mlflow]` installed, built via `build-images.sh` and imported into k3d
- **FR-007**: System MUST provide a FastAPI bridge service (`n8n-datahub-bridge`) that accepts n8n execution webhook events and emits DataHub DataJob/DataProcessInstance MCPs
- **FR-008**: Bridge service MUST be deployed as `genai-datahub-bridge` in the `genai` namespace
- **FR-009**: System MUST deploy `acryldata/mcp-server-datahub` as `genai-mcp-datahub` in the `genai` namespace
- **FR-010**: DataHub MCP server MUST be registered in `charts/genai-litellm/values.yaml` as `datahub_metadata` with transport `http`
- **FR-011**: System MUST add DataHub health checks to `scripts/smoke.sh` (conditional on `genai-datahub` ArgoCD app existing)
- **FR-012**: System MUST add DataHub URL to the `task urls` output in `Taskfile.yml`
- **FR-013**: `genai-datahub-prereqs` MUST be assigned to ArgoCD sync-wave 0 (infrastructure tier) by updating `applicationset-git.yaml`
- **FR-014**: Prerequisites MySQL PVC MUST use `local-path` storage class (overlay FS) to support fsGroup chown — not the sshfs bind-mount path

### Key Entities

- **genai-datahub-prereqs**: Helm release wrapping `datahub-prerequisites` chart (Elasticsearch, Kafka, MySQL)
- **genai-datahub**: Helm release wrapping `datahub` chart (GMS, frontend, actions, ingestion-cron)
- **datahub-ingestion-mlflow**: Custom Docker image — `acryldata/datahub-ingestion-slim` + `datahub[mlflow]`
- **n8n-datahub-bridge**: FastAPI service translating n8n execution events to DataHub MCPs via `acryl-datahub` REST emitter SDK
- **genai-datahub-bridge**: Helm release deploying the bridge service
- **genai-mcp-datahub**: Helm release deploying `acryldata/mcp-server-datahub`
- **DataJob**: DataHub entity representing an n8n workflow definition
- **DataProcessInstance**: DataHub entity representing a single n8n workflow execution

## Non-Functional Requirements

- **Resource budget**: Total DataHub RAM budget ≤ 8Gi across all pods (GMS 2Gi, frontend 1Gi, Elasticsearch 2Gi, Kafka 1Gi, MySQL 1Gi, actions 512Mi)
- **ARM64 native**: All images MUST publish `linux/arm64` variants, or explicit `platform: linux/amd64` overrides MUST be set — no silent QEMU use
- **pullPolicy: Never for custom images**: `datahub-ingestion-mlflow` and `datahub-bridge` images MUST use `pullPolicy: Never` — they are built locally and k3d-imported, never pulled from a registry
- **No shared databases**: DataHub prerequisites use a dedicated MySQL instance — not the existing `genai-pg-*` PostgreSQL instances. DataHub's MySQL schema is version-locked and not interchangeable.
- **Idempotent bootstrap**: `task up` must produce the same result from zero, every time. DataHub deployment must not require any manual intervention after `task up`.
- **Bridge non-blocking**: Bridge failures MUST NOT cause n8n workflow failures. Lineage emission is best-effort.

## Success Criteria

- **SC-001**: DataHub GMS responds `{"status":"UP"}` at `/health` after `task up`
- **SC-002**: DataHub frontend returns HTTP 200 or 302 after `task up`
- **SC-003**: MLflow entities appear in DataHub GMS search within 65 minutes of ingestion CronJob schedule
- **SC-004**: A manually triggered ingestion job completes without errors and produces searchable entities
- **SC-005**: A test n8n webhook POST to the bridge results in a DataProcessInstance entity in DataHub GMS within 10 seconds
- **SC-006**: `agent:mlops` uses the `datahub_metadata` MCP tool when asked a catalog question
- **SC-007**: `task smoke` reports DataHub GMS and UI as passing after `task down && task up`
- **SC-008**: `task urls` output includes the DataHub URL
- **SC-009**: Bridge unit tests cover n8n payload → DataHub MCP translation with mocked GMS
- **SC-010**: All custom images are built and k3d-imported by `build-images.sh` before ArgoCD deploys dependent workloads

## Acceptance Criteria

1. `kubectl get pods -n genai | grep datahub` shows all pods Running after ArgoCD sync
2. `curl -s http://datahub-gms.genai.127.0.0.1.nip.io/health` returns `{"status":"UP"}`
3. `kubectl create job --from=cronjob/datahub-ingestion-cron-mlflow datahub-ingest-manual -n genai` completes with exit 0
4. DataHub GMS search query for "mlflow" returns non-empty results
5. POST to `http://genai-datahub-bridge.genai.svc.cluster.local:8000/webhook/n8n` with a synthetic execution event → DataProcessInstance entity queryable from GMS
6. `task smoke` exits 0 with DataHub checks passing
7. `uv run pytest` in `services/n8n-datahub-bridge/` passes all unit tests
8. `task down && task up` completes idempotently with DataHub healthy

## Out of Scope

- **DataHub authentication/authorization**: DataHub runs without authentication in local k3d. Production auth (OIDC, policies) is not in scope.
- **Neo4j graph backend**: Using Elasticsearch for the graph service (`graph_service_impl: elasticsearch`). Neo4j is disabled in the prerequisites chart.
- **Custom lineage UI or dashboards**: DataHub's built-in UI is the interface. No custom visualization is built.
- **OpenSearch**: Explicitly excluded due to ARM64 SVE/JRE crash issues (see CLAUDE.md). The prerequisites chart's Elasticsearch is used.
- **DataHub ingestion from sources other than MLflow**: Only MLflow ingestion is configured in this spec. Additional sources (PostgreSQL, Kafka topics, n8n as a platform source) are future work.
- **Production/stage DataHub deployments**: This spec targets the `genai` namespace on the mewtwo local cluster only.
- **DataHub metadata write-back to MLflow**: DataHub is read-only with respect to MLflow. The integration is one-directional (MLflow → DataHub).

## Reference

- DataHub Helm repo: `https://helm.datahubproject.io/`
- Chart versions: `datahub-prerequisites v0.2.3`, `datahub v0.8.24` (appVersion `v1.4.0.3`)
- MCP server: `acryldata/mcp-server-datahub`
- SDK: `acryl-datahub` (PyPI) for REST emitter in bridge service
- Implementation detail: [plan.md](./plan.md)
- Task breakdown: [tasks.md](./tasks.md)

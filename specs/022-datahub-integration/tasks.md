# Tasks: 022 — DataHub Metadata Platform Integration

**Input**: [plan.md](./plan.md)
**Prerequisites**: plan.md (complete), spec.md (pending — derive from task instructions)

---

## Phase 1: Infrastructure — Prerequisites + Core DataHub

**Purpose**: Get DataHub prerequisites (ES, Kafka, MySQL) and DataHub itself deployed and healthy in k3d.

**Checkpoint**: `kubectl get pods -n genai | grep datahub` — all pods Running; GMS responds at `/health`.

### T001 [P] Fix ApplicationSet sync-wave for genai-datahub-prereqs

- [ ] Impl: Edit `charts/argocd-root/templates/applicationset-git.yaml` — extend the wave-0 condition to include `genai-datahub-prereqs`
- **File**: `charts/argocd-root/templates/applicationset-git.yaml`
- **Note**: Current condition: `hasPrefix "genai-pg" | eq "genai-minio" | eq "genai-pgvector"`. Add `eq "genai-datahub-prereqs"`.

### T002 Create genai-datahub-prereqs wrapper chart

- [ ] Impl: `charts/genai-datahub-prereqs/Chart.yaml` — dep on `datahub-prerequisites` v0.2.3 from `https://helm.datahubproject.io/`
- [ ] Impl: `charts/genai-datahub-prereqs/values.yaml` — resource limits: elasticsearch.master 2Gi, kafka 1Gi, mysql 1Gi; persistence using overlay FS (`storageClass: local-path`); disable neo4j (not needed for ES-based graph)
- [ ] Impl: `charts/genai-datahub-prereqs/values-k3d.yaml` — k3d-specific overrides if needed (empty or minimal)
- **Files**: `charts/genai-datahub-prereqs/`
- **Depends on**: T001

### T003 Create genai-datahub wrapper chart

- [ ] Impl: `charts/genai-datahub/Chart.yaml` — dep on `datahub` v0.8.24 from `https://helm.datahubproject.io/`
- [ ] Impl: `charts/genai-datahub/values.yaml` — point at prerequisites services (`prerequisites-kafka:9092`, `elasticsearch-master:9200`, `prerequisites-mysql:3306`); GMS 2Gi, frontend 1Gi, actions 512Mi; `datahub-ingestion-cron.enabled: false` (enabled in Phase 2); service type ClusterIP (ingress via nginx)
- [ ] Impl: `charts/genai-datahub/values-k3d.yaml` — ingress: `datahub.genai.127.0.0.1.nip.io` for frontend; GMS ingress `datahub-gms.genai.127.0.0.1.nip.io`
- **Files**: `charts/genai-datahub/`
- **Depends on**: T002
- **Note**: `global.datahub.version` must match chart appVersion `v1.4.0.3`. Set `graph_service_impl: elasticsearch` (no Neo4j).

### T004 Verify DataHub deploys and reaches healthy state

- [ ] Test: After git push to in-cluster GitLab, ArgoCD syncs both apps. `kubectl get pods -n genai | grep datahub` → all Running
- [ ] Test: `curl -s http://datahub-gms.genai.127.0.0.1.nip.io/health` → `{"status":"UP"}`
- [ ] Test: `curl -s http://datahub.genai.127.0.0.1.nip.io` → 200/302 (frontend loads)
- **Depends on**: T003

---

## Phase 2: MLflow Ingestion

**Purpose**: Ingest MLflow experiments, runs, and models into DataHub's metadata catalog.

**Checkpoint**: Search DataHub UI for "mlflow" → finds datasets/pipelines. GMS REST confirms entities exist.

### T005 Build custom datahub-ingestion-mlflow image

- [ ] Impl: `images/datahub-ingestion-mlflow/Dockerfile` — `FROM acryldata/datahub-ingestion-slim:v1.4.0.3` + `pip install datahub[mlflow]`
- [ ] Impl: Add entry to `scripts/build-images.sh` IMAGES array: `"datahub-ingestion-mlflow:latest:${PLATFORM_DIR}/images/datahub-ingestion-mlflow/Dockerfile:${PLATFORM_DIR}/images/datahub-ingestion-mlflow"`
- **Files**: `images/datahub-ingestion-mlflow/Dockerfile`, `scripts/build-images.sh`
- **Note**: Use `pullPolicy: Never` in chart — image imported into k3d via build-images.sh

### T006 Write MLflow ingestion recipe

- [ ] Impl: `datahub/recipes/mlflow.yml` — source type `mlflow`, pointing at `http://genai-mlflow.genai.svc.cluster.local`; sink type `datahub-rest`, server `http://datahub-gms.genai.svc.cluster.local:8080`
- **File**: `datahub/recipes/mlflow.yml`

### T007 Enable datahub-ingestion-cron in genai-datahub chart

- [ ] Impl: Edit `charts/genai-datahub/values.yaml` — set `datahub-ingestion-cron.enabled: true`; configure `crons.mlflow` with `schedule: "0 * * * *"` (hourly), `recipe.fileContent` inline from T006, `image.repository: datahub-ingestion-mlflow`, `image.tag: latest`, `image.pullPolicy: Never`
- **File**: `charts/genai-datahub/values.yaml`
- **Depends on**: T005, T006

### T008 Verify MLflow entities appear in DataHub

- [ ] Test: Trigger ingestion manually via `kubectl create job --from=cronjob/datahub-ingestion-cron-mlflow datahub-ingest-manual -n genai`
- [ ] Test: `curl -s 'http://datahub-gms.genai.127.0.0.1.nip.io/entities?action=search' -d '{"input":"mlflow","entity":"dataset","start":0,"count":5}'` → non-empty results
- **Depends on**: T007

---

## Phase 3: n8n-DataHub Bridge Service

**Purpose**: Emit DataHub lineage MCPs from n8n workflow execution events (DataJob + DataProcessInstance).

**Checkpoint**: n8n webhook → bridge → DataHub GMS: DataProcessInstance entity created for a workflow execution.

### T009 [P] Scaffold bridge service

- [ ] Impl: `services/n8n-datahub-bridge/pyproject.toml` — `uv init`, Python 3.12, deps: `fastapi`, `uvicorn[standard]`, `acryl-datahub`, `pydantic-settings`
- [ ] Impl: `services/n8n-datahub-bridge/src/bridge/config.py` — `Settings(BaseSettings)` with `DATAHUB_GMS_URL`, `DATAHUB_TOKEN`, `SERVICE_PORT`
- **Files**: `services/n8n-datahub-bridge/`

### T010 [P] Implement n8n event Pydantic models

- [ ] Test: `services/n8n-datahub-bridge/tests/test_models.py` — test n8n execution payload → `DataJobUrn`, `DataProcessInstanceUrn` translation; write tests FIRST, verify fail
- [ ] Impl: `services/n8n-datahub-bridge/src/bridge/models.py` — `N8nExecutionEvent(BaseModel)`, `to_datahub_mcp()` method returning list of `MetadataChangeProposalWrapper`
- **Files**: `services/n8n-datahub-bridge/src/bridge/models.py`, `tests/test_models.py`
- **Depends on**: T009

### T011 Implement DataHub REST emitter

- [ ] Test: `services/n8n-datahub-bridge/tests/test_emitter.py` — mock GMS endpoint, verify MCP batch emitted; write tests FIRST, verify fail
- [ ] Impl: `services/n8n-datahub-bridge/src/bridge/emitter.py` — `DatahubRestEmitter` wrapper; `emit_execution_event(event: N8nExecutionEvent)` → translate + emit via `acryl-datahub` SDK
- **Files**: `services/n8n-datahub-bridge/src/bridge/emitter.py`, `tests/test_emitter.py`
- **Depends on**: T010

### T012 Implement FastAPI app

- [ ] Impl: `services/n8n-datahub-bridge/src/bridge/main.py` — FastAPI app; `POST /webhook/n8n` endpoint; `GET /health`; calls emitter; structured logging
- [ ] Impl: `services/n8n-datahub-bridge/Dockerfile` — `FROM python:3.12-slim`, `uv sync`, `CMD ["python", "-m", "uvicorn", "bridge.main:app"]`
- **Files**: `services/n8n-datahub-bridge/src/bridge/main.py`, `Dockerfile`
- **Depends on**: T011

### T013 Create Helm chart for bridge + add to build-images

- [ ] Impl: `charts/genai-datahub-bridge/Chart.yaml`, `values.yaml` (image: `datahub-bridge:latest`, pullPolicy: Never, port 8000, env: DATAHUB_GMS_URL, DATAHUB_TOKEN), `values-k3d.yaml` (ingress optional), `templates/` (Deployment, Service, ConfigMap for env)
- [ ] Impl: Add `datahub-bridge` entry to `scripts/build-images.sh`
- **Files**: `charts/genai-datahub-bridge/`, `scripts/build-images.sh`
- **Depends on**: T012

### T014 Verify bridge receives n8n webhook and emits to DataHub

- [ ] Test: Trigger test workflow in n8n configured to POST to `http://genai-datahub-bridge.genai.svc.cluster.local:8000/webhook/n8n`
- [ ] Test: Query DataHub GMS for DataProcessInstance entity → entity exists
- **Depends on**: T013

---

## Phase 4: DataHub MCP Server

**Purpose**: Enable agents to search and browse DataHub metadata via LiteLLM tool routing.

**Checkpoint**: `agent:mlops` answers "what MLflow experiments are in DataHub?" using DataHub MCP tools.

### T015 Create genai-mcp-datahub chart

- [ ] Impl: `charts/genai-mcp-datahub/Chart.yaml`, `values.yaml` (image: `acryldata/mcp-server-datahub:latest`, pullPolicy: IfNotPresent; env: `DATAHUB_URL=http://datahub-gms.genai.svc.cluster.local:8080`; service port 3000), `templates/` (Deployment, Service)
- **Files**: `charts/genai-mcp-datahub/`
- **Depends on**: T004
- **Note**: Verify `acryldata/mcp-server-datahub` publishes `linux/arm64` before deploying. If not, add `platform: linux/amd64`.

### T016 Register DataHub MCP server in LiteLLM

- [ ] Impl: Edit `charts/genai-litellm/values.yaml` — add entry to `config.mcp_servers`:
  ```yaml
  datahub_metadata:
    transport: "http"
    url: "http://genai-mcp-datahub.genai.svc.cluster.local:3000/mcp"
    description: "DataHub metadata catalog — search datasets, pipelines, lineage"
  ```
- **File**: `charts/genai-litellm/values.yaml`
- **Depends on**: T015

### T017 Verify agent can query DataHub via MCP

- [ ] Test: `curl http://agent-gateway.genai.127.0.0.1.nip.io/v1/chat/completions -d '{"model":"agent:mlops","messages":[{"role":"user","content":"what datasets are catalogued in datahub?"}]}'` → response references DataHub entities
- **Depends on**: T016

---

## Phase 5: Bootstrap Integration

**Purpose**: DataHub is part of the standard `task up` lifecycle — no manual steps after cluster creation.

**Checkpoint**: `task down && task up` completes with DataHub healthy in smoke results.

### T018 [P] Add DataHub checks to smoke.sh

- [ ] Impl: Edit `scripts/smoke.sh` — add conditional checks for `genai-datahub-prereqs` and `genai-datahub`:
  - `app_exists "genai-datahub" && http_check "http://datahub-gms.genai.127.0.0.1.nip.io/health" "DataHub GMS"`
  - `app_exists "genai-datahub" && http_check "http://datahub.genai.127.0.0.1.nip.io" "DataHub UI" 302`
- **File**: `scripts/smoke.sh`

### T019 [P] Add DataHub URL to task urls

- [ ] Impl: Edit `Taskfile.yml` urls task — add `echo "  DataHub:      http://datahub.genai.127.0.0.1.nip.io"`
- **File**: `Taskfile.yml`

### T020 End-to-end bootstrap verification

- [ ] Test: `task down && task up` completes without errors
- [ ] Test: `task smoke` shows DataHub GMS and UI passing
- [ ] Test: MLflow entities visible in DataHub UI after first CronJob run
- [ ] Test: Agent responds to DataHub metadata query
- **Depends on**: T001–T019

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1** (T001–T004): No dependencies — start here
- **Phase 2** (T005–T008): Depends on Phase 1 (DataHub must be running)
- **Phase 3** (T009–T014): Can start after Phase 1 (bridge doesn't need ingestion)
- **Phase 4** (T015–T017): Depends on Phase 1 (needs DataHub GMS reachable)
- **Phase 5** (T018–T020): Depends on all prior phases complete

### Parallel Opportunities

- T001, T002 can be written in parallel (different files)
- T009, T010 can be scaffolded in parallel (different files within bridge service)
- T018, T019 can be done in parallel (different files)
- Phase 3 and Phase 4 can proceed concurrently after Phase 1

---

## Notes

- DataHub prerequisites use `prerequisites-` prefix for service names (kafka: `prerequisites-kafka:9092`, mysql: `prerequisites-mysql:3306`) — match quickstart-values pattern from datahub-helm repo
- MySQL overlay FS PV: set `storageClass: local-path` in prerequisites values to avoid sshfs chown failure (same issue as Bitnami PostgreSQL)
- Ingestion image `pullPolicy: Never` — must be built and k3d-imported before ArgoCD deploys
- `datahub-ingestion-cron` CronJob name is `datahub-ingestion-cron-<key>` where key is the cron name in values (e.g., `mlflow`)
- DataHub frontend port is 9002, GMS port is 8080 — both exposed via ingress-nginx
- `mcp-server-datahub` ARM64 support: check `docker manifest inspect acryldata/mcp-server-datahub:latest | grep arm64` before T015

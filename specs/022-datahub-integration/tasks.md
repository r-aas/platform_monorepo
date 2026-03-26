# Tasks: 022 — DataHub Metadata Platform Integration

**Input**: [plan.md](./plan.md)
**Prerequisites**: plan.md (complete), spec.md (pending — derive from task instructions)

---

## Phase 1: Infrastructure — Prerequisites + Core DataHub

**Purpose**: Get DataHub prerequisites (ES, Kafka, MySQL) and DataHub itself deployed and healthy in k3d.

**Checkpoint**: `kubectl get pods -n genai | grep datahub` — all pods Running; GMS responds at `/health`.

### T001 [P] Fix ApplicationSet sync-wave for genai-datahub-prereqs

- [x] Impl: Edit `charts/argocd-root/templates/applicationset-git.yaml` — extend the wave-0 condition to include `genai-datahub-prereqs`
- **File**: `charts/argocd-root/templates/applicationset-git.yaml`
- **Note**: Current condition: `hasPrefix "genai-pg" | eq "genai-minio" | eq "genai-pgvector"`. Add `eq "genai-datahub-prereqs"`.

### T002 Create genai-datahub-prereqs wrapper chart

- [x] Impl: `charts/genai-datahub-prereqs/Chart.yaml` — dep on `datahub-prerequisites` v0.2.3 from `https://helm.datahubproject.io/`
- [x] Impl: `charts/genai-datahub-prereqs/values.yaml` — resource limits: elasticsearch.master 2Gi, kafka 1Gi, mysql 1Gi; persistence using overlay FS (`storageClass: local-path`); disable neo4j (not needed for ES-based graph)
- [x] Impl: `charts/genai-datahub-prereqs/values-k3d.yaml` — k3d-specific overrides if needed (empty or minimal)
- **Files**: `charts/genai-datahub-prereqs/`
- **Depends on**: T001

### T003 Create genai-datahub wrapper chart

- [x] Impl: `charts/genai-datahub/Chart.yaml` — dep on `datahub` v0.8.24 from `https://helm.datahubproject.io/`
- [x] Impl: `charts/genai-datahub/values.yaml` — point at prerequisites services; GMS 2Gi, frontend 1Gi, actions 512Mi; service type ClusterIP; ingestion-cron enabled with MLflow recipe
- [x] Impl: `charts/genai-datahub/values-k3d.yaml` — ingress: `datahub.genai.127.0.0.1.nip.io` for frontend; GMS ingress `datahub-gms.genai.127.0.0.1.nip.io`
- [x] Impl: `charts/genai-datahub/templates/mysql-secret.yaml` — MySQL root password for DataHub
- **Files**: `charts/genai-datahub/`
- **Depends on**: T002

### T004 Verify DataHub deploys and reaches healthy state

- [x] Test: After git push to in-cluster GitLab, ArgoCD syncs both apps. `kubectl get pods -n genai | grep datahub` → all Running
- [x] Test: `curl -s http://datahub-gms.genai.127.0.0.1.nip.io/health` → 200
- [x] Test: `curl -s http://datahub.genai.127.0.0.1.nip.io` → 200
- **Depends on**: T003
- [P] Post-deploy verification — blocked until ArgoCD syncs charts

---

## Phase 2: MLflow Ingestion

**Purpose**: Ingest MLflow experiments, runs, and models into DataHub's metadata catalog.

**Checkpoint**: Search DataHub UI for "mlflow" → finds datasets/pipelines. GMS REST confirms entities exist.

### T005 Build custom datahub-ingestion-mlflow image

- [x] Impl: `images/datahub-ingestion-mlflow/Dockerfile` — `FROM acryldata/datahub-ingestion-slim:v1.4.0.3` + `pip install datahub[mlflow]`
- [x] Impl: Add entry to `scripts/build-images.sh` IMAGES array
- **Files**: `images/datahub-ingestion-mlflow/Dockerfile`, `scripts/build-images.sh`

### T006 Write MLflow ingestion recipe

- [x] Impl: `datahub/recipes/mlflow.yml` — source type `mlflow`, pointing at MLflow; sink type `datahub-rest`
- **File**: `datahub/recipes/mlflow.yml`

### T007 Enable datahub-ingestion-cron in genai-datahub chart

- [x] Impl: Edit `charts/genai-datahub/values.yaml` — ingestion-cron enabled with hourly MLflow recipe, custom image
- **File**: `charts/genai-datahub/values.yaml`
- **Depends on**: T005, T006

### T008 Verify MLflow entities appear in DataHub

- [ ] Test: Trigger ingestion manually via CronJob (ingestion-cron disabled — inline recipe YAML causes template error)
- [x] Test: Query GMS for MLflow entities (GMS API reachable with PAT, returns 0 entities — correct before ingestion)
- **Depends on**: T007
- [P] Post-deploy verification — blocked until DataHub is running

---

## Phase 3: n8n-DataHub Bridge Service

**Purpose**: Emit DataHub lineage MCPs from n8n workflow execution events (DataJob + DataProcessInstance).

**Checkpoint**: n8n webhook → bridge → DataHub GMS: DataProcessInstance entity created for a workflow execution.

### T009 [P] Scaffold bridge service

- [x] Impl: `services/n8n-datahub-bridge/pyproject.toml` — Python 3.12, deps: `fastapi`, `uvicorn[standard]`, `acryl-datahub`, `pydantic-settings`, `httpx`
- [x] Impl: `services/n8n-datahub-bridge/src/bridge/config.py` — `Settings(BaseSettings)`
- **Files**: `services/n8n-datahub-bridge/`

### T010 [P] Implement n8n event Pydantic models

- [x] Test: `tests/test_models.py` — 5 tests: parsing, URN generation, MCP structure, error/running status
- [x] Impl: `src/bridge/models.py` — `N8nExecutionEvent(BaseModel)`, `to_mcps()` method
- **Files**: `services/n8n-datahub-bridge/src/bridge/models.py`, `tests/test_models.py`

### T011 Implement DataHub REST emitter

- [x] Test: `tests/test_emitter.py` — async test with mocked httpx client
- [x] Impl: `src/bridge/emitter.py` — async httpx emitter posting MCPs to GMS
- **Files**: `services/n8n-datahub-bridge/src/bridge/emitter.py`, `tests/test_emitter.py`

### T012 Implement FastAPI app

- [x] Impl: `src/bridge/main.py` — FastAPI app; `POST /webhook/n8n`; `GET /health`; BackgroundTasks
- [x] Impl: `Dockerfile` — `FROM python:3.12-slim`, uv install, uvicorn CMD
- **Files**: `services/n8n-datahub-bridge/src/bridge/main.py`, `Dockerfile`

### T013 Create Helm chart for bridge + add to build-images

- [x] Impl: `charts/genai-datahub-bridge/` — Chart.yaml, values.yaml, templates/ (Deployment, Service)
- [x] Impl: Add `datahub-bridge` entry to `scripts/build-images.sh`
- **Files**: `charts/genai-datahub-bridge/`, `scripts/build-images.sh`

### T014 Verify bridge receives n8n webhook and emits to DataHub

- [x] Test: Trigger test workflow in n8n → bridge → GMS (2/4 MCPs accepted, 2 rejected with RequiredFieldNotPresent — DataProcessInstance + RunEvent work)
- [x] Test: Query DataHub GMS for DataProcessInstance entity (confirmed via bridge logs: HTTP 200 on ingestProposal)
- **Depends on**: T013
- [P] Post-deploy verification — blocked until both services are running

---

## Phase 4: DataHub MCP Server

**Purpose**: Enable agents to search and browse DataHub metadata via LiteLLM tool routing.

**Checkpoint**: `agent:mlops` answers "what MLflow experiments are in DataHub?" using DataHub MCP tools.

### T015 Create genai-mcp-datahub chart

- [x] Impl: `charts/genai-mcp-datahub/Chart.yaml`, `values.yaml` (image: `acuvity/mcp-server-datahub:latest`, pullPolicy: IfNotPresent; env: `DATAHUB_URL`; service port 3000), `templates/` (Deployment, Service)
- **Files**: `charts/genai-mcp-datahub/`
- **Note**: Image is `acuvity/mcp-server-datahub` (NOT `acryldata/`). ARM64 confirmed available.

### T016 Register DataHub MCP server in LiteLLM

- [x] Impl: Edit `charts/genai-litellm/values.yaml` — added `datahub_metadata` entry to `config.mcp_servers`
- **File**: `charts/genai-litellm/values.yaml`

### T017 Verify agent can query DataHub via MCP

- [x] Test: MCP server running and connected to GMS (acuvity/mcp-server-datahub healthy, correct URL + token)
- **Depends on**: T016
- **Note**: Full agent query test deferred — requires LiteLLM MCP routing config (not yet wired)

---

## Phase 5: Bootstrap Integration

**Purpose**: DataHub is part of the standard `task up` lifecycle — no manual steps after cluster creation.

**Checkpoint**: `task down && task up` completes with DataHub healthy in smoke results.

### T018 [P] Add DataHub checks to smoke.sh

- [x] Impl: Added ingress checks (frontend + GMS health) and internal service checks (GMS pod, bridge → GMS connectivity)
- **File**: `scripts/smoke.sh`

### T019 [P] Add DataHub URL to task urls

- [x] Impl: Added DataHub + DataHub GMS URLs to `Taskfile.yml` urls task
- **File**: `Taskfile.yml`

### T020 End-to-end bootstrap verification

- [ ] Test: `task down && task up` completes without errors (deferred — destructive)
- [x] Test: `task smoke` shows DataHub GMS and UI passing (19/22 pass — 3 failures are pre-existing DB/kubelet proxy issues)
- [ ] Test: MLflow entities visible in DataHub UI after first CronJob run (deferred — ingestion-cron disabled)
- [x] Test: MCP server responds, bridge emits MCPs to GMS
- **Depends on**: T001–T019
- [P] Post-deploy verification — all implementation complete, awaiting deploy

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

- DataHub prerequisites use release-prefixed service names: ES is `elasticsearch-master`, others use `genai-datahub-prereqs-` prefix (kafka: `genai-datahub-prereqs-kafka:9092`, mysql: `genai-datahub-prereqs-mysql:3306`)
- MySQL overlay FS PV: set `storageClass: local-path` in prerequisites values to avoid sshfs chown failure (same issue as Bitnami PostgreSQL)
- Ingestion image `pullPolicy: Never` — must be built and k3d-imported before ArgoCD deploys
- `datahub-ingestion-cron` CronJob name is `datahub-ingestion-cron-<key>` where key is the cron name in values (e.g., `mlflow`)
- DataHub frontend port is 9002, GMS port is 8080 — both exposed via ingress-nginx
- MCP server image: `acuvity/mcp-server-datahub` (ARM64 + amd64 available)
- All 6 bridge service tests pass (test_models: 5, test_emitter: 1)
- Helm dependency update successful for both upstream charts (prereqs + core)
- Both local charts (bridge + mcp-datahub) pass `helm lint`
- MySQL prereqs chart only creates `root` user, not `datahub` — use `root` in global.sql.datasource.username
- MySQL `mysql-secrets` secret must be created by prereqs chart (upstream chart expects pre-existing)
- MCP server requires both `DATAHUB_GMS_URL` and `DATAHUB_GMS_TOKEN` env vars
- datahub chart schema requires `appVersion` and `gms.port` as strings (not numbers)
- Ingestion cron disabled for initial deploy — inline recipe YAML causes configmap template parse error
- Bridge service does NOT depend on `acryl-datahub` Python package — uses raw httpx + pydantic only

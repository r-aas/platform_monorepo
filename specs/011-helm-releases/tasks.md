# Tasks: Helm Chart Packaging for k3d Deployment

**Branch**: `011-helm-releases` | **Date**: 2026-03-15
**Plan**: [plan.md](plan.md) | **Spec**: [spec.md](spec.md)

## Prerequisites

- [x] k3d cluster "mewtwo" running (`task k3d:cluster-up`)
- [x] Helm v3 installed (`brew install helm`)
- [x] Ollama running on host (`brew services start ollama`)
- [ ] genai-mlops docker-compose stack running (for reference/comparison)

---

## Phase 1: Infrastructure Tier ✅

### Task 1.1: Create chart scaffold in platform monorepo ✅

**Files**: `~/work/repos/platform_monorepo/charts/` directory structure
**Test**: `helm lint charts/genai-infra` passes
**Commit**: `63a39ad` (platform_monorepo)

1. ✅ Created: `charts/genai-infra/`, `charts/litellm/`, `charts/streaming-proxy/`, `charts/mcp-gateway/`
2. ✅ genai-infra Chart.yaml with deps: minio, postgresql×3, pgvector, neo4j
3. ✅ values.yaml with production defaults; pgvector needs `readOnlyRootFilesystem: false` + emptyDir for `/var/run/postgresql`
4. ✅ values-k3d.yaml: local-path storageClass (on overlay FS, NOT sshfs), nip.io ingress, Neo4j min 500m/2Gi
5. ✅ templates/_helpers.tpl + NOTES.txt
6. ✅ `helm dependency update` downloaded all 6 deps
7. ✅ `helm lint` passes clean

### Task 1.2: Shared secrets and init hooks — DEFERRED

MinIO buckets created via Bitnami chart's built-in `buckets:` config. PostgreSQL passwords inline in values.yaml (acceptable for local dev). pgvector extension via `initdb.scripts`. No custom hook Jobs needed for local k3d deployment.

### Task 1.3: Deploy and verify infrastructure tier ✅

**Result**: All 6 pods Running. All databases verified. MinIO buckets created. pgvector v0.8.2 loaded.

**Gotchas encountered and resolved:**
- Colima VM disk full (48G/48G) → resized to 100GB
- k3s NodePort allocator corrupted → `docker restart k3d-mewtwo-server-0`
- Bitnami PG chown fails on sshfs → reconfigured local-path provisioner to overlay FS
- pgvector read-only filesystem → `readOnlyRootFilesystem: false` + emptyDir

### Task 1.4: Write genai-helm Taskfile ✅

**File**: `taskfiles/genai-helm.yml`
**Tasks**: deploy, infra-up, apps-up, infra-down, apps-down, status, teardown, lint, template, logs

---

## Phase 2: Observability Tier ✅

### Task 2.1: Create genai-apps umbrella chart ✅

**Files**: `charts/genai-apps/Chart.yaml`, `values.yaml`, `values-k3d.yaml`
**Commit**: `63a39ad` (platform_monorepo)

All 6 dependencies in one umbrella: n8n, mlflow, langfuse, litellm, streaming-proxy, mcp-gateway.

**Key schema gotchas discovered:**
- n8n: uses `externalPostgresql` (NOT `externalDatabase`) + `db.type: postgresdb`
- MLflow: uses `backendStore.postgres`, `artifactRoot.s3`, `extraEnvVars` (dict, not array)
- Langfuse: subchart service names don't include parent prefix — must set explicit `clickhouse.host: "genai-apps-clickhouse"` and `redis.host: "genai-apps-redis-primary"`
- Langfuse requires `langfuse.salt.value` and `langfuse.nextauth.secret.value`
- LiteLLM: use `main-latest` tag (specific dev tags get removed from ghcr.io)

### Task 2.2: Deploy and verify observability ✅

**Result**: MLflow UI at ingress (403 = auth enabled, working). Langfuse v3.158.0 OK. LiteLLM "I'm alive!".

---

## Phase 3: Application Tier ✅

### Task 3.1: Create custom local charts ✅

All three local charts created and linted: litellm, streaming-proxy, mcp-gateway.
Streaming-proxy and mcp-gateway disabled by default (streaming-proxy needs custom image, mcp-gateway needs Docker socket).

### Task 3.2: Add n8n and custom services to apps chart ✅

n8n + all local charts added to genai-apps umbrella. n8n workflow import and prompt seeding hooks DEFERRED — n8n is running empty for now (manual workflow import via UI or API).

### Task 3.3: Deploy and verify full stack ✅

**Result**: 18 pods across both tiers. All Running. Services verified via ingress:
- n8n: 200 OK at `n8n.platform.127.0.0.1.nip.io`
- MLflow: 403 (auth enabled) at `mlflow.platform.127.0.0.1.nip.io`
- Langfuse: OK v3.158.0 at `langfuse.platform.127.0.0.1.nip.io`
- LiteLLM: "I'm alive!" via internal DNS
- MinIO Console: 200 at `minio-console.platform.127.0.0.1.nip.io`

**Note on DNS/port-forwarding**: Zero manual config needed. k3d port mapping (80/443 → loadbalancer) + nip.io wildcard DNS + ingress-nginx with `hostPort.enabled=true` handles everything automatically. Any new service just needs an Ingress resource.

### Task 3.4: Dashboard k8s integration ✅

**Files**: `scripts/dashboard.py`, `scripts/dashboard-static/topology.js`, `scripts/dashboard-static/panels.js`, `scripts/dashboard-static/styles.css`
**Commit**: `e812d4a` (genai-mlops)

Implemented:
1. ✅ Async kubectl polling (`kubectl get pods -n genai -o json` + `kubectl top pods`)
2. ✅ K8S_POD_TO_NODE mapping (pod name prefix → logical service ID)
3. ✅ Dual-mode topology: docker nodes (blue, left) + k8s nodes (purple, right) + shared Ollama (center)
4. ✅ New `k8s` deploy style with purple border/badge
5. ✅ Graceful degradation: if kubectl unavailable, only docker nodes shown
6. ✅ k8s pod details table in Services tab (pod name, phase, ready, restarts, CPU, mem)
7. ✅ DUAL MODE indicator in legend when both environments detected
8. ✅ Dynamic topology — only shows nodes for services that are actually running

**Verified**: 26 nodes (1 host + 13 docker + 12 k8s), 27 edges, metrics-server CPU data flowing

### Task 3.5: Terraform module for declarative deployment ✅

**Files**: `terraform/` directory in platform_monorepo
**Commit**: `24bfbf8` (platform_monorepo)

Terraform root module using Helm + Kubernetes providers to manage the same charts declaratively:
- `terraform apply -var-file=environments/k3d.tfvars` deploys to local k3d
- `aws.tfvars.example` scaffolds future cloud deployment path
- Taskfile integration: `task genai-helm:tf-init`, `tf-plan`, `tf-apply`, `tf-destroy`

---

## Phase 4: Sync and Documentation

### Task 4.1: Doctor check for both environments — DEFERRED

Will update `task doctor` in genai-mlops to optionally check k8s when cluster available.

### Task 4.2: Update RESUME.md and commit

1. [ ] Update RESUME.md with Helm deployment instructions
2. [x] Commit chart files in platform_monorepo (`63a39ad`)
3. [x] Update spec status to `in-progress`
4. [x] Commit spec updates + dashboard k8s integration in genai-mlops (`e812d4a`)
5. [x] Commit Terraform module in platform_monorepo (`24bfbf8`)
6. [ ] Final commit with completed spec status

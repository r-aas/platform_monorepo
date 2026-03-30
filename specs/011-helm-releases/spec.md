<!-- status: shipped -->

# Feature Specification: Helm Chart Packaging for k3d Deployment

**Feature Branch**: `011-helm-releases`
**Created**: 2026-03-15
**Status**: Shipped
**Input**: Helm chart packaging for deploying genai-mlops stacks to k3d cluster. Both docker-compose AND k8s deployments coexist. Stack grouping maps to namespaces. Ollama stays bare-metal on host.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deploy Full Stack to k3d (Priority: P1)

As a platform operator, I want to deploy the entire genai-mlops stack to the shared k3d cluster so that I have a production-like environment running alongside my docker-compose dev environment.

**Why this priority**: This is the core capability — without it, nothing else matters. A single `task helm:deploy` should bring the full stack up in k3d with all services healthy.

**Independent Test**: Deploy all Helm releases to k3d `dev` namespace, run `task doctor` equivalent against k8s endpoints, verify all services are healthy and interconnected.

**Acceptance Scenarios**:

1. **Given** the k3d cluster "mewtwo" is running, **When** I run `task helm:deploy`, **Then** all 7 Helm releases are installed in the `dev` namespace and all pods reach Ready state within 5 minutes.
2. **Given** all releases are deployed, **When** I run `task helm:status`, **Then** I see all releases with their status, pod count, and health summary.
3. **Given** the stack is deployed, **When** I access services via nip.io URLs (e.g., `n8n.platform.127.0.0.1.nip.io`), **Then** each service responds through ingress-nginx.
4. **Given** Ollama is running natively on the host, **When** k8s pods reference the LLM endpoint, **Then** they reach Ollama via `host.docker.internal:11434`.

---

### User Story 2 - Per-Stack Lifecycle Management (Priority: P1)

As a developer, I want to deploy, upgrade, and tear down individual stacks independently so that I can iterate on one component without affecting the rest.

**Why this priority**: Equally critical — the whole point of Helm releases is independent lifecycle management per stack. Deploying the entire platform every time defeats the purpose.

**Independent Test**: Deploy only the Langfuse stack, verify it comes up with all 5 pods healthy. Upgrade it with changed values. Tear it down without affecting other stacks.

**Acceptance Scenarios**:

1. **Given** no releases are deployed, **When** I run `task helm:install -- langfuse`, **Then** only the Langfuse stack (langfuse, langfuse-worker, langfuse-postgres, langfuse-clickhouse, langfuse-redis) is deployed.
2. **Given** Langfuse is deployed, **When** I change a Helm value and run `task helm:upgrade -- langfuse`, **Then** only affected pods restart and the release version increments.
3. **Given** all stacks are deployed, **When** I run `task helm:uninstall -- langfuse`, **Then** only Langfuse pods are removed; n8n, MLflow, and other stacks remain healthy.
4. **Given** a stack has persistent volumes, **When** I uninstall and reinstall the stack, **Then** data persists across the reinstall cycle.

---

### User Story 3 - Coexistence with Docker Compose (Priority: P2)

As a developer, I want both docker-compose and k3d deployments to coexist on my machine so that I can use compose for rapid iteration and k3d for production-like testing.

**Why this priority**: The existing compose workflow is proven and fast. k3d adds value for testing k8s-specific behavior but should not replace compose for daily development.

**Independent Test**: Run the compose stack AND the k3d stack simultaneously. Verify they don't conflict on ports, volumes, or service names.

**Acceptance Scenarios**:

1. **Given** docker-compose stack is running on standard ports, **When** I deploy to k3d, **Then** k3d services are accessible via different ports (ingress on 80/443) and nip.io hostnames, with no port conflicts.
2. **Given** both environments are running, **When** I run `task doctor`, **Then** it reports health for both docker-compose services AND k3d deployments.
3. **Given** compose is using Ollama on localhost:11434, **When** k3d pods also use Ollama, **Then** both environments share the same Ollama instance via different network paths (localhost vs host.docker.internal).

---

### User Story 4 - Dashboard Topology Reflects k8s State (Priority: P3)

As an operator, I want the Platform Observatory dashboard to show the k8s deployment topology so that I can monitor both compose and k3d environments from one view.

**Why this priority**: Visibility into the k8s deployment rounds out the observability story, but the dashboard already works for compose. This extends it.

**Independent Test**: With k3d stack deployed, open the dashboard and verify the topology view shows k8s pods with their actual status, resource usage, and namespace grouping.

**Acceptance Scenarios**:

1. **Given** the k3d stack is deployed, **When** I view the dashboard topology tab, **Then** I see nodes grouped by stack (namespace) with k8s-specific metadata (pod status, restart count, node).
2. **Given** a pod is crashing in k3d, **When** I view the dashboard, **Then** the affected node shows red/degraded status with the crash reason.

---

### Edge Cases

- What happens when the k3d cluster doesn't exist? Helm commands should fail with a clear error message directing the user to run `task k3d:cluster-up`.
- What happens when a dependent stack isn't deployed yet (e.g., deploying n8n before its postgres)? The Helm chart should include init containers or dependency checks that wait for prerequisites.
- What happens when Ollama is not running on the host? Pods depending on LLM inference should show degraded health, not crash loop.
- What happens when the Colima VM doesn't have enough resources for both compose and k3d? The doctor check should warn about resource contention.
- What happens when persistent volume data from compose needs to be used in k3d? This is explicitly out of scope — each environment has its own data.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST package each logical stack as an independent Helm chart that can be installed, upgraded, and uninstalled independently.
- **FR-002**: System MUST define 7 Helm releases: n8n, mlflow, langfuse, litellm, streaming-proxy, mcp-gateway, knowledge.
- **FR-003**: Each Helm chart MUST include liveness and readiness probes matching the existing docker-compose healthcheck definitions.
- **FR-004**: Each Helm chart MUST include resource requests and limits matching the existing docker-compose deploy.resources.limits.
- **FR-005**: Helm charts MUST support persistent volumes using the k3d bind-mount storage at `~/work/data/k3d/mewtwo/`.
- **FR-006**: Services requiring LLM access MUST connect to Ollama on the host via `host.docker.internal:11434` (bare-metal, never containerized).
- **FR-007**: All inter-service connectivity MUST work within the k8s cluster using k8s Service DNS (e.g., `langfuse-postgres.dev.svc.cluster.local`).
- **FR-008**: Each stack MUST be accessible via ingress-nginx with nip.io hostnames following the pattern `{service}.{namespace}.127.0.0.1.nip.io`.
- **FR-009**: Shared storage (MinIO) MUST be deployable as its own release or bundled within stacks that need it, configurable via Helm values.
- **FR-010**: Taskfile automation MUST provide commands for full-stack and per-stack deploy, upgrade, status, and teardown.
- **FR-011**: Environment secrets MUST be injected via Kubernetes Secrets, not hardcoded in chart values.
- **FR-012**: Init containers (n8n-import, create-bucket) MUST be modeled as Helm hooks or init containers in the chart.
- **FR-013**: The dashboard MUST be updated to optionally poll k8s pod status when the cluster is available.

### Key Entities

- **Helm Release**: A deployed instance of a Helm chart in a namespace. Has a name, version, status, and values override.
- **Stack**: A logical grouping of k8s resources (Deployment, Service, PVC, ConfigMap, Secret) that together form one platform component.
- **Namespace**: The k8s isolation boundary for a deployment environment (dev, stage, prod).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 7 Helm releases deploy successfully to the k3d cluster with all pods healthy within 5 minutes of `task helm:deploy`.
- **SC-002**: Any individual stack can be upgraded or rolled back in under 60 seconds without affecting other stacks.
- **SC-003**: Docker-compose and k3d deployments run simultaneously on the same machine without port or resource conflicts.
- **SC-004**: Service health endpoints are reachable via nip.io ingress URLs from the host browser.
- **SC-005**: Data persists across stack uninstall/reinstall cycles via k3d PersistentVolumes.
- **SC-006**: The existing smoke test suite can target either docker-compose or k3d endpoints by switching a base URL variable.

## Assumptions

- The k3d cluster "mewtwo" is already provisioned via `task k3d:cluster-up` with ingress-nginx and namespace init.
- Ollama is running as a native host process and is reachable from k3d pods via `host.docker.internal`.
- The Colima VM has sufficient resources (8+ CPU, 32+ GB RAM) to run both compose and k3d workloads.
- Helm v3 is installed on the host (available via `brew install helm`).
- The genai-mlops stack will deploy to the `dev` namespace by default, with `stage` and `prod` as future targets.
- MinIO will be deployed as a shared release rather than duplicated per-stack, to avoid storage overhead.

## Scope Boundaries

**In scope**:
- Helm chart creation for all 7 stacks
- Taskfile automation for Helm lifecycle
- Ingress configuration for all web-facing services
- PersistentVolume setup for stateful services
- Dashboard integration for k8s topology view

**Out of scope**:
- ArgoCD GitOps integration (future spec)
- CI/CD pipeline for Helm deployments (future spec)
- Multi-cluster or remote cluster deployment
- Data migration between compose and k8s environments
- TLS/cert-manager setup (plain HTTP via nip.io for local dev)

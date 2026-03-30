# Research: Helm Charts for genai-mlops

## Existing Official Helm Charts

Every major service has an existing chart. Use as dependencies, don't rewrite.

| Service | Chart | Repository | Notes |
|---------|-------|-----------|-------|
| n8n | community-charts/n8n | `https://community-charts.github.io/helm-charts` | v1.15.2, 8gears maintained |
| MLflow | community-charts/mlflow | `https://community-charts.github.io/helm-charts` | v1.8.1 (app v3.7.0), S3+PG backend |
| Langfuse | langfuse/langfuse | `https://langfuse.github.io/langfuse-k8s` | v1.2.1, bundles ClickHouse+Redis+PG as sub-deps |
| LiteLLM | berriai/litellm-helm | `oci://ghcr.io/berriai/litellm-helm` | v0.1.2, or RichardoC/litellm_helm-chart |
| MinIO | minio/minio | `https://charts.min.io` | Official v5.4.0, single-node mode for dev |
| Neo4j | neo4j/neo4j | `https://helm.neo4j.com/neo4j` | Official, standalone mode |
| PostgreSQL | bitnami/postgresql | `oci://registry-1.docker.io/bitnamicharts/postgresql` | Standard. 3 separate releases for isolation |
| pgvector | bitnami/postgresql + custom image | Same chart, override image with pgvector/pgvector | initdb.scripts for CREATE EXTENSION vector |
| ClickHouse | bitnami/clickhouse | `oci://registry-1.docker.io/bitnamicharts/clickhouse` | Langfuse chart bundles this |
| Redis | bitnami/redis | `oci://registry-1.docker.io/bitnamicharts/redis` | Langfuse chart bundles this |

## Decision: Chart Architecture

**Two-tier umbrella charts + custom local charts for services without official charts.**

| Tier | Release Name | Charts |
|------|-------------|--------|
| Infrastructure | `genai-infra` | minio, postgresql (x3), neo4j, pgvector |
| Application | `genai-apps` | n8n, mlflow, litellm, langfuse (+worker), streaming-proxy, mcp-gateway |

Rationale: Helm upgrades are atomic per release. Separating infra from apps means upgrading n8n doesn't touch databases.

## Decision: Shared MinIO

Deploy MinIO once in infra tier. Both MLflow and Langfuse reference it via global values. Avoids duplicate storage.

## Decision: Langfuse Sub-dependencies

Let Langfuse chart manage its own ClickHouse + Redis (bundled as Bitnami sub-charts). External PostgreSQL from infra tier. This simplifies the dependency graph — Langfuse is self-contained except for Postgres.

Alternative rejected: Sharing ClickHouse/Redis across stacks — nothing else uses them, so no sharing benefit.

## Decision: Custom Charts Needed

Three services have no good official chart and need thin local charts:
- **streaming-proxy** — custom Python service
- **mcp-gateway** — custom service with Docker socket mount
- **litellm** — official chart exists but is minimal; may need local chart for full config control

## Decision: Init Patterns

| Operation | Helm Pattern |
|-----------|-------------|
| create-bucket | Post-install hook Job (minio/mc image) |
| n8n-import | Post-install hook Job (waits for n8n health) |
| pgvector extension | Bitnami initdb.scripts value |
| prompt seeding | Post-install hook Job |

## Decision: PV Strategy

k3s Local Path Provisioner is default in k3d. PVCs automatically get hostPath storage under `~/work/data/k3d/mewtwo/`. No custom provisioner needed.

## Decision: Phased Migration

Phase 1: Infrastructure tier (databases + MinIO)
Phase 2: Observability tier (MLflow + Langfuse)
Phase 3: Application tier (n8n + LiteLLM + streaming-proxy + MCP gateway + knowledge stores)

Each phase has its own spec task group with tests.

<!-- status: in-progress -->
# Spec 015: DataOps — DataHub Lineage & Quality

## Problem

Platform databases (n8n, MLflow, Langfuse) are ingested into DataHub but lack:
1. **Cross-database lineage** — no visibility into data flowing between services
2. **Quality checks** — no automated validation of data freshness or schema drift
3. **Custom metadata** — no tagging of tables by domain (agent, eval, trace, session)

## Goals

1. Automatic lineage edges between n8n workflow executions → MLflow experiments → Langfuse traces
2. Scheduled data quality assertions (freshness, row count, schema)
3. Domain-tagged datasets for discoverability

## Architecture

```
DataHub GMS (GraphQL API)
  ├── Ingestion Sources (postgres-n8n, postgres-mlflow, postgres-langfuse)
  │   └── Schedule: every 6 hours
  ├── Lineage Edges (custom emitter)
  │   └── n8n.workflow_entity → mlflow.experiments → langfuse.traces
  └── Data Quality Rules
      ├── Freshness: tables updated within last 24h
      ├── Volume: row counts within expected range
      └── Schema: no unexpected column additions/removals
```

## Implementation

### Phase 1: Ingestion (DONE)

- [x] `scripts/datahub-ingest.sh` — registers 3 PostgreSQL sources
- [x] `task datahub-ingest` — Taskfile integration
- [x] JSON recipes (not YAML) for execution compatibility
- [x] First ingestion triggered and running

### Phase 2: Lineage Emitter

Script: `scripts/datahub-lineage.py`

Emit lineage edges via DataHub REST emitter:
- `k3d-mewtwo.n8n.public.workflow_entity` → `k3d-mewtwo.mlflow.public.experiments`
  (n8n workflows call MLflow API for prompt resolution, eval logging)
- `k3d-mewtwo.mlflow.public.runs` → `k3d-mewtwo.langfuse.public.traces`
  (MLflow eval runs produce Langfuse traces)
- `k3d-mewtwo.n8n.public.execution_entity` → `k3d-mewtwo.langfuse.public.traces`
  (n8n chat workflow logs traces to Langfuse)

### Phase 3: Quality Assertions

DataHub Assertions API — create freshness and volume checks:
- `workflow_entity`: updated within 1h (n8n is always active)
- `execution_entity`: >100 rows (baseline after import)
- `experiments`: >5 rows (seed experiments exist)
- `traces`: updated within 24h (if Langfuse is active)

### Phase 4: Domain Tags

Tag datasets with business domains via DataHub API:
- `agent` domain: agents table, skills table
- `eval` domain: experiments, runs, metrics
- `trace` domain: traces, observations, scores
- `workflow` domain: workflow_entity, execution_entity, webhook_entity

## Verification

1. DataHub UI shows 3 sources with SUCCESS status
2. Lineage graph shows cross-service edges
3. Quality tab shows freshness/volume assertions
4. Search by domain tag returns correct datasets

## Dependencies

- DataHub GMS healthy and accessible
- All 3 PostgreSQL databases populated with data
- `datahub` Python package for REST emitter (add to pyproject.toml or run via uvx)

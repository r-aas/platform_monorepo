# Implementation Plan: Connected Systems Graph

**Branch**: `025-systems-graph` | **Date**: 2026-03-25 | **Spec**: [spec.md](./spec.md)

## Summary

Wire DataHub as the universal metadata registry by configuring ingestion sources (MLflow native, n8n bridge, Obsidian vault), integrate GitLab Issues via speckit taskstoissues, and expose the systems graph through DataHub's native lineage UI.

## Technical Context

**Language/Version**: Python 3.12 (custom ingestion sources), YAML (recipes), Bash (Taskfile tasks)
**Primary Dependencies**: DataHub (from spec 022), GitLab CE API, Obsidian vault
**Storage**: DataHub's metadata graph (Elasticsearch + MySQL via prerequisites)
**Testing**: Smoke tests (entity counts, lineage paths, search results)
**Target Platform**: k3d genai namespace

## Design Decisions

### D1: Obsidian ingestion — custom source vs file scanner
**Decision**: Custom DataHub ingestion source that reads markdown files and emits Documentation entities.
**Rationale**: DataHub's ingestion framework has a clean Source interface. A custom source gives us control over entity mapping, tags, and lineage.

### D2: GitLab Issues — speckit native vs custom bridge
**Decision**: Use `/speckit.taskstoissues` for spec→issue creation. Build a lightweight GitLab→DataHub ingestion source for issue metadata in the graph.
**Rationale**: Speckit already handles the creation. We just need to index the results in DataHub.

### D3: Lineage depth
**Decision**: Build explicit lineage at the container level first (agent → workflow → model → dataset). Component-level lineage (function → function) is deferred.
**Rationale**: Container-level lineage provides the "zoom" R needs. Component-level requires code analysis which is a separate effort.

## Implementation Phases

### Phase 1: GitLab Issues Integration (spec 025 US2)
Wire `/speckit.taskstoissues` for existing specs. Verify issues created in GitLab with correct labels.

### Phase 2: Obsidian Vault Ingestion (spec 025 US3)
Build custom DataHub ingestion source for ~/work/vault/ markdown files. Create ingestion recipe.

### Phase 3: Cross-System Lineage (spec 025 US4)
Configure lineage assertions in DataHub connecting: agents → prompts → models, workflows → services → databases.

### Phase 4: Systems Graph Verification
Verify all entities and lineage paths are discoverable in DataHub UI. Run agent queries via MCP.

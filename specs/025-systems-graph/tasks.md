# Tasks: 025 — Connected Systems Graph

**Generated from**: [plan.md](./plan.md)

## Phase 1: GitLab Issues Integration

### T001: Run taskstoissues on existing specs
- [ ] Impl: Run `/speckit.taskstoissues` on specs 022, 023, 024 → create GitLab Issues
- **AC**: SC-003

### T002: Create GitLab ingestion recipe
- [ ] Impl: `datahub/recipes/gitlab.yml` — custom source or REST-based ingestion of GitLab issues/repos
- **Depends on**: T001, spec 022 (DataHub running)

## Phase 2: Obsidian Vault Ingestion

### T003: Build Obsidian vault ingestion source
- [ ] Test: Unit test for markdown → Documentation entity mapping
- [ ] Impl: `services/datahub-obsidian-source/` — Python package implementing DataHub Source interface
- **AC**: SC-004

### T004: Create vault ingestion recipe
- [ ] Impl: `datahub/recipes/obsidian.yml` — points at ~/work/vault/, incremental mode
- **Depends on**: T003

### T005: Deploy vault ingestion CronJob
- [ ] Impl: Add to datahub-ingestion CronJob schedule (daily)
- **Depends on**: T004

## Phase 3: Cross-System Lineage

### T006: Configure agent → prompt → model lineage
- [ ] Impl: Lineage assertions in MLflow ingestion recipe or post-ingestion script
- **Depends on**: spec 022 T008

### T007: Configure workflow → service → database lineage
- [ ] Impl: Lineage edges emitted by n8n-datahub bridge
- **Depends on**: spec 022 T012

### T008: Verify lineage graph in DataHub UI
- [ ] Test: Browse agent:mlops lineage → see prompt → model → dataset chain
- **Depends on**: T006, T007

## Phase 4: Verification

### T009: Search verification
- [ ] Test: Search DataHub for "mlops" → returns agent, prompts, and vault notes
- [ ] Test: Search DataHub for spec number → returns spec and linked issues

### T010: MCP agent verification
- [ ] Test: Agent queries "what depends on qwen2.5:14b?" → gets lineage results via DataHub MCP
- **Depends on**: spec 022 T015, T006

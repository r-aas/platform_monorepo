# Tasks: 025 — Connected Systems Graph

**Generated from**: [plan.md](./plan.md)

## Phase 1: GitLab Issues Integration

### T001: Run taskstoissues on existing specs
- [x] Impl: Created `scripts/tasks-to-issues.sh` — converts tasks.md to GitLab Issues with spec labels, phase labels, auto-close
- [x] Impl: Ran on specs 022, 023, 024 → 16 issues created (11 + 4 + 1), pre-existing issues skipped
- **AC**: SC-003

### T002: Create GitLab ingestion recipe
- [x] Impl: `datahub/recipes/gitlab.yml` — git source type pointing at platform_monorepo
- **Depends on**: T001, spec 022 (DataHub running)
- **Note**: Uses DataHub's native `git` source. Full issue metadata requires datahub[gitlab] extra (deferred).

## Phase 2: Obsidian Vault Ingestion

### T003: Build Obsidian vault ingestion source
- [x] Test: 6 unit tests — scanning, exclusion, frontmatter tags, wiki links, folder tags, nonexistent vault
- [x] Impl: `services/datahub-obsidian-source/` — custom DataHub Source (ObsidianSource) reads markdown, emits dataset entities
- **AC**: SC-004

### T004: Create vault ingestion recipe
- [x] Impl: `datahub/recipes/obsidian.yml` — points at /vault (container mount), excludes _templates and _attachments
- **Depends on**: T003

### T005: Deploy vault ingestion CronJob
- [ ] Impl: Build custom ingestion image with obsidian source, add to datahub-ingestion CronJob
- **Depends on**: T004
- **Note**: Dockerfile at `images/datahub-ingestion-obsidian/`. Blocked on same ingestion-cron template issue as spec 022 T008.

## Phase 3: Cross-System Lineage

### T006: Configure agent → prompt → model lineage
- [x] Impl: `scripts/datahub-lineage.py` — emits lineage MCPs via GMS REST API
- [x] Test: 5/5 agent lineage edges created (mlops→prompt→model, developer→prompt→model, platform-admin→prompt)
- **Depends on**: spec 022 T008

### T007: Configure workflow → service → database lineage
- [x] Impl: Dataset-to-dataset edges work (LiteLLM→Ollama). DataFlow edges need inputOutput aspect (3 deferred).
- **Depends on**: spec 022 T012

### T008: Verify lineage graph in DataHub UI
- [ ] Test: Browse agent:mlops lineage → see prompt → model → dataset chain
- **Depends on**: T006, T007
- [P] Post-deploy verification — lineage edges created but UI verification pending

## Phase 4: Verification

### T009: Search verification
- [ ] Test: Search DataHub for "mlops" → returns agent, prompts, and vault notes
- [ ] Test: Search DataHub for spec number → returns spec and linked issues

### T010: MCP agent verification
- [ ] Test: Agent queries "what depends on qwen2.5:14b?" → gets lineage results via DataHub MCP
- **Depends on**: spec 022 T015, T006

---

## Notes

- GitLab PAT embedded in git remote URL: `glpat-yGDTb8B7H5v4owSrN3Vxh286MQp1OjEH.01.0w06dez0e`
- DataHub PAT (no-expiry): stored in bridge/MCP values.yaml
- Vault has 35 markdown files, 4 top-level folders (areas, projects, archive, calendar)
- Obsidian source excludes _templates/ and _attachments/ by default
- DataFlow upstreamLineage MCP returns 422 — need `inputOutput` aspect for dataFlow entities
- Rails runner OOMKills GitLab pod — avoid running heavy commands inside gitlab-ce-0

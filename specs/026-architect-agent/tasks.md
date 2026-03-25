# Tasks: 026 — Architect Agent

**Generated from**: [plan.md](./plan.md) | **TDD**: test before implementation where applicable

## Phase 1: Agent Definition + Backlog

### T001: Create backlog format
- [ ] Impl: `~/.claude/agent-memory/architect/backlog.md` — structured markdown with REQ-NNN ID, title, source (session + timestamp), classification (requirement/bug/question/refinement), status (draft/specced/deferred/abandoned), linked spec
- [ ] Impl: Add 3 seed entries from past sessions as examples of the format
- **AC**: FR-003, SC-002

### T002: Create architect agent definition
- [ ] Impl: `~/.claude/agents/architect.md` — agent system prompt covering:
  - Signal detection patterns ("we should", "lets add", "eventually", "I want to", "it would be nice", "consider adding")
  - Classification logic: requirement vs bug fix vs question vs refinement
  - Deduplication: check backlog before adding (title similarity, topic overlap)
  - Backlog management: read/write `~/.claude/agent-memory/architect/backlog.md`
  - Spec commands: invoke speckit workflow when triggered
  - Change logging: append to `## Changelog` section in each spec with ISO timestamp + reason
  - C4 diagram awareness: knows diagrams live in `docs/architecture/`, can trigger `task arch:all`
- **AC**: FR-001, FR-002, FR-010

### T003: Wire signal detection + classification
- [ ] Test: Manually invoke architect with 5 test prompts (requirement signal, bug, question, refinement, ambiguous) — verify correct classification for each
- [ ] Impl: Refine signal detection section of `architect.md` based on test results
- **Depends on**: T002
- **AC**: FR-001, FR-002, SC-001

### T004: Wire deduplication check
- [ ] Test: Add a requirement to backlog, then mention the same topic again — verify it enriches not duplicates
- [ ] Impl: Add deduplication instructions to `architect.md`: "before creating REQ-NNN, search backlog.md for title similarity and topic overlap; if found, enrich the existing entry"
- **Depends on**: T001, T002
- **AC**: FR-007, SC-002

## Phase 2: C4 Diagram Generation

### T005: Create gen-context.sh
- [ ] Test: Run script, verify output is valid Mermaid `C4Context` block containing: platform boundary, R (developer), GitLab CI, Ollama, browser actors
- [ ] Impl: `scripts/arch/gen-context.sh` — queries `kubectl get ns -o name`, maps namespaces to platform boundary containers, adds hardcoded external actors block, writes `docs/architecture/c4-context.mmd`
- **AC**: FR-012, FR-013, SC-007

### T006: Create gen-containers.sh
- [ ] Test: Run `./scripts/arch/gen-containers.sh genai`, verify output contains nodes for all services in genai namespace (agent-gateway, n8n, mlflow, litellm visible in `kubectl get svc -n genai`)
- [ ] Impl: `scripts/arch/gen-containers.sh $NAMESPACE` — queries `kubectl get svc,deploy -n $1 -o json | jq`, extracts service names and types (Deployment/StatefulSet), outputs `C4Container` Mermaid block to `docs/architecture/c4-containers-$1.mmd`
- **AC**: FR-012, FR-013, SC-007

### T007: Create gen-components.sh
- [ ] Test: Run for `agent-gateway`, verify output shows routers grouped by path prefix (/agent, /registry, /health)
- [ ] Impl: `scripts/arch/gen-components.sh $SERVICE $NAMESPACE` — tries `kubectl port-forward svc/$SERVICE -n $NAMESPACE 18888:80 &` then `curl localhost:18888/openapi.json`, falls back to `grep -r '@router\|@app\.' src/` if port-forward fails; extracts path groups and writes `C4Component` Mermaid to `docs/architecture/c4-components-$SERVICE.mmd`
- **AC**: FR-012, FR-013, SC-007

### T008: Create taskfiles/arch.yml
- [ ] Impl: `taskfiles/arch.yml` with tasks:
  - `arch:context` — runs gen-context.sh
  - `arch:containers` — runs gen-containers.sh for genai and platform namespaces
  - `arch:components` — runs gen-components.sh for agent-gateway (and bridge if present)
  - `arch:all` — deps: [arch:context, arch:containers, arch:components, arch:index]
- [ ] Impl: Include in platform `Taskfile.yml` via `includes: {arch: taskfiles/arch.yml}`
- **AC**: FR-012, SC-007

### T009: Generate initial diagrams
- [ ] Impl: Run `task arch:all` against live cluster to generate initial `docs/architecture/*.mmd` files
- [ ] Impl: Commit generated diagrams as seed state
- **Depends on**: T005, T006, T007, T008
- **AC**: FR-011, FR-016

## Phase 3: Diagram-Driven Testing

### T010: Create verify.sh (drift detection)
- [ ] Test: Add a fake service entry to a `.mmd` file, run `verify.sh`, confirm it's flagged as stale; remove a real service from the diagram, confirm it's flagged as undocumented
- [ ] Impl: `scripts/arch/verify.sh` — runs `kubectl get svc -A -o json | jq`, extracts all service names; scans all `docs/architecture/*.mmd` for entity IDs; cross-references: outputs STALE list (in diagram, not in cluster) and UNDOCUMENTED list (in cluster, not in any diagram); exits non-zero if either list is non-empty
- **AC**: FR-014, SC-008

### T011: Add arch:verify to Taskfile
- [ ] Impl: Add `arch:verify` task to `taskfiles/arch.yml` that runs `scripts/arch/verify.sh`
- **Depends on**: T008, T010
- **AC**: FR-014

### T012: Create test.sh (connectivity tests)
- [ ] Test: Run against a diagram with a known-good edge (agent-gateway → litellm), verify curl test passes; add a fake edge, verify it fails with clear error
- [ ] Impl: `scripts/arch/test.sh` — parses `-->` and `->>` edges in `c4-containers-*.mmd` files; for each edge `SRC --> DST`, finds the k8s service for SRC, runs `kubectl exec deploy/$SRC -- curl -s -o /dev/null -w "%{http_code}" http://$DST/health` (or HEAD /); reports PASS/FAIL per edge with HTTP status
- **AC**: FR-015, SC-009

### T013: Add arch:test to Taskfile
- [ ] Impl: Add `arch:test` task to `taskfiles/arch.yml` that runs `scripts/arch/test.sh`
- **Depends on**: T008, T012
- **AC**: FR-015

## Phase 4: Architecture Index

### T014: Create index.sh
- [ ] Impl: `scripts/arch/index.sh` — lists `docs/architecture/*.mmd`, gets last-modified via `git log -1 --format=%ci -- $file`, runs `verify.sh --summary` for drift count per diagram; writes `docs/architecture/INDEX.md` table: Diagram | C4 Level | Last Generated | Drift | Link
- **Depends on**: T010

### T015: Add arch:index to Taskfile + wire into arch:all
- [ ] Impl: Add `arch:index` task to `taskfiles/arch.yml`; add as final dep in `arch:all`
- **Depends on**: T008, T014
- **AC**: FR-011

### T016: Generate initial INDEX.md
- [ ] Impl: Run `task arch:index` to produce the initial `docs/architecture/INDEX.md`
- [ ] Impl: Commit alongside diagrams
- **Depends on**: T009, T015

## Phase 5: Speckit Integration

### T017: Add speckit automation to architect agent
- [ ] Impl: Update `~/.claude/agents/architect.md` — add speckit section:
  - Trigger detection: "spec this", "write a spec for", "spec out", "create a spec"
  - Sequence: run `/speckit.specify` → check for `[NEEDS CLARIFICATION]` in generated spec.md → if found, ask R before proceeding → on approval, run `/speckit.plan` → `/speckit.tasks`
  - "plan it" trigger: run `/speckit.plan` on current/named spec
  - "generate tasks" trigger: run `/speckit.tasks` on current/named spec
- **Depends on**: T002
- **AC**: FR-004, SC-003, SC-006

### T018: Add spec refinement instructions to architect agent
- [ ] Test: Ask architect to "add a requirement to spec 026", verify FR numbering preserved and new FR appended correctly
- [ ] Impl: Update `~/.claude/agents/architect.md` — add refinement section:
  - Detect refinement signals ("add X to the spec", "change FR-NNN", "scope this down", "remove")
  - Always read existing spec.md before editing to preserve structure
  - FR numbering: next available FR-NNN, sequential
  - After editing: "Note: plan.md and tasks.md may need updating" if they exist
  - Append to `## Changelog` with: date (ISO 8601), change description, reason provided by R
- **Depends on**: T002
- **AC**: FR-005, FR-006, FR-008, SC-004, SC-005

### T019: Add diagram regeneration task
- [ ] Impl: `arch:regenerate` task in `taskfiles/arch.yml` — alias for `arch:all` with a note in desc about triggering on spec ship
- [ ] Impl: Document in `docs/architecture/INDEX.md` header: "Run `task arch:regenerate` after shipping a spec that changes platform services"
- **Depends on**: T008, T009
- **AC**: SC-010

## Verification

### T020: End-to-end smoke test
- [ ] Invoke `@architect`, say "we should add a cost tracking dashboard" — verify REQ entry added to backlog.md with correct classification
- [ ] Invoke `@architect`, say "spec the cost tracking dashboard" — verify spec.md created with FR-001+, user stories, and acceptance scenarios
- [ ] Run `task arch:all` — verify all `docs/architecture/*.mmd` files generated without errors
- [ ] Run `task arch:verify` — verify drift detection runs and produces a report
- [ ] Run `task arch:test` — verify connectivity tests run for all edges in container diagrams
- [ ] Run `task arch:index` — verify `INDEX.md` updated with correct timestamps
- **Depends on**: T001–T019
- **AC**: All FRs, SC-001 through SC-010

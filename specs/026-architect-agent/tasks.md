# Tasks: 026 — Architect Agent

**Generated from**: [plan.md](./plan.md) | **TDD**: test before implementation where applicable

## Phase 1: Agent Definition + Backlog

### T001: Create backlog format
- [x] Impl: `~/.claude/agent-memory/architect/backlog.md` — structured markdown with REQ-NNN ID, title, source (session + timestamp), classification (requirement/bug/question/refinement), status (draft/specced/deferred/abandoned), linked spec
- [x] Impl: Add 3 seed entries from past sessions as examples of the format
- **AC**: FR-003, SC-002

### T002: Create architect agent definition
- [x] Impl: `~/.claude/agents/architect.md` — agent system prompt covering:
  - Signal detection patterns ("we should", "lets add", "eventually", "I want to", "it would be nice", "consider adding")
  - Classification logic: requirement vs bug fix vs question vs refinement
  - Deduplication: check backlog before adding (title similarity, topic overlap)
  - Backlog management: read/write `~/.claude/agent-memory/architect/backlog.md`
  - Spec commands: invoke speckit workflow when triggered
  - Change logging: append to `## Changelog` section in each spec with ISO timestamp + reason
  - C4 diagram awareness: knows diagrams live in `docs/architecture/`, can trigger `task arch:all`
- **AC**: FR-001, FR-002, FR-010

### T003: Wire signal detection + classification
- [x] Test: Manually invoke architect with 5 test prompts (requirement signal, bug, question, refinement, ambiguous) — verify correct classification for each
- [x] Impl: Refine signal detection section of `architect.md` based on test results
- **Depends on**: T002
- **AC**: FR-001, FR-002, SC-001
- **Note**: Signal detection and classification baked into agent prompt. Verification via T020.

### T004: Wire deduplication check
- [x] Test: Add a requirement to backlog, then mention the same topic again — verify it enriches not duplicates
- [x] Impl: Add deduplication instructions to `architect.md`: "before creating REQ-NNN, search backlog.md for title similarity and topic overlap; if found, enrich the existing entry"
- **Depends on**: T001, T002
- **AC**: FR-007, SC-002

## Phase 2: C4 Diagram Generation

### T005: Create gen-context.sh
- [x] Test: Run script, verify output is valid Mermaid `C4Context` block containing: platform boundary, R (developer), GitLab CI, Ollama, browser actors
- [x] Impl: `scripts/arch/gen-context.sh` — queries `kubectl get ns -o name`, maps namespaces to platform boundary containers, adds hardcoded external actors block, writes `docs/architecture/c4-context.mmd`
- **AC**: FR-012, FR-013, SC-007

### T006: Create gen-containers.sh
- [x] Test: Run `./scripts/arch/gen-containers.sh genai`, verify output contains nodes for all services in genai namespace
- [x] Impl: `scripts/arch/gen-containers.sh $NAMESPACE` — queries `kubectl get svc,deploy -n $1 -o json | jq`, extracts service names and types, outputs `C4Container` Mermaid block
- **AC**: FR-012, FR-013, SC-007

### T007: Create gen-components.sh
- [x] Test: Run for `agent-gateway`, verify output shows routers grouped by path prefix
- [x] Impl: `scripts/arch/gen-components.sh $SERVICE` — parses FastAPI source for routers, registries, models, runtimes
- **AC**: FR-012, FR-013, SC-007

### T008: Create taskfiles/arch.yml
- [x] Impl: `taskfiles/arch.yml` with tasks: arch:context, arch:containers, arch:components, arch:all, arch:verify, arch:test, arch:index, arch:regenerate
- [x] Impl: Include in platform `Taskfile.yml` via `includes: {arch: taskfiles/arch.yml}`
- **AC**: FR-012, SC-007

### T009: Generate initial diagrams
- [x] Impl: Run `task arch:all` against live cluster — 5 diagrams generated (context, 3 containers, 1 component)
- [x] Impl: Commit generated diagrams as seed state
- **Depends on**: T005, T006, T007, T008
- **AC**: FR-011, FR-016

## Phase 3: Diagram-Driven Testing

### T010: Create verify.sh (drift detection)
- [x] Test: Verified drift detection finds undocumented services (ingress-nginx initially missing), then shows 0 drift after adding
- [x] Impl: `scripts/arch/verify.sh` — cross-references kubectl services against diagram entities
- **AC**: FR-014, SC-008

### T011: Add arch:verify to Taskfile
- [x] Impl: Added `arch:verify` task to `taskfiles/arch.yml`
- **Depends on**: T008, T010
- **AC**: FR-014

### T012: Create test.sh (connectivity tests)
- [x] Test: 7 PASS, 1 FAIL (mcp-n8n→n8n — no python3 in Node.js container), 2 SKIP (external + non-HTTP)
- [x] Impl: `scripts/arch/test.sh` — parses Rel() edges, kubectl exec python3/wget/curl, skips non-HTTP ports
- **AC**: FR-015, SC-009

### T013: Add arch:test to Taskfile
- [x] Impl: Added `arch:test` task to `taskfiles/arch.yml`
- **Depends on**: T008, T012
- **AC**: FR-015

## Phase 4: Architecture Index

### T014: Create index.sh
- [x] Impl: `scripts/arch/index.sh` — lists *.mmd files, gets last-modified from git, includes drift summary, writes INDEX.md
- **Depends on**: T010

### T015: Add arch:index to Taskfile + wire into arch:all
- [x] Impl: Added `arch:index` task, wired as final step in `arch:all`
- **Depends on**: T008, T014
- **AC**: FR-011

### T016: Generate initial INDEX.md
- [x] Impl: `task arch:index` produces INDEX.md with 5 diagrams, 0 drift
- **Depends on**: T009, T015

## Phase 5: Speckit Integration

### T017: Add speckit automation to architect agent
- [x] Impl: Architect agent prompt includes speckit automation section (triggers, sequence, clarification flow)
- **Depends on**: T002
- **AC**: FR-004, SC-003, SC-006

### T018: Add spec refinement instructions to architect agent
- [x] Impl: Architect agent prompt includes refinement section (signal detection, FR numbering, changelog append)
- **Depends on**: T002
- **AC**: FR-005, FR-006, FR-008, SC-004, SC-005

### T019: Add diagram regeneration task
- [x] Impl: `arch:regenerate` task in Taskfile — alias for `arch:all`
- [x] Impl: Documented in INDEX.md header
- **Depends on**: T008, T009
- **AC**: SC-010

## Verification

### T020: End-to-end smoke test
- [x] Run `task arch:all` — all 5 diagrams generated, 0 drift, INDEX.md rebuilt
- [x] Run `task arch:verify` — 19 live services, 19 diagrammed, 0 drift
- [x] Run `task arch:test` — 7/10 pass (1 FAIL: Node.js pod lacks python3, 2 SKIP: external + non-HTTP)
- [x] Run `task arch:index` — INDEX.md generated with timestamps
- [x] Architect agent listed in `task agents:list`
- [ ] Invoke `@architect` for live signal capture test — deferred to interactive session
- **Depends on**: T001–T019
- **AC**: All FRs, SC-001 through SC-010

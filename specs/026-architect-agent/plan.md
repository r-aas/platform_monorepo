# Implementation Plan: Architect Agent

**Branch**: `026-architect-agent` | **Date**: 2026-03-25 | **Spec**: [spec.md](./spec.md)

## Summary

Build a Claude Code agent that captures requirements from conversations, drives the speckit workflow, maintains a living requirements backlog, generates C4 architecture diagrams from live API queries, and provides diagram-driven architecture testing.

## Technical Context

**Language/Version**: Markdown (agent definition), Python 3.12 (diagram generation scripts), Bash (Taskfile tasks)
**Primary Dependencies**: Claude Code agents system, speckit CLI, kubectl, jq, FastAPI route introspection
**Storage**: Requirements backlog as markdown (`~/.claude/agent-memory/architect/backlog.md`), diagrams as Mermaid in `docs/architecture/`
**Testing**: Diagram drift detection (`task arch:verify`), connectivity tests (`task arch:test`)
**Target Platform**: macOS, Claude Code CLI, k3d cluster

## Design Decisions

### D1: Backlog format — markdown vs DataHub
**Decision**: Start with markdown file at `~/.claude/agent-memory/architect/backlog.md`. Migrate to DataHub entities when spec 025 ships.
**Rationale**: Zero dependencies for MVP. Markdown is git-trackable (via agent-memory) and human-readable. DataHub migration path is clean — same structure, different backend.

### D2: Diagram generation — static templates vs live queries
**Decision**: Live API queries via scripts in `scripts/arch/`. Each C4 level has its own generation script.
**Rationale**: Live queries ensure diagrams match reality. Static templates rot instantly. Scripts are independently testable and composable via Taskfile.

### D3: C4 Context level — what's "external"?
**Decision**: External actors: R (developer), GitLab CI (automation), Ollama (native Mac LLM), browsers (UI access). Everything deployed in k3d is inside the platform boundary.
**Rationale**: Matches how R thinks about the system — k3d is "the platform", everything else is external. Ollama is external because it runs native (not k3d).

### D4: Connectivity test generation — manual vs automated
**Decision**: Automated from diagrams. Parse Mermaid container diagram, extract edges, generate curl/wget tests that run inside the relevant pod namespace.
**Rationale**: The diagram IS the test spec. If the diagram says A→B, prove it. Manual tests drift as fast as static diagrams.

### D5: Diagram storage — per-spec vs centralized
**Decision**: Centralized at `docs/architecture/`. Diagrams are platform artifacts, not spec artifacts. Specs reference the central diagrams.
**Rationale**: One source of truth. C4 diagrams describe the whole platform, not individual features. Versioned in git alongside specs per FR-016.

### D6: Agent memory location
**Decision**: `~/.claude/agent-memory/architect/` for persistent state (backlog, pattern log). Not committed to repo — personal to R's machine.
**Rationale**: Backlog contains draft requirements and session context that are personal/machine-local. The _generated_ artifacts (diagrams, specs) are committed to the repo.

### D7: Component diagram source — code vs runtime
**Decision**: FastAPI services: introspect via `/openapi.json` endpoint when running, fall back to static code analysis via `grep` on route decorators when not running.
**Rationale**: Runtime introspection is most accurate. Static fallback ensures diagrams can be generated without a live cluster (e.g., CI).

## Project Structure

```text
~/.claude/agents/architect.md         # Agent definition (system prompt)
~/.claude/agent-memory/architect/
├── backlog.md                         # Requirements backlog (draft requirements)
└── patterns.md                        # Captured architectural patterns and decisions

docs/architecture/
├── INDEX.md                           # Auto-generated: all diagrams, timestamps, drift status
├── c4-context.mmd                     # System context: platform boundary + external actors
├── c4-containers-genai.mmd            # genai namespace: agent-gateway, n8n, MLflow, LiteLLM, DataHub
├── c4-containers-platform.mmd         # platform namespace: GitLab CE, ArgoCD, ingress-nginx
├── c4-components-agent-gateway.mmd    # agent-gateway internals: routers, registries, runtimes
└── c4-components-bridge.mmd           # n8n-datahub bridge internals (when bridge exists)

scripts/arch/
├── gen-context.sh       # kubectl get ns + known external actors → c4-context.mmd
├── gen-containers.sh    # kubectl get svc,deploy -n $1 → c4-containers-$1.mmd
├── gen-components.sh    # /openapi.json or grep routes → c4-components-$1.mmd
├── verify.sh            # compare diagram entities against live kubectl output → drift report
├── test.sh              # parse diagram edges → generate + run connectivity tests via kubectl exec
└── index.sh             # update docs/architecture/INDEX.md with timestamps + drift status

taskfiles/arch.yml       # Taskfile include: arch:context, arch:containers, arch:components,
                         #                  arch:all, arch:verify, arch:test, arch:index
```

## Implementation Phases

### Phase 1: Agent Definition + Backlog (P1, FR-001 to FR-010)

Create the architect agent at `~/.claude/agents/architect.md` with:
- Requirement signal detection patterns ("we should", "lets add", "eventually", "I want")
- Signal classification logic (requirement / bug fix / question / refinement)
- Deduplication check against existing backlog entries
- Speckit workflow automation (specify → clarify? → plan → tasks)
- Spec refinement with FR preservation
- Change logging with timestamps and reasons

Create backlog format at `~/.claude/agent-memory/architect/backlog.md` with structured markdown:
- Requirement ID (REQ-NNN), title, source (session + timestamp), classification, status, linked spec

### Phase 2: C4 Diagram Generation (P1, FR-011 to FR-013)

Build `scripts/arch/` generation scripts:
- `gen-context.sh`: Queries `kubectl get ns` for platform boundary, hardcodes known external actors, outputs `C4Context` Mermaid block
- `gen-containers.sh`: Queries `kubectl get svc,deploy -n $1`, maps to `C4Container` nodes, uses service annotations for connection hints
- `gen-components.sh`: Hits `/openapi.json` of named service (via `kubectl port-forward`), extracts paths grouped by router prefix, outputs `C4Component` Mermaid block

Wire into `taskfiles/arch.yml` with tasks: `arch:context`, `arch:containers`, `arch:components`, `arch:all`.

### Phase 3: Diagram-Driven Testing (P2, FR-014, FR-015)

Build verification and testing scripts:
- `verify.sh`: Runs `kubectl get svc -A`, extracts service names, cross-references against all `*.mmd` files, reports services not found in any diagram (undocumented) and diagram entities with no matching service (stale)
- `test.sh`: Parses `-->` edges in container diagrams, maps source/target to k8s service endpoints, runs `kubectl exec` curl tests from source pod to target service, reports pass/fail per edge

Add `arch:verify` and `arch:test` tasks to `taskfiles/arch.yml`.

### Phase 4: Architecture Index (FR-011, FR-016)

Build `scripts/arch/index.sh`:
- Lists all `docs/architecture/*.mmd` files
- Extracts last-modified timestamp from git log
- Runs `verify.sh` in summary mode to get drift count per diagram
- Writes `docs/architecture/INDEX.md` with table: diagram | level | last-generated | drift-count | link

Add `arch:index` task. Run as part of `arch:all`.

### Phase 5: Speckit Integration + Regeneration Hook (P1, FR-004, SC-010)

Update architect agent definition with full speckit automation context:
- Command triggers: "spec this", "write a spec for X", "plan it", "generate tasks"
- Clarification detection: scan generated spec.md for `[NEEDS CLARIFICATION]` markers before proceeding
- Post-ship hook: when spec status changes to `shipped`, regenerate affected diagrams

Add `arch:regenerate` task triggered by the hook.

## Migration Path (P3 — DataHub integration)

When spec 025 ships:
1. Implement DataHub custom ingestion source for `backlog.md`
2. Add `task arch:ingest` that pushes spec artifacts as DataHub entities
3. Add lineage: spec entity → GitLab issues (via taskstoissues) → commits → deployments
4. Migrate backlog from markdown to DataHub entities; keep markdown as human-readable mirror

This is deferred until DataHub (spec 025) is shipped. No code written for it now.

# Tasks: 023 — Autonomous Platform Team

**Generated from**: [plan.md](./plan.md) | **TDD**: test before implementation where applicable

## Phase 1: Agent Definitions

### T001: Create benchmark-runner agent
- [ ] Impl: `~/.claude/agents/benchmark-runner.md` — scheduled nightly eval agent
- **Files**: `~/.claude/agents/benchmark-runner.md`
- **AC**: FR-001, FR-002

### T002: Create n8n-fixer agent
- [ ] Impl: `~/.claude/agents/n8n-fixer.md` — n8n workflow diagnosis and repair
- **Files**: `~/.claude/agents/n8n-fixer.md`
- **AC**: FR-001, FR-002

### T003: Create docs-sync agent
- [ ] Impl: `~/.claude/agents/docs-sync.md` — documentation drift detection
- **Files**: `~/.claude/agents/docs-sync.md`
- **AC**: FR-001, FR-002

## Phase 2: Agent Memory Infrastructure

### T004: Create agent memory directory structure
- [ ] Impl: `~/.claude/agent-memory/` with subdirs for each agent + shared/
- **Files**: `~/.claude/agent-memory/{platform-doctor,merge-reviewer,rules-curator,benchmark-runner,n8n-fixer,docs-sync,shared}/MEMORY.md`
- **AC**: FR-007, FR-008

### T005: Add memory loading to agent prompts
- [ ] Impl: Update all 6 agent .md files to read their memory dir at startup
- **Depends on**: T001, T002, T003, T004
- **AC**: FR-007

## Phase 3: Factory Worker Worktree Isolation

### T006: Modify factory-worker for git worktrees
- [ ] Impl: `~/.claude/scheduled-tasks/factory-worker/SKILL.md` — replace lock file with worktree create/remove
- **AC**: FR-006

### T007: Update guardrails for worktree model
- [ ] Impl: `platform_monorepo/.claude/autonomous/guardrails.md` — replace concurrency lock rules with worktree rules
- **Depends on**: T006
- **AC**: FR-006

## Phase 4: Benchmark Runner Scheduled Task

### T008: Create benchmark-runner scheduled task
- [ ] Impl: `~/.claude/scheduled-tasks/benchmark-runner/SKILL.md` — nightly eval with drift detection
- **AC**: FR-001, SC-005

### T009: Create benchmark baselines in MLflow
- [ ] Impl: Script to store current benchmark results as baselines via /webhook/traces action=baseline_set
- **Depends on**: T008
- **AC**: SC-005

## Phase 5: Taskfile Integration

### T010: Add agents Taskfile tasks
- [ ] Impl: `~/work/repos/platform_monorepo/taskfiles/agents.yml` — list, test, invoke tasks
- **AC**: FR-001

## Verification

### T011: End-to-end agent verification
- [ ] Invoke each agent manually and verify correct behavior
- [ ] Run benchmark-runner dry run
- [ ] Verify agent memory persistence across invocations
- **Depends on**: T001-T010

# Feature Specification: Autonomous Platform Team

**Feature Branch**: `023-autonomous-agents`
**Created**: 2026-03-25
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Infrastructure Self-Healing (Priority: P1)

As a platform engineer, I have an agent that monitors cluster health every 30 minutes and automatically diagnoses issues (DNS failures, pod crashes, storage problems) — so I don't have to manually debug recurring infrastructure problems.

**Why this priority**: DNS cascades, pod crashes, and storage issues are the top 3 recurring problems. Automated diagnosis eliminates the biggest time sink.

**Independent Test**: Stop a service, wait for the platform-doctor scheduled run, verify it produces a correct diagnosis report.

**Acceptance Scenarios**:

1. **Given** a pod is in CrashLoopBackOff, **When** platform-doctor runs, **Then** it identifies the root cause (OOM, missing secret, image pull failure) in its report
2. **Given** CoreDNS can't resolve external names, **When** platform-doctor runs, **Then** it identifies the DNS fix is missing and provides the exact remediation command
3. **Given** all services are healthy, **When** platform-doctor runs, **Then** it produces a clean health report in under 60 seconds

---

### User Story 2 - Automated Merge Review (Priority: P1)

As a developer, every commit I make is automatically reviewed for security, ARM64 compatibility, Helm chart validity, n8n sandbox violations, and spec compliance — so I catch issues before they reach production.

**Why this priority**: Manual review is a bottleneck. Automated review catches known footguns (secrets in code, amd64 images, n8n axios usage) deterministically.

**Independent Test**: Make a commit with a known issue (e.g., hardcoded secret), verify merge-reviewer flags it.

**Acceptance Scenarios**:

1. **Given** a commit adds a Docker image without arm64 variant, **When** merge-reviewer runs, **Then** it flags the ARM64 incompatibility with the exact image and fix
2. **Given** a commit modifies an n8n workflow JSON with `process.env`, **When** merge-reviewer runs, **Then** it flags the sandbox violation
3. **Given** a clean commit with tests, **When** merge-reviewer runs, **Then** it approves with a summary

---

### User Story 3 - Rules System Maintenance (Priority: P2)

As a platform engineer, I have an agent that weekly audits my skills, hooks, CLAUDE.md, and agent definitions — identifying staleness, bloat, duplication, and gaps — so the rules system stays lean and effective.

**Why this priority**: With 76+ skills and 700+ line CLAUDE.md, instruction-following degrades. Systematic pruning keeps the system effective.

**Independent Test**: Run rules-curator, verify it correctly identifies CLAUDE.md line count and proposes specific pruning targets.

**Acceptance Scenarios**:

1. **Given** CLAUDE.md exceeds 200 lines, **When** rules-curator runs, **Then** it identifies specific sections to move to skills
2. **Given** a skill references a path that no longer exists, **When** rules-curator runs, **Then** it flags the stale reference
3. **Given** two skills cover overlapping domains, **When** rules-curator runs, **Then** it recommends consolidation

---

### User Story 4 - Factory Worker Parallelism (Priority: P2)

As a platform engineer, the factory worker runs in an isolated git worktree — so it can work in parallel with my own development without lock file contention.

**Why this priority**: The current lock file mechanism is a serialization bottleneck. Worktree isolation enables true parallelism.

**Independent Test**: Start a factory worker run while manually editing code, verify no conflicts.

**Acceptance Scenarios**:

1. **Given** R is editing code on main, **When** factory-worker starts, **Then** it creates a worktree and works independently
2. **Given** factory-worker completes a task in its worktree, **When** it commits, **Then** the changes can be merged to main without conflicts
3. **Given** two factory workers start simultaneously, **When** both create worktrees, **Then** they work on different tasks without interference

---

### User Story 5 - Benchmark Regression Detection (Priority: P3)

As an ML engineer, a nightly agent runs the full benchmark suite across all agents and models, compares against baselines, and alerts me if quality degrades — so prompt changes never silently break agent performance.

**Why this priority**: Depends on eval pipeline (already built). Closes the autonomous improvement loop.

**Independent Test**: Degrade a prompt intentionally, run benchmark-runner, verify it detects the regression.

**Acceptance Scenarios**:

1. **Given** baselines exist for all agents, **When** benchmark-runner executes nightly, **Then** results are logged to MLflow with per-agent/per-model breakdowns
2. **Given** a prompt change drops pass rate below baseline, **When** benchmark-runner detects drift, **Then** it writes a regression report with specific failing test cases

---

### Edge Cases

- What if platform-doctor detects an issue it can fix but the fix is destructive (delete pod, restart service)? → L0 agents report only. L1 promotion requires explicit R approval.
- What if merge-reviewer produces a false positive? → Review findings are advisory, not blocking. R decides.
- What if factory-worker worktree has merge conflicts with main? → Worker aborts, marks task blocked.
- What if benchmark-runner can't reach n8n (cluster down)? → Report "cluster unreachable", don't flag as regression.

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide agent definitions as `.md` files in `~/.claude/agents/` with YAML frontmatter
- **FR-002**: Each agent MUST have a defined autonomy level (L0=read-only, L1=safe writes, L2=code changes, L3=infra, L4=platform)
- **FR-003**: platform-doctor MUST follow the diagnostic flowchart: Colima → k3d → DNS → ArgoCD → pods → services → storage
- **FR-004**: merge-reviewer MUST check: security, ARM64 compatibility, Helm validity, n8n sandbox, spec compliance, test coverage
- **FR-005**: rules-curator MUST audit: CLAUDE.md line count, skill staleness, hook coverage, agent definitions, factory state
- **FR-006**: Factory worker MUST support worktree isolation (eliminate lock file mechanism)
- **FR-007**: Each agent MUST have persistent memory at `~/.claude/agent-memory/{name}/`
- **FR-008**: Agents MUST share cross-cutting patterns via `~/.claude/agent-memory/shared/`
- **FR-009**: merge-reviewer MUST be triggerable via PostToolUse hook on `git commit`
- **FR-010**: All agents MUST respect the emergency stop file (`.factory-stop`)

### Key Entities

- **Agent Definition**: Markdown file with YAML frontmatter (name, description, tools, model, memory scope)
- **Autonomy Level**: L0-L4 trust hierarchy controlling what actions an agent can take
- **Agent Memory**: Persistent directory per agent for cross-session learning
- **Shared Memory**: Cross-agent patterns/conventions directory

## Success Criteria

### Measurable Outcomes

- **SC-001**: platform-doctor correctly diagnoses 90%+ of common issues (DNS, pod crash, storage) in under 60 seconds
- **SC-002**: merge-reviewer catches 100% of known footguns (secrets, ARM64, n8n sandbox, missing tests)
- **SC-003**: rules-curator identifies all CLAUDE.md sections over the 200-line budget
- **SC-004**: Factory worker with worktree isolation has zero lock file contention
- **SC-005**: benchmark-runner detects 100% of regressions where pass rate drops >5% below baseline
- **SC-006**: All agent definitions are under 200 lines each

## Assumptions

- Claude Code supports `~/.claude/agents/` for custom agent definitions
- Worktree isolation is available via git worktrees (not Claude Code's experimental feature — use raw git)
- Agent memory directories are manually managed (write via agent, read at startup)
- Hook-triggered agents use PostToolUse Bash hooks that spawn `claude -p "review this commit"`

## Reference Repos

- `~/work/clones/claude-code/claude-code-hooks-mastery` — hook patterns
- `~/work/clones/agents/self_improving_coding_agent` — self-improvement loop (ICLR 2025)
- `~/work/clones/claude-code/gstack` — role-based agent orchestration
- `~/work/clones/agent-sdk/claude-agent-sdk-demos` — multi-agent SDK patterns

# Feature Specification: P0 Hooks & Rules System Overhaul

**Feature Branch**: `024-hooks-rules-system`
**Created**: 2026-03-25
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Destructive Command Prevention (Priority: P1)

As a developer using Claude Code, destructive kubectl commands (delete, drain, scale to 0) and secret-leaking git operations are blocked before execution with clear guidance — so I never accidentally destroy resources or commit credentials.

**Why this priority**: These are the highest-blast-radius mistakes. One `kubectl delete namespace` or committed API key can cause hours of recovery.

**Independent Test**: Attempt `kubectl delete pod` via Claude Code, verify it's blocked with an actionable message.

**Acceptance Scenarios**:

1. **Given** Claude attempts `kubectl delete pod X`, **When** the PreToolUse hook fires, **Then** execution is blocked with message "Destructive kubectl operation — confirm with user first"
2. **Given** Claude attempts `git add .env`, **When** the PreToolUse hook fires, **Then** execution is blocked with message "Blocked: .env files must not be committed"
3. **Given** Claude attempts `kubectl get pods`, **When** the PreToolUse hook fires, **Then** the command proceeds (read-only, not blocked)

---

### User Story 2 - ArgoCD Ownership Protection (Priority: P1)

As a platform engineer, Claude is prevented from running `helmfile sync` or `helm upgrade` on resources that ArgoCD already manages — so we never cause field manager conflicts or GitOps drift.

**Why this priority**: Helm-ArgoCD conflicts were the #2 cause of bootstrap failures. This rule is documented but not enforced.

**Independent Test**: Run `helmfile sync` when ArgoCD apps exist, verify it's blocked.

**Acceptance Scenarios**:

1. **Given** ArgoCD manages genai-litellm, **When** Claude runs `helm upgrade genai-litellm`, **Then** hook blocks with "This release is managed by ArgoCD. Use ArgoCD sync or edit Helm values in Git."
2. **Given** ArgoCD is not yet deployed (fresh bootstrap), **When** Claude runs `helmfile sync`, **Then** the command proceeds normally

---

### User Story 3 - n8n Workflow Safety (Priority: P1)

As a developer editing n8n workflow JSON files, Claude is warned when writing Code nodes that use `process.env` (broken), `axios` (crashes), or direct HTTP calls (blocked by sandbox) — so I never introduce n8n task runner crashes.

**Why this priority**: n8n sandbox violations are the #1 recurring workflow issue. Every one has cost hours of debugging.

**Independent Test**: Edit a workflow JSON to add `process.env.FOO` in a Code node, verify the hook warns.

**Acceptance Scenarios**:

1. **Given** Claude writes a workflow JSON with `process.env.VAR`, **When** the PostToolUse hook fires, **Then** warning shows "Use $env.VAR — process.env is empty in n8n task runner sandbox"
2. **Given** Claude writes a Code node with `require('axios')`, **When** hook fires, **Then** warning shows "axios crashes on 4xx in task runner. Use native HTTP Request nodes for outbound HTTP."

---

### User Story 4 - CLAUDE.md Pruning (Priority: P2)

As a developer, CLAUDE.md is under 200 lines containing only principles and decisions — all technical details, gotchas, and troubleshooting steps live in context-activated skills — so instruction-following stays reliable.

**Why this priority**: Research shows LLMs degrade beyond ~150-200 instructions. Our CLAUDE.md is 700+ lines. Pruning directly improves Claude's reliability.

**Independent Test**: Count CLAUDE.md lines before and after pruning. Verify moved content exists in the target skills.

**Acceptance Scenarios**:

1. **Given** the global CLAUDE.md is 700+ lines, **When** pruning is complete, **Then** it's under 200 lines
2. **Given** ARM64 compatibility details are removed from CLAUDE.md, **When** Claude encounters an ARM64 issue, **Then** the `platform-helm-authoring` skill activates with the full compatibility table
3. **Given** n8n gotchas are removed from CLAUDE.md, **When** Claude edits an n8n workflow, **Then** the `genai-mlops-workflows` skill activates with all sandbox constraints

---

### User Story 5 - PostCompact Context Survival (Priority: P2)

As a developer in a long session, when context is compacted, critical rules (safety constraints, toolchain choices, quality gates) survive the compaction — so Claude doesn't regress to default behavior mid-session.

**Why this priority**: After compaction, Claude sometimes forgets project-specific rules (uses pip instead of uv, forgets ARM64 constraints). Re-injection prevents this.

**Independent Test**: Trigger compaction in a session, verify critical rules are present in the post-compaction context.

**Acceptance Scenarios**:

1. **Given** a session reaches compaction threshold, **When** compaction occurs, **Then** a PostCompact hook injects: toolchain rules (uv only), safety rules (no containerized Ollama), and quality gates
2. **Given** the injected context, **When** Claude continues working, **Then** it follows project conventions without being reminded

---

### Edge Cases

- What if a hook blocks a command the user explicitly requested? → Hook provides guidance; user can override via direct shell.
- What if ArgoCD is deployed but unhealthy (can't sync)? → Allow helmfile as fallback, log warning.
- What if CLAUDE.md pruning moves content to a skill that doesn't exist yet? → Create the skill first.
- What if multiple hooks fire on the same action? → All hooks run; any block stops execution.

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide PreToolUse:Bash hooks that block destructive kubectl commands (delete, drain, cordon, taint, scale to 0)
- **FR-002**: System MUST provide PreToolUse:Bash hooks that block `git add`/`git commit` of files matching `.env`, `*secret*`, `*credential*`, `*token*`
- **FR-003**: System MUST provide PreToolUse:Bash hooks that block `helmfile sync`/`helm upgrade`/`helm install` when ArgoCD manages the target release
- **FR-004**: System MUST provide PreToolUse:Write/Edit hooks that block adding Ollama service to compose/k8s manifest files
- **FR-005**: System MUST provide PostToolUse:Write/Edit hooks that warn on n8n workflow JSON containing `process.env`, `require('axios')`, `require('http')`
- **FR-006**: Global CLAUDE.md MUST be pruned to under 200 lines with details moved to skills
- **FR-007**: System MUST provide a PostCompact hook that re-injects critical rules
- **FR-008**: All hooks MUST provide actionable error messages with the specific fix
- **FR-009**: All hooks MUST be idempotent and complete in under 2 seconds
- **FR-010**: Hook scripts MUST be executable shell scripts at `~/.claude/hooks/`

### Key Entities

- **PreToolUse Hook**: Fires before tool execution — can block (exit 2) or allow (exit 0)
- **PostToolUse Hook**: Fires after tool execution — can provide feedback but not block
- **PostCompact Hook**: Fires after context compaction — re-injects critical rules
- **Hook Script**: Executable at `~/.claude/hooks/{name}.sh` — receives tool input via stdin JSON

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% of destructive kubectl commands are blocked before execution
- **SC-002**: 100% of `.env` file commits are blocked before staging
- **SC-003**: 100% of helm operations on ArgoCD-managed releases are blocked with guidance
- **SC-004**: Global CLAUDE.md is under 200 lines after pruning
- **SC-005**: All moved content is accessible via context-activated skills
- **SC-006**: PostCompact hook injects critical rules in under 1 second
- **SC-007**: No hook takes more than 2 seconds to execute (latency budget)

## Assumptions

- Hook scripts receive tool input as JSON on stdin (per Claude Code hooks spec)
- PreToolUse hooks can block execution by exiting with code 2
- PostToolUse hooks provide feedback but don't block
- Skills activate automatically by description keyword matching
- The `barrier.sh` hook already blocks some dangerous commands — extend rather than replace

## Reference Repos

- `~/work/clones/claude-code/claude-code-hooks-mastery` — hook patterns and examples
- `~/work/clones/claude-code/claude-hooks-decider` — code quality validation hooks
- `~/work/clones/claude-code/claude-hooks-lindquist` — typed hook payloads
- `~/work/clones/claude-code/awesome-claude-code` — curated CLAUDE.md examples

## Content Migration Plan

| CLAUDE.md Section | Target Skill | Est. Lines Saved |
|-------------------|-------------|-----------------|
| ARM64 compatibility table | platform-helm-authoring | ~30 |
| Docker image ARM64 notes | platform-helm-authoring | ~20 |
| n8n gotchas (all) | genai-mlops-workflows | ~15 |
| k3d host networking details | platform-k3d-networking | ~15 |
| MLflow DNS rebinding | platform-helm-authoring | ~5 |
| sshfs/chown details | platform-k3d-networking | ~10 |
| GitLab CI gotchas | platform-gitlab-ci | ~10 |
| Detailed env var examples | Keep summary only | ~20 |
| **Total savings** | | **~125 lines** |

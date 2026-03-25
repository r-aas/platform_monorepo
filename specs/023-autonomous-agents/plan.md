# Implementation Plan: Autonomous Platform Team

**Branch**: `023-autonomous-agents` | **Date**: 2026-03-25 | **Spec**: [spec.md](./spec.md)

## Summary

Create 6 specialized Claude Code subagents (platform-doctor, merge-reviewer, rules-curator, benchmark-runner, n8n-fixer, docs-sync), add worktree isolation to factory worker, implement persistent agent memory, and set up hook-triggered agent spawning.

## Technical Context

**Language/Version**: Markdown (agent definitions), Bash (Taskfile tasks, test scripts)
**Primary Dependencies**: Claude Code agents system (~/.claude/agents/), git worktrees
**Storage**: Agent memory at ~/.claude/agent-memory/{name}/
**Testing**: Manual invocation + scheduled task dry runs
**Target Platform**: macOS, Claude Code CLI
**Project Type**: Configuration + agent definitions

## Design Decisions

### D1: Agent location — global vs per-repo
**Decision**: Global (~/.claude/agents/) for platform-wide agents. Per-repo (.claude/agents/) for project-specific ones.
**Rationale**: platform-doctor, rules-curator work across all repos. merge-reviewer could be per-repo for project-specific rules.

### D2: Worktree isolation — Claude Code feature vs raw git
**Decision**: Raw git worktrees managed by factory-worker prompt.
**Rationale**: Claude Code's worktree feature is for interactive sessions. Factory worker needs programmatic control. Use `git worktree add`, work, commit, `git worktree remove`.

### D3: Agent memory — filesystem vs MCP
**Decision**: Filesystem at ~/.claude/agent-memory/{name}/MEMORY.md. Shared patterns at ~/.claude/agent-memory/shared/.
**Rationale**: Simple, git-trackable, no external dependencies. Migrate to DataHub when spec 025 ships.

### D4: Benchmark runner — scheduled task vs on-demand agent
**Decision**: Scheduled task (like factory-worker) running nightly.
**Rationale**: Benchmarks take 25+ minutes. Better as background job than interactive agent.

### D5: Hook-triggered merge review — PostToolUse vs manual
**Decision**: Start manual (@merge-reviewer), add hook trigger after proving value.
**Rationale**: Hook-triggered agents are experimental. Prove the agent works manually first.

## Implementation Phases

### Phase 1: Agent Definitions (P1 stories)
Create agent .md files with proper frontmatter, system prompts, and diagnostic workflows.

Agents already created (Tier 1): platform-doctor, merge-reviewer, rules-curator.
Agents to create (Tier 2): benchmark-runner, n8n-fixer, docs-sync.

### Phase 2: Agent Memory Infrastructure
Create directory structure, shared memory conventions, and startup memory loading.

### Phase 3: Factory Worker Worktree Isolation
Modify factory-worker SKILL.md to use git worktrees instead of lock files.

### Phase 4: Benchmark Runner Scheduled Task
Create benchmark-runner as a scheduled task that runs nightly evals.

### Phase 5: Taskfile Integration
Add `task agents:list`, `task agents:test`, `task agents:invoke` tasks.

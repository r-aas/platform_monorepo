# Tasks: 024 — P0 Hooks & Rules System

**Generated from**: [plan.md](./plan.md) | **TDD**: test file before implementation

## Phase 1: Hook Scripts

### T001: kubectl-guard in barrier.sh
- [x] Test: `tests/hooks/test_barrier.sh` — verify kubectl delete/drain/cordon blocked, kubectl get/describe allowed
- [x] Impl: `~/.claude/hooks/barrier.sh` — add kubectl destructive command patterns
- **Depends on**: nothing
- **Files**: `~/.claude/hooks/barrier.sh`
- **AC**: SC-001 (100% destructive kubectl blocked)

### T002: secret-detect in barrier.sh
- [x] Test: `tests/hooks/test_barrier.sh` — verify git add .env blocked, git add src/main.py allowed
- [x] Impl: `~/.claude/hooks/barrier.sh` — add git secret patterns
- **Depends on**: T001
- **Files**: `~/.claude/hooks/barrier.sh`
- **AC**: SC-002 (100% .env commits blocked)

### T003: argocd-ownership.sh
- [x] Test: `tests/hooks/test_argocd_ownership.sh` — verify helm upgrade blocked when ArgoCD app exists, allowed when not
- [x] Impl: `~/.claude/hooks/argocd-ownership.sh` — new script
- **Depends on**: nothing
- **Files**: `~/.claude/hooks/argocd-ownership.sh`
- **AC**: SC-003 (100% ArgoCD-managed releases protected)

### T004: no-ollama-container in write-guard.sh
- [x] Test: `tests/hooks/test_write_guard.sh` — verify ollama in compose YAML blocked
- [x] Impl: `~/.claude/hooks/write-guard.sh` — add ollama container check
- **Depends on**: nothing
- **Files**: `~/.claude/hooks/write-guard.sh`
- **AC**: FR-004

### T005: n8n-workflow-lint.sh
- [x] Test: `tests/hooks/test_n8n_lint.sh` — verify process.env and axios warnings
- [x] Impl: `~/.claude/hooks/n8n-workflow-lint.sh` — new PostToolUse script
- **Depends on**: nothing
- **Files**: `~/.claude/hooks/n8n-workflow-lint.sh`
- **AC**: FR-005

## Phase 2: settings.json Bindings

### T006: Update settings.json hook bindings
- [x] Impl: `~/.claude/settings.json` — add argocd-ownership.sh and n8n-workflow-lint.sh bindings
- **Depends on**: T003, T005
- **Files**: `~/.claude/settings.json`

## Phase 3: CLAUDE.md Pruning

### T007: Migrate ARM64 content to platform-helm-authoring skill
- [x] Impl: Move ARM64 compatibility table + JRE crash details + known-bad/good image tables
- **Depends on**: nothing
- **Files**: `~/.claude/skills/platform-helm-authoring/SKILL.md`, `~/work/CLAUDE.md`
- **AC**: SC-004, SC-005

### T008: Migrate k3d networking to platform-k3d-networking skill
- [x] Impl: Move host networking table, sshfs/chown fix, local-path provisioner details
- **Depends on**: nothing
- **Files**: `~/.claude/skills/platform-k3d-networking/SKILL.md`, `~/work/CLAUDE.md`

### T009: Migrate GitLab CI gotchas to platform-gitlab-ci skill
- [x] Impl: Move bitnami/kubectl entrypoint, gitleaks GIT_DEPTH, pip-audit pattern
- **Depends on**: nothing
- **Files**: `~/.claude/skills/platform-gitlab-ci/SKILL.md`, `~/work/CLAUDE.md`

### T010: Migrate n8n gotchas to genai-mlops-workflows skill
- [x] Impl: Verify all n8n gotchas from CLAUDE.md exist in skill (partially done already)
- **Depends on**: nothing
- **Files**: `~/.claude/skills/genai-mlops-workflows/SKILL.md`, `~/work/CLAUDE.md`

### T011: Prune CLAUDE.md — remove migrated sections
- [x] Impl: Remove migrated content, keep 1-line summaries with "see skill X for details"
- **Depends on**: T007, T008, T009, T010
- **Files**: `~/work/CLAUDE.md`
- **AC**: SC-004 (under 200 lines) — achieved: 171 lines

## Phase 4: PostCompact Hook

### T012: post-compact-context.sh
- [x] Test: Verify critical rules text is emitted on stdout
- [x] Impl: `~/.claude/hooks/post-compact-context.sh` — new script
- **Depends on**: T011 (needs final CLAUDE.md to know what to reinject)
- **Files**: `~/.claude/hooks/post-compact-context.sh`, `~/.claude/settings.json`
- **AC**: SC-006

## Verification

### T013: End-to-end hook verification
- [x] Run test script that simulates all blocked/allowed scenarios
- [x] Verify CLAUDE.md line count < 200 (171 lines)
- [x] Verify migrated content accessible via skills (ARM64: 21 refs, networking: 3 refs, CI: 3 refs, n8n: 1 ref)
- **Depends on**: T001-T012

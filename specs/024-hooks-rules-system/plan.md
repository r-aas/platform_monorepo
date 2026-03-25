# Implementation Plan: P0 Hooks & Rules System Overhaul

**Branch**: `024-hooks-rules-system` | **Date**: 2026-03-25 | **Spec**: [spec.md](./spec.md)

## Summary

Implement 5 PreToolUse/PostToolUse hook scripts that enforce platform safety rules deterministically, prune ~/work/CLAUDE.md from 700+ lines to under 200 by migrating details to context-activated skills, and add a PostCompact hook that re-injects critical rules after context compaction.

## Technical Context

**Language/Version**: Bash (hooks), Markdown (CLAUDE.md, skills)
**Primary Dependencies**: jq (JSON parsing in hooks), kubectl (ArgoCD ownership check)
**Storage**: N/A — hooks are stateless scripts
**Testing**: Manual verification via Claude Code tool invocations + automated test script
**Target Platform**: macOS (Apple Silicon), Claude Code CLI
**Project Type**: Configuration + scripts (no compiled code)
**Performance Goals**: Every hook completes in under 2 seconds
**Constraints**: Hooks receive JSON on stdin, exit 0 (allow) or exit 2 (block with message)

## Constitution Check

No constitution.md is filled yet for this repo. Applying CLAUDE.md principles:
- ✅ TDD: Hook test script verifies each hook
- ✅ uv only: No Python dependencies (pure bash + jq)
- ✅ Anti-sprawl: Extending existing barrier.sh where possible
- ✅ No temp files: Hooks are stateless, no artifacts

## Project Structure

### Source Code

```text
~/.claude/hooks/
├── barrier.sh                  # EXISTING — extend with kubectl guards + secret detection
├── write-guard.sh              # EXISTING — extend with Ollama container check
├── n8n-workflow-lint.sh         # NEW — PostToolUse warning for n8n sandbox violations
├── argocd-ownership.sh          # NEW — PreToolUse block for ArgoCD-managed releases
├── post-compact-context.sh      # NEW — re-inject critical rules after compaction

~/.claude/settings.json          # UPDATE — add new hook bindings

~/.claude/skills/
├── platform-helm-authoring/SKILL.md    # UPDATE — absorb ARM64 table + Bitnami notes
├── platform-k3d-networking/SKILL.md    # UPDATE — absorb sshfs/chown + host networking
├── platform-gitlab-ci/SKILL.md         # UPDATE — absorb CI gotchas
├── genai-mlops-workflows/SKILL.md      # UPDATE — absorb n8n gotchas (already partially done)

~/work/CLAUDE.md                 # PRUNE — remove migrated sections, keep principles only
```

## Research (Phase 0)

### Reference Patterns from ~/work/clones/claude-code/claude-code-hooks-mastery

Hook stdin JSON format:
```json
{
  "tool_name": "Bash",
  "tool_input": {
    "command": "kubectl delete pod X",
    "description": "..."
  }
}
```

Exit codes: 0 = allow, 2 = block (stdout shown as blocking reason)

Field extraction pattern:
```bash
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty')
```

### Existing barrier.sh Analysis

Current barrier.sh blocks: `rm -rf /`, `mkfs`, `dd if=`, format/fdisk, shutdown/reboot, iptables flush, `> /dev/sd`. Does NOT block destructive kubectl or secret commits. Safe to extend.

### ArgoCD Ownership Detection

Check if a Helm release is ArgoCD-managed:
```bash
kubectl get app -n platform -o name 2>/dev/null | grep -q "$RELEASE_NAME"
```
Caveat: `kubectl` call adds ~500ms latency. Acceptable within 2s budget.

## Design Decisions

### D1: Extend barrier.sh vs separate scripts
**Decision**: Separate scripts per concern. barrier.sh stays for OS-level dangers. New scripts for platform-specific rules.
**Rationale**: Single-responsibility. Easier to test, disable, and evolve independently.

### D2: ArgoCD check — live query vs cached
**Decision**: Live kubectl query on each helmfile/helm command.
**Rationale**: ArgoCD state changes during sessions. Cached data would go stale. 500ms latency is acceptable for rare helm commands.

### D3: n8n lint — PreToolUse (block) vs PostToolUse (warn)
**Decision**: PostToolUse warning (not blocking).
**Rationale**: n8n workflow JSON edits are iterative. Blocking would be too aggressive. Warning lets Claude self-correct on the next edit.

### D4: CLAUDE.md target line count
**Decision**: Under 200 lines for ~/work/CLAUDE.md. Per-repo CLAUDE.md stays as-is.
**Rationale**: Research shows instruction-following degrades beyond ~150-200 rules. The global CLAUDE.md is loaded in every session.

### D5: PostCompact injection content
**Decision**: Inject a focused 20-line block with: toolchain (uv, Taskfile), safety (no containerized Ollama, ARM64 awareness), quality gates, and the single most important rule per domain.
**Rationale**: PostCompact has limited token budget. Inject only what Claude is most likely to forget.

## Implementation Phases

### Phase 1: Hook Scripts (FR-001 through FR-005)

**1a. kubectl-guard additions to barrier.sh** (FR-001)
Add regex patterns for: `kubectl delete`, `kubectl drain`, `kubectl cordon`, `kubectl taint`, `kubectl scale.*--replicas=0`
Allow: `kubectl get`, `kubectl describe`, `kubectl logs`, `kubectl exec`, `kubectl apply`

**1b. secret-detect additions to barrier.sh** (FR-002)
Add patterns for: `git add .*\.env`, `git add .*secret`, `git add .*credential`, `git add .*token`
Check staged files: parse `git diff --cached --name-only` if command is `git commit`

**1c. argocd-ownership.sh** (FR-003)
New script. Triggers on commands matching `helmfile sync|helm upgrade|helm install`.
Queries `kubectl get app -n platform -o name` for matching release.
Blocks with ArgoCD sync guidance if found. Allows if ArgoCD not deployed (fresh bootstrap).

**1d. no-ollama-container check in write-guard.sh** (FR-004)
Extend write-guard.sh: if file_path matches `*compose*.yml` or `charts/**/*.yml`, grep new content for `ollama`. Block with guidance.

**1e. n8n-workflow-lint.sh** (FR-005)
New PostToolUse script. Triggers on Write/Edit of `*.json` in workflow directories.
Scans for: `process.env`, `require('axios')`, `require('http')`, `require('node-fetch')`, `$helpers.httpRequest`.
Outputs warning (not blocking) with specific fix guidance.

### Phase 2: settings.json Update (FR-010)

Add new hooks to settings.json bindings:
```json
{
  "PreToolUse": [
    {"matcher": "Bash", "hooks": [
      {"type": "command", "command": "~/.claude/hooks/barrier.sh"},
      {"type": "command", "command": "~/.claude/hooks/argocd-ownership.sh"}
    ]},
    {"matcher": "Write|Edit", "hooks": [
      {"type": "command", "command": "~/.claude/hooks/write-guard.sh"}
    ]}
  ],
  "PostToolUse": [
    {"matcher": "Write|Edit", "hooks": [
      {"type": "command", "command": "~/.claude/hooks/python-edit.sh"},
      {"type": "command", "command": "~/.claude/hooks/n8n-workflow-lint.sh"}
    ]}
  ]
}
```

### Phase 3: CLAUDE.md Pruning (FR-006)

Migration map:

| Section to Remove | Target Skill | Action |
|-------------------|-------------|--------|
| APPLE SILICON / GPU CONSTRAINT (lines 170-210) | platform-helm-authoring | Move ARM64 table + JRE crash details |
| Docker Image ARM64 Compatibility (lines 178-207) | platform-helm-authoring | Move known-bad/good image tables |
| K3D Host Networking (lines 307-315) | platform-k3d-networking | Move host IP table + verification command |
| MLflow DNS Rebinding (lines 338-340) | platform-helm-authoring | Move extraFlags fix |
| sshfs + chown (from memory) | platform-k3d-networking | Move local-path provisioner fix |
| GitLab CI Networking Gotchas (lines 378-383) | platform-gitlab-ci | Move bitnami/kubectl + gitleaks + pip-audit |
| Detailed env var examples (lines 233-244) | Keep 1-line summary | Remove code blocks, keep principle |

**Keep in CLAUDE.md**: Persona, communication style, maintenance instructions, work root layout, toolchain (1 line each), core principles, Python conventions (brief), Ollama (brief), LiteLLM (brief), k3d cluster (brief lifecycle commands), Taskfile conventions, speckit overview, skills overview, development principles, rules.

### Phase 4: PostCompact Hook (FR-007)

New `post-compact-context.sh` bound to PreCompact event (fires just before compaction, injecting rules into the context that survives).

Injection content (~20 lines):
```
CRITICAL RULES (survive compaction):
- Python: uv only, never pip/venv/poetry
- Containers: Never containerize Ollama (GPU needs native Metal)
- k3d: Pods reach Mac host at 192.168.5.2, NOT host.docker.internal
- ArgoCD: Never helmfile sync if ArgoCD manages the resource
- n8n: Code nodes CANNOT make outbound HTTP. Use HTTP Request nodes.
- Helm: All images must be ARM64-native or explicitly set platform: linux/amd64
- Git: Never force push, never amend published commits
- Quality: Tests pass, lint clean, no hardcoded values, secrets externalized
```

## Verification Plan

1. **Hook tests**: Script that simulates tool inputs and verifies exit codes
2. **CLAUDE.md line count**: `wc -l ~/work/CLAUDE.md` < 200
3. **Skill content check**: Verify migrated content exists in target skills via grep
4. **Manual test**: Start new Claude Code session, attempt blocked operations, verify behavior

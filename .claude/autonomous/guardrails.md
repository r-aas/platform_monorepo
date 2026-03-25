# Factory Guardrails

<!-- These are HARD constraints. Workers MUST check these before acting. -->
<!-- Only R can modify this file. Workers must never edit guardrails.md. -->

## Spawn Limits

- **Max total spawned tasks: 5** (not counting `factory-worker` itself)
- Before spawning, call `list_scheduled_tasks` and count. If >= 6 total tasks exist, DO NOT spawn.
- Log the denied spawn in lessons.md with reason "spawn cap reached"

## Prompt Self-Update Limits

- **Max 3 prompt self-updates per day** across all workers
- Before self-updating, check the "Prompt Update History" section in lessons.md
- Count entries with today's date. If >= 3, defer the update to next run.
- **Max diff size: 20 lines added/changed per update** — no wholesale rewrites
- **Never delete existing guardrail references** from any prompt
- **Always log** the update in lessons.md "Prompt Update History" before applying

## Concurrency Protection (Worktree Isolation)

Workers use **git worktrees** for isolation instead of lock files:
- Create a worktree at `/tmp/factory-worktree-$$` on a temporary branch
- All work happens in the worktree — never modify the main working tree directly
- Multiple workers CAN run simultaneously (each gets its own worktree)
- On completion: fast-forward merge to main if possible, otherwise flag for R
- **Always clean up worktree** at end of run: `git worktree remove <path> --force`
- Clean up the temporary branch after merge: `git branch -d <branch>`
- If worktree creation fails (e.g., /tmp full), abort

## Lessons Size Limits

- **Max 50 entries per section** in lessons.md
- When a section hits 50, append `<!-- DISTILLATION NEEDED — section full -->` and stop adding
- This triggers the `lessons-distiller` task (if it exists) or flags for R

## Backlog Health

- **Max 30 unchecked items** in any single priority level in ledger.md
- If a priority level has > 30 unchecked items, do NOT add more — log a warning instead
- If the ratio of completed-to-unchecked drops below 0.5, add a health warning to the Evolution Log

## Git Safety

- **Never force push**
- **Never amend commits** — always create new ones
- **Never commit if tests are failing** — fix first or abort
- **After committing, run tests again** to verify the commit didn't break anything
- If post-commit tests fail, **immediately revert**: `git revert HEAD --no-edit` and log the incident
- **Uncommitted changes abort**: If `git status` shows changes and the last commit wasn't made by a factory worker (check commit message for `[B.xx]` pattern), abort. Don't try to stash or work around R's changes.
- **Always stage files explicitly** — never use `git add .` or `git add -A`. List each file by path.
- **Never commit generated artifacts**: `__pycache__/`, `*.pyc`, `.venv/`, `dist/`, `*.egg-info/`, `.python-version`, node_modules/. Check `.gitignore` before staging.
- **Pre-commit check**: Before `git commit`, run `git diff --cached --name-only` and verify no ignored/generated files are staged. If any are, `git rm --cached` them first.

## Scope Containment

- **Workers only modify files under** `services/agent-gateway/`, `agents/`, `skills/`, `charts/`, and `.claude/autonomous/`
- **Never modify**: `CLAUDE.md`, `.claude/commands/`, `.claude/skills/`, `specs/`, `Taskfile.yml` (root), `envs/`, `manifests/`
- **Never create files outside** the allowed directories above
- **Never delete files** unless the task explicitly calls for it

## Self-Update Boundaries

Workers may update their own prompt but MUST preserve these sections unchanged:
- Abort Conditions
- Quality Gates
- "What NOT To Do"
- All references to guardrails.md
- The boot sequence step that reads guardrails.md

Workers may ADD to these sections but never remove or weaken existing rules.

## Circuit Breaker

If a worker encounters **3 consecutive aborts** (tracked via Evolution Log in ledger.md):
- Do NOT attempt the next task
- Instead, write a diagnostic entry in lessons.md explaining the pattern
- Add `<!-- CIRCUIT BREAKER TRIPPED — needs R's attention -->` to ledger.md Current Phase
- The pattern of 3 aborts suggests a systemic issue that needs human judgment

## Emergency Stop

R can halt all factory work instantly by creating:
`/Users/r/work/repos/platform_monorepo/.claude/autonomous/.factory-stop`

Workers MUST check for this file in the boot sequence. If it exists, exit immediately with no changes.

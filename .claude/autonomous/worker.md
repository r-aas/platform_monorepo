# Factory Worker Prompt — Reference Copy

<!-- This is a reference copy for R to review. The live prompt is in the scheduled task. -->
<!-- Only R edits this file. Workers must never modify worker.md. -->
<!-- Last synced: 2026-03-20 -->

See the live prompt via: list_scheduled_tasks → factory-worker

## Guardrail Summary (enforced in live prompt)

1. **Emergency stop**: `.factory-stop` file halts all workers instantly
2. **Concurrency lock**: `.factory-lock` file prevents overlapping runs (20-min staleness)
3. **Spawn cap**: Max 5 spawned tasks total (6 including factory-worker)
4. **Self-update cap**: Max 3 prompt updates per day, max 20 lines per update
5. **Lessons cap**: Max 50 entries per section before distillation required
6. **Backlog cap**: Max 30 items per priority level
7. **Scope containment**: Only modify allowed directories
8. **Circuit breaker**: 3 consecutive aborts → halt and wait for R
9. **Post-commit verification**: Tests run after commit, auto-revert if broken
10. **Self-update boundaries**: Can add rules, never relax existing ones

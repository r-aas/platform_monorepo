# Factory Lessons Learned

<!-- Accumulated by factory workers. Each lesson improves future runs. -->
<!-- Format: YYYY-MM-DD | source task | lesson -->
<!-- Workers: append here. R: review and prune periodically. -->
<!-- HARD LIMIT: Max 50 entries per section. When a section hits 50, stop appending and add a note requesting distillation. -->

## Patterns

<!-- Reusable approaches that worked. Max 50 entries. -->
- 2026-03-21 | B.02 | Graceful fallback pattern: `get_embedding()` returns `None` on any Exception; `hybrid_score(kw, None)` returns keyword score unchanged. Makes embedding integration safe to ship without a running Ollama.
- 2026-03-21 | B.02 | For search utilities (embedding, scoring), write unit tests independently of the router tests. Pure functions are easy to test in isolation; router-level tests can assume the utility works.

## Anti-Patterns

<!-- Approaches that failed and why. Max 50 entries. -->
- 2026-03-20 | factory-worker run 1 | Committed __pycache__/ and .python-version because `git add` included generated files. Fix: always check `git diff --cached --name-only` before committing and verify no gitignored artifacts are staged.
- 2026-03-20 | factory-worker run 1 | Skipped self-improvement loop entirely (didn't update ledger checkboxes, lessons, or RESUME). The execution protocol completed but the "after" steps were dropped. Fix: self-improvement steps must run even if time-pressured — they are not optional.
- 2026-03-21 | factory-worker boot | Post-commit `uv run pytest` MUST be run from `services/agent-gateway/`, NOT from monorepo root. Running from root fails with ModuleNotFoundError on agent_gateway. Always cd to service dir before running pytest.
- 2026-03-21 | factory-worker boot | Pre-existing test failures from factory's own prior commit (B.09 broke test_registry.py by updating get_prompt→get_prompt_version without updating mocks). Boot protocol "tests failing → abort" is too blunt. When failures are in factory-authored tests (not R's code), fix them as prerequisite work before proceeding with the selected task.

## Task Templates

<!-- When the factory identifies a recurring task shape, capture it here -->
<!-- These templates can seed new scheduled tasks -->

## Spawned Tasks

<!-- Log of scheduled tasks created by the factory -->
<!-- Format: date | task-id | reason | schedule -->
<!-- HARD LIMIT: Max 5 total spawned tasks. If 5 exist, DO NOT spawn more — add to backlog instead. -->

## Prompt Update History

<!-- Log EVERY self-update to any scheduled task prompt -->
<!-- Format: date | task-id | what changed | why -->
<!-- HARD LIMIT: Max 3 self-updates per calendar day across all workers. If 3 reached, defer to next day. -->

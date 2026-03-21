# Factory Lessons Learned

<!-- Accumulated by factory workers. Each lesson improves future runs. -->
<!-- Format: YYYY-MM-DD | source task | lesson -->
<!-- Workers: append here. R: review and prune periodically. -->
<!-- HARD LIMIT: Max 50 entries per section. When a section hits 50, stop appending and add a note requesting distillation. -->

## Patterns

<!-- Reusable approaches that worked. Max 50 entries. -->
- 2026-03-21 | B.02 | Graceful fallback pattern: `get_embedding()` returns `None` on any Exception; `hybrid_score(kw, None)` returns keyword score unchanged. Makes embedding integration safe to ship without a running Ollama.
- 2026-03-21 | B.02 | For search utilities (embedding, scoring), write unit tests independently of the router tests. Pure functions are easy to test in isolation; router-level tests can assume the utility works.
- 2026-03-21 | B.04 | Workflow GitOps pattern: pure transformation functions (strip/sort/portabilize) test without any mocks. Network I/O (fetch/import) is thin wrappers — test the logic separately. This decomposition made 21 tests pass with zero mocking complexity.
- 2026-03-21 | B.05 | Benchmark runner pattern: pure evaluate_case() function covers all evaluation logic (strings, tools, latency). BenchmarkResult dataclass with computed properties (pass_rate, avg_latency) avoids state mutation. 17 tests with zero mocking needed for the core evaluation logic.
- 2026-03-21 | B.06 | MCP server pattern: JSON-RPC 2.0 over HTTP POST — single endpoint handles all methods via method dispatch. No external MCP library needed — FastAPI + dict dispatch is sufficient for a stub. Success results omit isError key entirely; only error results set isError:true.

## Anti-Patterns

<!-- Approaches that failed and why. Max 50 entries. -->
- 2026-03-20 | factory-worker run 1 | Committed __pycache__/ and .python-version because `git add` included generated files. Fix: always check `git diff --cached --name-only` before committing and verify no gitignored artifacts are staged.
- 2026-03-20 | factory-worker run 1 | Skipped self-improvement loop entirely (didn't update ledger checkboxes, lessons, or RESUME). The execution protocol completed but the "after" steps were dropped. Fix: self-improvement steps must run even if time-pressured — they are not optional.
- 2026-03-21 | factory-worker boot | Post-commit `uv run pytest` MUST be run from `services/agent-gateway/`, NOT from monorepo root. Running from root fails with ModuleNotFoundError on agent_gateway. Always cd to service dir before running pytest.
- 2026-03-21 | factory-worker boot | Pre-existing test failures from factory's own prior commit (B.09 broke test_registry.py by updating get_prompt→get_prompt_version without updating mocks). Boot protocol "tests failing → abort" is too blunt. When failures are in factory-authored tests (not R's code), fix them as prerequisite work before proceeding with the selected task.
- 2026-03-21 | B.06 | Registry functions (get_agent, list_agents) are async. Do NOT wrap with asyncio.to_thread() — await directly. Only skills_registry functions (get_skill, list_skills, etc.) are sync and need to_thread. Check with grep "^async def" in the target module before writing dispatch code.
- 2026-03-21 | B.10/B.11 | For YAML skill definitions, TDD = test loads and validates the YAML via SkillDefinition.model_validate(). Write test → YAML missing → tests fail red → create YAML → green. Clean TDD loop for declarative config files.
- 2026-03-21 | B.10/B.11 | Path traversal from test file to monorepo root: services/agent-gateway/tests/ is 4 levels deep (tests→agent-gateway→services→platform_monorepo). Use Path(__file__).parent * 4. 5 parents goes one level too far to repos/.

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

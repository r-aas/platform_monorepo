Read the skill at ~/.claude/skills/$ARGUMENTS/SKILL.md and its evals at ~/.claude/skills/$ARGUMENTS/evals.yml.

If no evals.yml exists, help create one following the autoresearch methodology:
- 3-5 diverse scenarios (different use cases, not the same one repeated)
- 4-8 binary yes/no criteria (not too narrow, not too many)
- Criteria must be LLM-judgeable (another model can answer yes/no by reading the output)
- No Likert scales — binary only
- Scenario diversity prevents overfitting to one prompt

Then run the optimization loop:

1. Back up current SKILL.md to SKILL.md.bak
2. Run: uv run scripts/skill-optimize.py --skill-name $ARGUMENTS --verbose
3. Parse the JSON output from stdout. Stderr has progress logs.
4. Analyze failure patterns — which criteria fail most? Which scenarios?
5. Propose a targeted mutation to SKILL.md that addresses the most common failures
6. Apply the mutation to SKILL.md
7. Re-run: uv run scripts/skill-optimize.py --skill-name $ARGUMENTS --verbose
8. Compare scores:
   - If pass_rate improved: KEEP the mutation. Log it to ~/.claude/skills/$ARGUMENTS/mutations.md
   - If pass_rate regressed or stayed the same: REVERT from SKILL.md.bak. Log the failed attempt too.
9. Copy current SKILL.md to SKILL.md.bak (new baseline for next iteration)
10. Repeat from step 5

Stop conditions (whichever comes first):
- 3 consecutive iterations with no improvement (convergence)
- pass_rate >= pass_threshold from evals.yml
- Manual interruption by user

Log each iteration to ~/.claude/skills/$ARGUMENTS/mutations.md with this format:

```markdown
## Iteration N (keep|discard: X.XX -> Y.YY)
- **What changed**: Description of the mutation
- **Why**: Which failure patterns motivated it
- **Criteria improved**: list
- **Criteria regressed**: list (if any)
- **Lesson**: What this teaches about the skill's prompt design
```

Rules:
- NEVER modify evals.yml during optimization — that is the fixed evaluation, not the thing being optimized
- Keep mutations focused — one change per iteration, not wholesale rewrites
- If a mutation makes the skill longer than 500 lines, find ways to compress instead
- Prefer structural changes (reordering, reformatting) over adding more text
- If the baseline score is already above pass_threshold, report it and ask if optimization is still desired
- Always show the current score and failure summary between iterations so the user can follow progress

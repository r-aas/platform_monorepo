# Platform Monorepo — Session Resume

## Session: 2026-03-21 — Factory Worker Run 6

### Built

- **prompt-engineering skill** — `skills/prompt-engineering.yaml`
  - Tags: prompt, optimization, eval
  - MCP servers: genai namespace (MLflow tools for experiment tracking)
  - 4 tasks: design-variants, run-evals, compare-results, apply-best
  - Prompt fragment: A/B eval methodology guidance

- **code-generation skill** — `skills/code-generation.yaml`
  - Tags: code, generation, testing
  - MCP servers: genai namespace (GitLab tools for file + MR management)
  - 4 tasks: generate-code, modify-code, verify-tests, review-diff
  - Prompt fragment: TDD-first code generation guidance

- **Skill YAML tests extended** — `services/agent-gateway/tests/test_skill_yamls.py`
  - 16 new schema validation tests (8 per skill, same pattern as B.10/B.11)

### Test Status

121 tests passing:
- test_skill_yamls.py (32) — B.10/B.11/B.12/B.13 schema validation
- All prior 89 tests still passing

### Commits This Session

- `116bc25` feat(agent-gateway): skill YAMLs for prompt-engineering and code-generation [B.12] [B.13]

### Branch

`001-agent-gateway` — clean

### What's NOT Done (B items remaining)

| Item | What | Status |
|------|------|--------|
| B.07 | Python runtime | Blocked (needs pyagentspec eval) |
| B.08 | Claude Code runtime | Blocked (needs headless testing) |
| B.14 | Skill: documentation | Priority 2 — next |
| B.15 | Skill: security-audit | Priority 2 |
| B.16-B.18 | New agents | Priority 3 |

### Next Steps

- [local] B.14: Skill YAML — documentation (generate docs from code, specs, conversations) in `skills/documentation.yaml`
- [local] B.15: Skill YAML — security-audit (scan code/infra for vulnerabilities) in `skills/security-audit.yaml`
- [local] Use test_skill_yamls.py pattern — add 8 tests per skill (section headers B.14, B.15)

### Notes

- Path from test to skills dir: `Path(__file__).parent.parent.parent.parent` (4 parents)
- Skill YAML TDD loop: write tests → confirm red (FileNotFoundError) → create YAML → green
- `uv run pytest` MUST be run from `services/agent-gateway/`, not monorepo root
- P2 is now 4/6 done. B.14-B.15 will complete P2.
- After P2 done, B.16-B.18 (agents) can compose from the 6+ skills.

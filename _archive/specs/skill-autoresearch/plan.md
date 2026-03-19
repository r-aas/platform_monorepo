<!-- status: planned -->
# Skill Auto-Research: Self-Improving Skills via Autonomous Optimization

## Origin

Adapted from [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) methodology.
Video source: [Stop Fixing Your Claude Skills. Autoresearch Does It For You](https://www.youtube.com/watch?v=qKU-e0x2EmE)

## Core Insight

Skills are prompts. Prompts are noisy (~70% reliable). Instead of manually tweaking them,
create a closed-loop system that:

1. **Runs** a skill N times against test scenarios
2. **Evaluates** each output against binary (yes/no) criteria
3. **Scores** total passes out of max (criteria × runs)
4. **Mutates** the SKILL.md prompt to fix failures
5. **Keeps** the winner, discards regressions
6. **Loops** autonomously until convergence or manual stop

The changelog of mutations is itself a valuable artifact — future models pick up where predecessors left off.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                /skill-optimize <name>                │
│  (Claude Code command — the "program.md" equivalent) │
└──────────┬──────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│              Test Harness (Python script)            │
│  scripts/skill-optimize.py                          │
│                                                     │
│  1. Load SKILL.md + evals.yml + scenarios.yml       │
│  2. For each scenario:                              │
│     - Invoke skill via `claude -p` subprocess       │
│     - Capture output                                │
│  3. For each output × each eval criterion:          │
│     - Judge with fast model (binary yes/no)         │
│  4. Score = passed / total                          │
│  5. Log to results.tsv                              │
│  6. Return score + failures to optimizer            │
└──────────┬──────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│              Optimization Loop (in command)          │
│                                                     │
│  LOOP:                                              │
│    1. Run test harness → get score                  │
│    2. If score > best_score: keep SKILL.md, advance │
│    3. If score <= best_score: revert SKILL.md       │
│    4. Analyze failure patterns                      │
│    5. Mutate SKILL.md to address failures           │
│    6. Commit mutation                               │
│    7. Repeat                                        │
└─────────────────────────────────────────────────────┘
```

### Mapping Karpathy → Skills

| autoresearch | skill-optimize |
|-------------|----------------|
| `train.py` | `SKILL.md` (the thing being optimized) |
| `prepare.py` | `evals.yml` + `scenarios.yml` (fixed eval — never modified) |
| `program.md` | `/skill-optimize` command (agent instructions) |
| `val_bpb` | eval pass rate (0.0 – 1.0) |
| `results.tsv` | `~/.claude/skills/<name>/results.tsv` |
| git branch `autoresearch/<tag>` | git branch `skill-opt/<name>` (or in-place with backup) |
| `uv run train.py` | `claude -p "<scenario>" --allowedTools ...` |

---

## Eval Criteria Format

Each skill gets an `evals.yml` file in its directory:

```yaml
# ~/.claude/skills/<name>/evals.yml
name: fastapi-templates
runs_per_iteration: 5          # how many times to run each scenario
pass_threshold: 0.85           # minimum pass rate to "keep" a mutation

scenarios:
  - name: basic-crud-api
    prompt: "Create a FastAPI app with CRUD endpoints for a 'tasks' resource with SQLite backend"

  - name: auth-api
    prompt: "Create a FastAPI app with JWT authentication and protected endpoints"

  - name: async-external-api
    prompt: "Create a FastAPI app that fetches data from an external API with retry logic"

criteria:
  - id: uses-uv
    question: "Does the output use uv (not pip) for dependency management?"

  - id: has-pydantic-models
    question: "Does the output define Pydantic models for request/response validation?"

  - id: has-error-handling
    question: "Does the output include proper HTTP error handling with appropriate status codes?"

  - id: has-async
    question: "Does the output use async def for route handlers?"

  - id: src-layout
    question: "Does the output follow src/{project_name}/ layout?"

  - id: no-hardcoded-secrets
    question: "Is the output free of hardcoded secrets, passwords, or API keys?"
```

### Design Rules (from video)

1. **Binary only** — every criterion is yes/no. No Likert scales. Scales compound variance.
2. **Not too narrow** — "Is the code under 200 lines?" will cause gaming. Keep criteria about quality, not arbitrary constraints.
3. **Not too many** — 4-8 criteria per skill is the sweet spot. More = model optimizes for test-passing, not actual quality.
4. **Scenario diversity** — test different use cases, not the same one 10 times. Prevents overfitting to one prompt.
5. **Criteria must be LLM-judgeable** — another model must be able to answer yes/no by reading the output.

### Scoring

```
max_score = len(scenarios) × runs_per_iteration × len(criteria)
actual_score = count of "yes" judgments
pass_rate = actual_score / max_score
```

Example: 3 scenarios × 5 runs × 6 criteria = 90 max. Score of 78 = 86.7% pass rate.

---

## Skill Categories & Pilot Selection

### Category Analysis

| Category | Skills | Eval Strategy | Difficulty |
|----------|--------|--------------|------------|
| **Artifact-producing** | pdf, xlsx, docx, frontend-design | Generate file, inspect output | Medium |
| **Code-generating** | fastapi-templates, docker-patterns, github-actions-templates | Generate code, check structure/correctness | Easy |
| **Text-generating** | cold-email-sequence-generator, career-helper | Generate text, check quality criteria | Easy |
| **Behavioral** | k8s-troubleshooting, debugging-strategies, code-review-excellence | Run against test scenario, check response quality | Hard |
| **Meta** | skill-authoring, skill-evolution, speckit-workflow | Run meta-task, check output | Hard |
| **Domain** | n8n-*, genai-mlops-*, private-* | Context-dependent, project-specific | Hard |

### Pilot Skills (start with easiest-to-eval)

1. **`fastapi-templates`** — code output, can verify structure, imports, patterns
2. **`docker-patterns`** — generates Dockerfiles, clear binary criteria (multi-stage? non-root? .dockerignore?)
3. **`cold-email-sequence-generator`** — text output, can check personalization, CTA, length, structure

These three cover code generation, config generation, and text generation — proving the system works across output types.

---

## Component Design

### 1. `skill-autoresearch` Skill

Location: `~/.claude/skills/skill-autoresearch/SKILL.md`

Purpose: Teaches Claude the autoresearch methodology for skills. Contains:
- How to write good eval criteria (binary, not too narrow, not too many)
- How to write diverse scenarios
- How to analyze failure patterns and mutate prompts effectively
- Anti-patterns (gaming evals, over-constraining, Likert scales)

### 2. `/skill-optimize` Command

Location: `~/.claude/commands/skill-optimize.md`

The "program.md" equivalent. Instructs Claude to:
1. Read the target skill's SKILL.md, evals.yml, scenarios.yml
2. If no evals.yml exists, help create one (guided by skill-autoresearch)
3. Run the optimization loop:
   - Back up current SKILL.md
   - Run test harness
   - Analyze failures
   - Propose mutation
   - Apply mutation
   - Re-run test harness
   - Keep or revert
   - Log to results.tsv
4. Never stop until manually interrupted or convergence (3 consecutive iterations with no improvement)

### 3. Test Harness Script

Location: `~/.claude/skills/skill-autoresearch/scripts/skill-optimize.py`

Python script (run with `uv run`) that:
- Takes skill name as arg
- Loads evals.yml from the skill directory
- For each scenario × run:
  - Invokes `claude -p "<prompt>" --output-format text` as subprocess
  - Captures output to temp file
- For each output × criterion:
  - Sends to judge model (Sonnet via claude CLI, or Ollama for cost savings)
  - Parses binary yes/no response
- Computes pass rate
- Writes results.tsv row
- Returns structured JSON: { score, pass_rate, failures: [{scenario, criterion, output_excerpt}] }

### 4. Results Log

Location: `~/.claude/skills/<name>/results.tsv`

```
iteration	pass_rate	score	max_score	status	description
0	0.722	65	90	baseline	original SKILL.md
1	0.789	71	90	keep	added explicit uv instruction + src layout requirement
2	0.756	68	90	discard	tried adding code examples (too verbose, lost structure)
3	0.844	76	90	keep	simplified to bullet checklist format
```

### 5. Mutation Changelog

Location: `~/.claude/skills/<name>/mutations.md`

Append-only log of what was tried:
```markdown
## Iteration 1 (keep: 0.722 → 0.789)
- Added explicit "use uv, never pip" instruction
- Added src/{name}/ layout requirement
- Failures fixed: uses-uv (was 3/15, now 14/15), src-layout (was 5/15, now 12/15)

## Iteration 2 (discard: 0.789 → 0.756)
- Added inline code examples for each pattern
- Regression: model started copying examples verbatim instead of adapting
- Lesson: examples constrain rather than guide for this skill type
```

This changelog is the "valuable asset" the video mentions — future models can read it and pick up where predecessors left off.

---

## Integration Points

### With Existing Skills

| Skill | Integration |
|-------|------------|
| `skill-evolution` | Add autoresearch as an evolution strategy. `/evolve` can suggest running `/skill-optimize` when a skill underperforms. |
| `skill-authoring` | Add eval authoring guidance. Every new skill should ship with evals.yml. |
| `tdd-orchestrator` | Parallel philosophy: tests first for code, evals first for skills. |

### With `/loop` Command

The `/loop` command can run `/skill-optimize` on a schedule:
```
/loop 5m /skill-optimize fastapi-templates
```

This enables overnight autonomous optimization — exactly what the video describes.

### With `/parallel` Command

Optimize multiple skills concurrently:
```
/parallel /skill-optimize fastapi-templates /skill-optimize docker-patterns /skill-optimize cold-email-sequence-generator
```

---

## Implementation Plan

### Phase 1: Foundation (this session)
1. Create `skill-autoresearch` skill with methodology
2. Create `evals.yml` for 3 pilot skills
3. Create `/skill-optimize` command
4. Create test harness script
5. Manual test: run one optimization iteration on `fastapi-templates`

### Phase 2: Validation (next session)
1. Run full optimization loop on all 3 pilot skills
2. Measure before/after pass rates
3. Review mutation changelogs for quality
4. Tune the system (judge prompt, mutation strategy, convergence criteria)

### Phase 3: Scale (subsequent sessions)
1. Write evals for remaining high-value skills
2. Create `/skill-optimize-all` meta-command
3. Integrate with `/evolve` and `skill-evolution`
4. Add eval authoring to `skill-authoring` as standard practice
5. Run overnight batch optimization

### Priority Order for Eval Authoring (after pilots)

| Priority | Skills | Why |
|----------|--------|-----|
| P0 | career-helper, code-review-excellence | High usage, high variance |
| P1 | modern-python, taskfile-patterns | Core workflow, must be reliable |
| P2 | mcp-development, github-actions-templates | Complex output, benefits from optimization |
| P3 | n8n-*, genai-mlops-workflows | Domain-specific, needs specialized evals |
| P4 | architecture-*, security-*, error-handling-* | Reference/teaching skills, lower urgency |

---

## Test Plan

### Unit Tests (test harness script)

| # | Test | Input | Expected | Pass Criteria |
|---|------|-------|----------|---------------|
| U1 | Load valid evals.yml | Well-formed YAML | Parsed config object | No errors, all fields present |
| U2 | Load malformed evals.yml | Missing `criteria` key | Clear error message | Exits with helpful error |
| U3 | Judge binary response parsing | "Yes", "No", "YES", "no", "Yes, because..." | True/False | Correctly extracts binary from various formats |
| U4 | Score calculation | 65 passes out of 90 | 0.722 pass_rate | Math is correct |
| U5 | Results.tsv append | New iteration data | Row appended | File not corrupted, TSV format valid |

### Integration Tests (single iteration)

| # | Test | Input | Expected | Pass Criteria |
|---|------|-------|----------|---------------|
| I1 | Baseline run | `fastapi-templates` with evals | Score + results.tsv | Completes without crash, score is reasonable (0.5-1.0) |
| I2 | Mutation produces different output | Run after mutation | Different SKILL.md content | SKILL.md changed, backup exists |
| I3 | Keep decision | Score improves | SKILL.md kept, status="keep" | results.tsv shows keep |
| I4 | Discard decision | Score regresses | SKILL.md reverted to backup | Content matches backup |
| I5 | Convergence detection | 3 iterations, no improvement | Loop stops | Exit message indicates convergence |

### System Tests (full loop)

| # | Test | Input | Expected | Pass Criteria |
|---|------|-------|----------|---------------|
| S1 | Full optimization run | `fastapi-templates`, 10 iterations max | Improved pass rate | Final > baseline by ≥5% |
| S2 | Mutation changelog quality | After 5+ iterations | Readable, useful changelog | Each entry has: what changed, why, result |
| S3 | No eval gaming | Review final SKILL.md | Genuine improvement | Skill still works for prompts NOT in scenarios |
| S4 | Cross-skill independence | Optimize 2 skills in parallel | Both improve independently | No interference between optimizations |
| S5 | Recovery from crash | Kill mid-iteration | Backup SKILL.md intact | Can resume or revert cleanly |

### Eval Quality Tests (meta — testing the evals themselves)

| # | Test | Input | Expected | Pass Criteria |
|---|------|-------|----------|---------------|
| E1 | Known-good output | Manually verified good skill output | High score (≥0.9) | Evals don't reject good work |
| E2 | Known-bad output | Deliberately poor skill output | Low score (≤0.3) | Evals catch real problems |
| E3 | Borderline output | Mediocre skill output | Mid score (0.4-0.7) | Evals discriminate, not binary all-or-nothing |
| E4 | Judge consistency | Same output judged 5 times | Consistent scores | Variance < 10% across runs |
| E5 | Criteria independence | Outputs that fail on one criterion only | Only that criterion fails | Criteria don't bleed into each other |

### Acceptance Criteria

The system is working when:
1. At least 2 of 3 pilot skills show ≥10% pass rate improvement after optimization
2. Mutation changelogs are readable and contain actionable insights
3. Optimized skills still work correctly on prompts NOT in the eval scenarios
4. The system can run unattended for 30+ minutes without crashing
5. Results are reproducible — re-running produces similar (not identical) trajectories

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Eval gaming (Goodhart's Law) | Skill passes evals but degrades for real use | Test with held-out scenarios not in evals.yml |
| Judge model inconsistency | Noisy scores make keep/discard unreliable | Use majority vote (3 judgments per criterion) |
| Over-mutation | Skill prompt becomes bloated/incoherent | Add simplicity criterion: "Is the SKILL.md under 500 lines and well-organized?" |
| Cost runaway | Many iterations × many runs × judge calls | Cap iterations, use Haiku for judging, batch |
| Prompt collapse | Mutation makes skill too specific to scenarios | Ensure scenarios are diverse, add "generality" eval |

---

## Cost Estimate

Per optimization iteration (one skill):
- 5 runs × 3 scenarios = 15 claude invocations (~$0.30 at Haiku rates for judging)
- 1 mutation analysis + proposal (~$0.05)
- **~$0.35/iteration**

Full optimization run (10 iterations): **~$3.50/skill**

All 51 skills: **~$180** (but only ~20 are high-value enough to optimize)

Top 20 skills: **~$70** for a one-time quality boost across the entire skill library.

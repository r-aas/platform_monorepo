<!-- status: deferred -->
<!-- parent: 009 -->
<!-- depends: 009a, 009b -->
<!-- note: eval-triad.py + agent-benchmark.py cover evaluation. Meta-agents (evaluator, curator, specifier) deferred. -->
# Spec 009d: Meta-Agents & Evaluation Triad

## Problem

The evaluation pipeline (`scripts/eval-triad.py`) runs benchmarks as an external script. There are no agents in the stack dedicated to evaluation, dataset curation, or task specification. The evaluation triad concept (dataset + method + metric) is implemented in Python but not formalized in the registry or accessible via API.

Skills are benchmarked ad-hoc. There is no systematic lifecycle: define what success looks like → build test cases → score outputs → iterate.

## Parent Spec

[Spec 009: AgenticOps Registries](../009-agentic-registries/spec.md) — this spec implements FR-002 (skills-as-shared-prompts completion), FR-009, FR-010.

## Dependencies

- **009a** (Structured Agent Tags) — meta-agents use structured tags
- **009b** (Registry APIs) — meta-agents registered via agent API, eval datasets via MLflow

## Requirements

### FR-001: Meta-Agent Definitions

Three specialized agents registered in the agent registry:

**Evaluator** (`evaluator`):
- Runs skill outputs through the `judge` prompt and scores them
- Uses MLflow to log evaluation results as experiment runs
- Skills: `mlops.evaluate`
- MCP servers: `mlflow`
- Model: configurable — can use a stronger cloud model via LiteLLM

**Curator** (`curator`):
- Generates and curates evaluation datasets for specific skills
- Produces input/expected-output pairs stored in MLflow datasets
- Skills: `curator.generate`, `curator.validate`
- MCP servers: `mlflow`

**Specifier** (`specifier`):
- Defines what a skill should do — acceptance criteria, edge cases, scoring rubrics
- Outputs structured task specifications that feed into evaluator and curator
- Skills: `specifier.define`, `specifier.rubric`
- MCP servers: `mlflow`

### FR-002: New Skill Prompts for Meta-Agents

Create 4 new skill prompts:
- `curator.generate` — generate diverse evaluation test cases for a named skill
- `curator.validate` — validate dataset quality, coverage, and difficulty distribution
- `specifier.define` — define task acceptance criteria and edge cases
- `specifier.rubric` — create structured scoring rubric for skill evaluation

### FR-003: Evaluation Triad Formalization

Every task (skill) is benchmarked using three components:

| Component | What | Storage | Identity |
|-----------|------|---------|----------|
| **Dataset** | Input/expected pairs | MLflow Registered Model + MinIO JSONL | `eval:{DOMAIN}.{SKILL}` |
| **Method** | Agent + skill + config | Composed from registry data at runtime | `{agent}.{skill}` |
| **Metric** | Judge agent + scoring prompt | Agent registry entry + skill prompt | `{judge}.{scoring_skill}` |

Dataset JSONL schema:
```json
{
  "id": "cr-sec-001",
  "input": {"code": "eval(input())", "language": "python"},
  "expected": {"verdict": "fail", "issues": [{"severity": "critical"}]},
  "tags": ["security"],
  "difficulty": "easy"
}
```

### FR-004: MLflow Experiment Run Schema

Each benchmark execution logged as an MLflow experiment run:
- **Params**: `task`, `dataset`, `dataset_version`, `method.agent`, `method.model`, `method.prompt_version`, `metric.judge`, `metric.model`, `metric.scoring_skill`
- **Metrics**: `accuracy`, `avg_score`, `case_count`, `timeout_count`
- **Artifacts**: full per-case results as JSONL

### FR-005: Seed Datasets

Migrate existing benchmark JSONL files from `data/benchmarks/` to the formal dataset schema:
- `eval:coder.review` — from `coder.review.jsonl`
- `eval:coder.debug` — from `coder.debug.jsonl`
- `eval:writer.email` — from `writer.email.jsonl`
- `eval:writer.rewrite` — from `writer.rewrite.jsonl`
- `eval:reasoner.solve` — from `reasoner.solve.jsonl`
- `eval:mlops.evaluate` — from `mlops.evaluate.jsonl`

### FR-006: Meta-Agent LLM Flexibility

Meta-agents (especially evaluator) can use cloud models via LiteLLM:
- `agent.provider: "litellm"` with `agent.model: "anthropic/claude-sonnet-4-20250514"`
- Allows a stronger model to judge a weaker model's output
- No code changes needed — LiteLLM routing handles provider switching

## Non-Goals

- Automated pipeline chaining (specifier → curator → evaluator) — future spec
- Dynamic MCP server registration at runtime
- UI for registry management

## Files Changed

| File | Action |
|------|--------|
| `data/seed-prompts.json` | EDIT — add evaluator, curator, specifier agents + 4 new skill prompts |
| `scripts/eval-triad.py` | EDIT — use registry API for agent/skill discovery, log triad params |
| `scripts/agent-benchmark.py` | EDIT — add meta-agent test cases |
| `tests/test_workflow_json.py` | EDIT — assertions for new agents and skills |

## Verification

| Check | FR | Expected |
|-------|-----|----------|
| `POST /webhook/agents {"action":"list"}` | FR-001 | Returns 10 agents (7 original + evaluator, curator, specifier) |
| `POST /webhook/agents {"action":"get","name":"evaluator"}` | FR-001 | Returns evaluator with mlops.evaluate skill and mlflow MCP |
| `POST /webhook/skills {"action":"list"}` | FR-002 | Returns 10 skills (6 original + 4 new meta-agent skills) |
| `grep -c 'use_case.*skill' data/seed-prompts.json` | FR-002 | 10 |
| Eval triad run with dataset + method + metric | FR-003, FR-004 | MLflow experiment logged with all triad params |
| `ls data/benchmarks/*.jsonl \| wc -l` | FR-005 | 6 dataset files |
| `POST /webhook/chat {"agent_name":"evaluator","message":"..."}` | FR-001 | Evaluator responds using configured model |
| Evaluator with `agent.provider: "litellm"` | FR-006 | Routes to cloud API via LiteLLM |
| `uv run pytest tests/test_workflow_json.py` | All | All pass |
| `bash scripts/smoke-test.sh` | All | All pass |

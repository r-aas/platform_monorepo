<!-- status: shipped -->
<!-- pr: #1 -->
# 004: Agent Task Prompts

## Problem

The Prompt Resolver in chat.json already supports task-specific prompts — it searches MLflow for `{agentName}.%` patterns, classifies incoming messages, and loads matching task prompts to augment the SYSTEM prompt. But no task prompts exist yet, so the entire task routing pipeline is dead code.

The agent benchmark only tests general agent capability. It doesn't verify task routing, task-specific behavior, or the task classification pipeline.

## Requirements

### FR-001: Create task prompts for coder agent
Add 2 task prompts with `task.description` tags:
- `coder.review` — structured code review with severity levels
- `coder.debug` — root cause analysis with fix suggestions

### FR-002: Create task prompts for writer agent
Add 2 task prompts:
- `writer.email` — professional email with structure constraints
- `writer.rewrite` — text rewriting with tone/style control

### FR-003: Create task prompts for reasoner agent
Add 1 task prompt:
- `reasoner.solve` — step-by-step problem solving with proof structure

### FR-004: Create task prompt for mlops agent
Add 1 task prompt:
- `mlops.evaluate` — evaluate a prompt using the eval pipeline

### FR-005: Add task-specific benchmark cases
Add test cases to `scripts/agent-benchmark.py` that pass explicit `task` parameter to `/webhook/chat`, verifying the task routing pipeline end-to-end.

**Acceptance**: `uv run pytest tests/test_workflow_json.py` passes. Seed prompts JSON is valid. Total seed prompts: 20 (14 existing + 6 new task prompts). Agent benchmark has task-routed test cases.

## Files Changed

| File | Action |
|------|--------|
| `data/seed-prompts.json` | EDIT — add 6 task prompts |
| `scripts/agent-benchmark.py` | EDIT — add task-routed test cases |
| `specs/004-agent-task-prompts/spec.md` | CREATE |

## Verification

| Check | Expected |
|-------|----------|
| `python3 -c "import json; json.load(open('data/seed-prompts.json'))"` | Valid JSON |
| `python3 -c "import json; d=json.load(open('data/seed-prompts.json')); print(len(d))"` | 20 |
| `uv run pytest tests/test_workflow_json.py` | All pass |
| `grep -c 'task.description' data/seed-prompts.json` | 6 |

<!-- status: shipped -->

# 021: Agent Eval Pipeline

## Overview
Native agent benchmarking via `/webhook/agent-eval` — runs test cases against agents through the full stack (agent-gateway → n8n → LiteLLM → Ollama), validates responses, and scores with LLM-as-judge. Supports agent mode, prompt mode (direct LiteLLM), and lite mode (skip agent-gateway for speed).

## User Stories
- As an ML engineer, I run benchmarks against my agent to measure quality before deploying prompt changes
- As an ML engineer, I compare model performance (qwen2.5:7b vs 14b vs mistral:7b) on the same test suite
- As an ML engineer, I define automated validators (keyword presence, length bounds, JSON structure) for deterministic pass/fail
- As an ML engineer, I use LLM-as-judge scoring (relevance, helpfulness) for nuanced quality assessment
- As a platform engineer, I run the full benchmark suite to verify the stack works end-to-end after changes

## Functional Requirements

### FR-001: Agent Evaluation Endpoint
POST `/webhook/agent-eval` SHALL accept:
- `agent` (string) — agent name (e.g., "mlops")
- `task` (string, optional) — task name (e.g., "evaluate")
- `test_cases` (array) — test cases with variables, label, validators, judges
- `model` (string, optional) — model override (default: qwen2.5:14b)
- `lite` (boolean, optional) — skip agent-gateway, call LiteLLM directly
- `judges` (array, optional) — LLM-as-judge criteria

### FR-002: Validators
The system SHALL support these deterministic validators:
- `expect_contains` — response must include specified keyword (case-insensitive)
- `expect_min_length` — response must be at least N characters
- `expect_max_words` — response must not exceed N words
- `expect_json_keys` — response must contain valid JSON with specified keys
- `expect_max_sentences` — response must not exceed N sentences

### FR-003: LLM-as-Judge
The system SHALL support judge criteria:
- Built-in: relevance, coherence, helpfulness, accuracy, conciseness, safety
- Custom: `{"metric": "custom_name", "criteria": "free-text evaluation criteria"}`
- Judge model defaults to same model as test, overridable via `judge_model`
- Scores returned as 0.0-1.0 float with reason text

### FR-004: Test Case Format
Each test case SHALL include:
- `label` — unique identifier (e.g., "evaluate-model-accuracy")
- `variables` — key-value pairs merged into user message
- `validators` — array of validator objects
- `judges` — array of judge criteria (optional)

### FR-005: Response Format
The endpoint SHALL return:
- `results[]` — per-case: label, pass, response, latency_ms, validator_results[], scores{}
- `summary` — total, passed, failed, avg_latency_ms, avg_scores{}

### FR-006: Execution Modes
- Agent mode: Calls agent-gateway → n8n chat-v1 → LiteLLM → Ollama (full e2e)
- Prompt mode: Fetches prompt from MLflow, renders template, calls LiteLLM directly
- Lite mode (`lite: true`): Constructs message from variables, calls LiteLLM directly (fastest, ~10x)

## Agents and Tasks

| Agent | System Prompt | Tasks |
|-------|--------------|-------|
| mlops | MLOps engineer — model lifecycle, tracking, monitoring | evaluate, debug, explain |
| developer | Software engineer — code gen, review, docs | review, generate, document |
| platform-admin | Platform ops — k8s, capacity, runbooks | diagnose, plan, runbook |

Prompt naming: `{agent}.SYSTEM` + `{agent}.{TASK}` in MLflow prompt registry.

## Benchmark Results (Baseline)

| Model | Pass Rate | Avg Relevance | Avg Helpfulness | Avg Time/Case |
|-------|-----------|---------------|-----------------|---------------|
| qwen2.5:7b | 39/45 (87%) | 0.85 | 0.72 | ~33s |
| qwen2.5:14b | 38/45 (84%) | 0.88 | 0.77 | ~55s |
| mistral:7b | 33/45 (73%) | — | — | ~21s |

## Acceptance Criteria
- SC-001: `/webhook/agent-eval` returns results with all validator fields populated
- SC-002: All 5 validator types work correctly (tested across 45 cases)
- SC-003: LLM-as-judge returns 0.0-1.0 scores with reason text
- SC-004: Lite mode runs at least 5x faster than agent mode
- SC-005: 87%+ pass rate on qwen2.5:7b across all 45 test cases
- SC-006: Results are deterministic (same test case + model → same validators pass/fail)

## Key Decisions
- One test case per HTTP call to avoid n8n task runner timeouts
- 5-second delay between calls prevents Ollama memory thrashing
- LiteLLM MLflow success_callback disabled (saves 16s per call)
- n8n memory bumped to 2Gi (task runner OOMs at 1Gi under benchmark load)
- Ingress proxy-read-timeout: 300s for eval calls
- Validators run on the response text, not parsed JSON

## Files
- Workflow: `genai-mlops/n8n-data/workflows/agent-eval.json` (if exists) or inline in chat.json
- Test cases: `genai-mlops/data/benchmarks/{agent}.{task}.json` (9 files, 45 cases)
- Seed prompts: `genai-mlops/data/seed-prompts.json` (42 entries)
- Agent YAMLs: `platform_monorepo/agents/{agent}.yaml` (5 agents)

## Dependencies
- n8n with agent-eval workflow active
- LiteLLM with models registered (qwen2.5:14b, qwen2.5:7b, mistral:7b-instruct)
- MLflow with prompts seeded
- Agent gateway deployed (for non-lite mode)

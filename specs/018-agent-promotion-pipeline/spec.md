<!-- status: shipped -->
<!-- pr: #10 -->
# Spec 018: Agent Promotion Pipeline

## Problem

The platform has all the pieces for agent quality assurance but no orchestration layer connecting them. Evaluation datasets exist (`data/benchmarks/*.jsonl`, 13 files), an LLM-as-judge eval engine exists (`/webhook/eval` with `run_dataset`), canary routing exists (`openai-compat.json`), drift detection exists (`trace.json` + `drift_monitor.py`), and prompt version management exists (`/webhook/prompts` with `promote`/`set_canary`). But these are disconnected manual operations. There is no automated pipeline that:

1. Takes a staging prompt version
2. Benchmarks it against the agent's dataset
3. Compares results to the production baseline
4. Makes a promote/rollback decision
5. Records the decision with evidence

The result: prompt updates go to production via manual `promote` calls with no quality gate. The `agent-benchmark.py` script has 16 hardcoded test cases instead of using the 78+ JSONL benchmark cases. The `ab_eval` action compares production vs staging but doesn't persist results or trigger promotion. Good traces auto-promote into benchmark datasets via the `feedback` action, but those datasets are never consumed by any pipeline.

The goal is AgenticOps-as-AutoDevOps: every prompt change goes through automated benchmarking before reaching production, with the same rigor that CI/CD brings to code deployment.

## Current State

### What works (disconnected)

| Component | Location | Status |
|-----------|----------|--------|
| Benchmark datasets | `data/benchmarks/*.jsonl` (13 files, 78+ cases) | Written by feedback loop, never read |
| Eval engine | `/webhook/eval` (`run_dataset`, `ab_eval`) | Shipped (spec 006) |
| Canary tags | `/webhook/prompts` (`set_canary`, `get_canary`, `clear_canary`) | Shipped |
| Canary routing | `/webhook/v1/chat/completions` (sticky hash routing) | Shipped |
| Prompt promotion | `/webhook/prompts` (`promote`) | Shipped, manual only |
| Drift detection | `/webhook/traces` (`drift_check`, `baseline_set`) | Shipped, script-driven |
| Feedback-to-benchmark | `/webhook/traces` (`promote` action) | Shipped, writes JSONL |
| Agent benchmark script | `scripts/agent-benchmark.py` | Hardcoded cases, ignores JSONL |
| Agent catalog | `/webhook/agents` (`list`, `get`) | Shipped (spec 017) |

### What's missing

1. **Dataset-driven benchmarking** --- `agent-benchmark.py` should consume `data/benchmarks/*.jsonl` instead of hardcoded cases
2. **Promotion gate** --- automated decision: benchmark score >= threshold -> promote, else rollback
3. **Pipeline orchestration** --- staging -> benchmark -> compare -> gate -> promote/rollback as a single invocation
4. **Baseline tracking** --- per-agent benchmark baselines stored in MLflow for regression detection
5. **Evidence trail** --- every promotion/rejection logged with scores, comparison, and rationale

## Requirements

### FR-001: Dataset-driven agent benchmark

Rewrite `scripts/agent-benchmark.py` to load test cases from `data/benchmarks/*.jsonl` instead of hardcoded inline cases.

Behavior:
- Discover benchmark files matching `data/benchmarks/{agent}.*.jsonl` pattern
- Each JSONL row has: `input`, `expected`, `criteria`, `domain`, `task`, `tags`
- For each case: POST to `/webhook/chat`, run LLM-as-judge via `/webhook/eval`, validate response
- Create one MLflow experiment run per benchmark invocation: `{agent}-benchmark`
- Log per-case results + aggregate summary (pass rate, avg score, p50/p95 latency, total tokens)
- Support filtering: `--agent coder`, `--task review`, `--tags promoted`
- Exit code: 0 if pass rate >= threshold (default 0.7), 1 otherwise

The script retains its current two-layer scoring (deterministic validator + LLM-as-judge) but sources cases from JSONL.

### FR-002: Promotion pipeline webhook

New action on `/webhook/prompts`:

```
POST /webhook/prompts
{
  "action": "pipeline",
  "name": "coder.SYSTEM",
  "staging_version": 4,
  "threshold": 0.8,
  "canary_pct": 20,
  "auto_promote": true
}
```

Pipeline stages (executed sequentially in a single request):

1. **Validate** --- staging version exists, agent has benchmark dataset
2. **Benchmark staging** --- run `ab_eval` with production vs staging using the agent's benchmark dataset
3. **Compare** --- compute score delta between production and staging
4. **Gate** --- if staging avg score >= threshold AND staging score >= production score: pass. Else: fail.
5. **Act** ---
   - Pass + `auto_promote: true`: promote staging to production, clear canary, update baseline
   - Pass + `auto_promote: false`: set canary at `canary_pct`, return recommendation
   - Fail: clear canary if active, return rejection with evidence
6. **Record** --- create MLflow run in `{agent}-promotions` experiment with all metrics, decision, and rationale

Response:
```json
{
  "pipeline": "promote",
  "name": "coder.SYSTEM",
  "staging_version": 4,
  "decision": "promoted" | "canary" | "rejected",
  "production_score": 0.82,
  "staging_score": 0.91,
  "delta": 0.09,
  "threshold": 0.8,
  "pass_rate": 0.92,
  "cases_evaluated": 15,
  "experiment_run_id": "abc123",
  "evidence": {
    "per_metric": {"relevance": {"prod": 0.80, "staging": 0.90}, ...},
    "failures": [{"input": "...", "reason": "..."}]
  }
}
```

### FR-003: Baseline management

Extend the existing `baseline_set`/`baseline_get` in `trace.json` to support benchmark baselines (not just trace-derived baselines):

New action on `/webhook/traces`:
```
POST /webhook/traces
{
  "action": "baseline_set_benchmark",
  "prompt_name": "coder.SYSTEM",
  "version": 3,
  "scores": {"relevance": 0.85, "accuracy": 0.82, "overall": 0.84},
  "pass_rate": 0.92,
  "cases_evaluated": 15,
  "latency_p50_ms": 2300,
  "latency_p95_ms": 8100
}
```

Stored in `__baselines` experiment with tag `baseline_type: benchmark` (vs existing `baseline_type: trace`).

The promotion pipeline (FR-002) auto-updates the benchmark baseline after a successful promotion.

### FR-004: Agent-level promotion status

Extend the agent catalog (spec 017, `/webhook/agents`) to include promotion status:

```json
{
  "name": "coder",
  "promotion": {
    "production_version": 3,
    "staging_version": 4,
    "canary_enabled": false,
    "canary_pct": 0,
    "last_benchmark": {
      "score": 0.84,
      "pass_rate": 0.92,
      "run_id": "abc123",
      "timestamp": "2026-03-16T10:30:00Z"
    },
    "last_promotion": {
      "from_version": 2,
      "to_version": 3,
      "decision": "promoted",
      "timestamp": "2026-03-15T14:00:00Z"
    }
  }
}
```

Data sourced from: MLflow model aliases (production/staging), canary tags, and `{agent}-promotions` experiment.

### FR-005: Promote command in agent-benchmark.py

Add `--promote` flag to the benchmark script for a complete CLI-driven pipeline:

```bash
# Benchmark only (default)
uv run scripts/agent-benchmark.py --agent coder

# Benchmark + promote if passing
uv run scripts/agent-benchmark.py --agent coder --promote --threshold 0.8

# Benchmark staging version specifically
uv run scripts/agent-benchmark.py --agent coder --version staging --promote
```

When `--promote` is set:
1. Run benchmark against specified version (default: staging alias)
2. If pass rate >= threshold: call `/webhook/prompts {action: "pipeline", ...}`
3. Report result

This gives a single CLI entry point for the full promote-or-reject cycle.

### FR-006: Observatory integration

Extend the Observatory dashboard (spec 014/017) to show promotion pipeline status:

- Per-agent card: last benchmark score, production version, staging version, canary status
- Promotion history: recent promote/reject decisions with scores
- Data source: agent catalog enriched response (FR-004)

### FR-007: Smoke tests

Add smoke tests:
- Pipeline endpoint: `POST /webhook/prompts {action: "pipeline", name: "coder.SYSTEM", staging_version: 1, threshold: 0.0}` returns valid response
- Baseline management: `POST /webhook/traces {action: "baseline_set_benchmark", ...}` stores and retrieves
- Agent catalog promotion status: `POST /webhook/agents {action: "get", name: "coder"}` includes `promotion` field

## Architecture

```
                          Promotion Pipeline
                          ==================

Developer updates prompt
         │
         v
  ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
  │ MLflow       │────>│ /prompts     │────>│ Set staging   │
  │ new version  │     │ pipeline     │     │ alias         │
  └─────────────┘     └──────┬───────┘     └──────────────┘
                             │
                    ┌────────v────────┐
                    │  Load benchmark │
                    │  dataset JSONL  │
                    └────────┬────────┘
                             │
                    ┌────────v────────┐
                    │  ab_eval:       │
                    │  prod vs staging│
                    │  (LLM-as-judge) │
                    └────────┬────────┘
                             │
                    ┌────────v────────┐
                    │  Gate:          │
                    │  score >= 0.8?  │
                    │  score >= prod? │
                    └───┬─────────┬───┘
                        │         │
                   PASS │         │ FAIL
                        v         v
               ┌──────────┐  ┌──────────┐
               │ Promote   │  │ Reject   │
               │ to prod   │  │ keep prod│
               │ Update    │  │ Clear    │
               │ baseline  │  │ canary   │
               └──────────┘  └──────────┘
                        │         │
                        v         v
               ┌──────────────────────┐
               │ Log decision to      │
               │ {agent}-promotions   │
               │ MLflow experiment    │
               └──────────────────────┘


Feedback Loop (existing, spec 008)
==================================

Good trace (rating >= 4)
         │
         v
  ┌─────────────┐     ┌──────────────┐
  │ /traces     │────>│ Write JSONL   │
  │ feedback    │     │ to benchmarks │
  └─────────────┘     └──────────────┘

Benchmark datasets grow organically from production usage.
Next pipeline run includes the new cases.
```

## Files Changed

| File | What |
|------|------|
| `scripts/agent-benchmark.py` | FR-001: rewrite to use JSONL datasets, FR-005: add --promote flag |
| `n8n-data/workflows/prompt-crud.json` | FR-002: add `pipeline` action |
| `n8n-data/workflows/trace.json` | FR-003: add `baseline_set_benchmark` action |
| `n8n-data/workflows/agents.json` | FR-004: include promotion status in catalog |
| `scripts/dashboard.py` | FR-006: promotion status in agent cards |
| `scripts/dashboard-static/panels.js` | FR-006: render promotion data |
| `scripts/smoke-test.sh` | FR-007: new test cases |
| `specs/018-agent-promotion-pipeline/spec.md` | This spec |

## Dependencies

- Spec 004 (agent-task-prompts) --- shipped, `{agent}.{task}` naming
- Spec 006 (dataset-eval) --- shipped, `run_dataset` and `ab_eval` actions
- Spec 007 (agent-tool-routing) --- shipped, per-agent `mcp_tools`
- Spec 008 (real-streaming) --- shipped, canary routing in openai-compat
- Spec 017 (agent-executor) --- in-progress, agent catalog API + skills

## Verification

| Check | Expected |
|-------|----------|
| `uv run scripts/agent-benchmark.py --agent coder` | Loads `coder.*.jsonl`, runs all cases, logs to MLflow |
| `uv run scripts/agent-benchmark.py --agent coder --promote --threshold 0.0` | Benchmarks + promotes staging to production |
| `POST /webhook/prompts {action:"pipeline", name:"coder.SYSTEM", staging_version:1, threshold:0.0}` | Returns decision with scores and evidence |
| `POST /webhook/agents {action:"get", name:"coder"}` | Response includes `promotion` field with versions and last benchmark |
| `POST /webhook/traces {action:"baseline_set_benchmark", ...}` | Stores benchmark baseline, retrievable via `baseline_get` |
| Pipeline with failing score | Returns `decision: "rejected"` with evidence, does NOT promote |
| Pipeline after successful promote | Baseline updated, canary cleared, alias set |
| Observatory dashboard | Agent cards show benchmark score, versions, canary status |
| Smoke tests | All pass including new promotion pipeline tests |
| Existing eval tests | No regressions |

## Non-requirements

- **Multi-model comparison** --- comparing the same prompt across different LLM models is deferred
- **Automated rollback on drift** --- drift detection alerts but does not auto-rollback (too risky without human oversight)
- **Scheduled pipeline runs** --- pipelines are triggered explicitly, not on a cron (can be added later via n8n scheduling)
- **Cross-agent benchmarking** --- no composite score across all agents; each agent is evaluated independently
- **Dataset versioning** --- JSONL files are append-only via the feedback loop; formal dataset versioning (snapshots, splits) is deferred

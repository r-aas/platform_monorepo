# Plan: Spec 018 — Agent Promotion Pipeline

## Overview

Connect existing disconnected pieces (benchmark datasets, ab_eval, canary routing, drift detection, prompt promotion) into an automated staging-to-production pipeline. 6 phases, 8 files changed.

## Phase 1: Rewrite agent-benchmark.py (FR-001 + FR-005)

**File:** `scripts/agent-benchmark.py`

Replace hardcoded SUITES with JSONL dataset loading. Keep the existing `validate()`, `chat()`, `judge_response()`, `write_langfuse_score()` functions unchanged.

Changes:
1. Add `argparse` for `--agent`, `--task`, `--tags`, `--threshold`, `--promote`, `--version`
2. Add `load_benchmarks()` — glob `data/benchmarks/{agent}.*.jsonl`, parse each line
3. Map JSONL fields to existing test case format: `input` → `message`, `criteria` → `judge_criteria`, `expected` → `expect_contains` (if short, < 20 chars)
4. Replace `SUITES` constant with dynamic loading from JSONL
5. Add MLflow experiment logging: create run in `{agent}-benchmark` experiment per invocation, log aggregate metrics
6. Add `--promote` mode: after benchmark, POST to `/webhook/prompts {action: "pipeline", ...}` if pass rate >= threshold
7. Keep backward compat: if no JSONL files found for an agent, warn and skip (not error)

**Key design decision:** The script stays as a Python script calling webhooks (not an n8n workflow). This keeps it CLI-friendly and testable outside n8n.

## Phase 2: Pipeline action in prompt-crud.json (FR-002)

**File:** `n8n-data/workflows/prompt-crud.json`

Add `pipeline` action to the CRUD Handler Code node. This is the orchestration core.

New action block (insert before the final `throw new Error('Unknown action')` line):

```javascript
if (action === 'pipeline') {
  // 1. Validate inputs
  var name = body.name;           // e.g. "coder.SYSTEM"
  var stagingVer = body.staging_version;
  var threshold = body.threshold || 0.8;
  var canaryPct = body.canary_pct || 20;
  var autoPromote = body.auto_promote !== false;

  // 2. Verify staging version exists
  await apiGet('/model-versions/get?name=' + encodeURIComponent(name) + '&version=' + stagingVer);

  // 3. Set staging alias
  await post('/registered-models/alias', {name: name, alias: 'staging', version: String(stagingVer)});

  // 4. Load benchmark dataset from JSONL files via HTTP
  //    (Read data/benchmarks/{agent}.*.jsonl — agent = name without .SYSTEM)
  //    Use N8N internal self-call to /webhook/eval with ab_eval

  // 5. Build test_cases from JSONL rows for ab_eval
  // 6. Call /webhook/eval {action: "ab_eval", prompt_name: name, test_cases: [...], judges: ["relevance", "accuracy"]}
  // 7. Compute aggregate scores, compare prod vs staging
  // 8. Gate decision: staging avg >= threshold AND staging >= production
  // 9. Act: promote/canary/reject
  // 10. Log to {agent}-promotions MLflow experiment
}
```

**Implementation approach:** The pipeline action calls `/webhook/eval` internally (via axios to n8n self) with the `ab_eval` action. This reuses the existing eval infrastructure rather than reimplementing LLM-as-judge.

**Challenge:** The pipeline action needs to read JSONL files from disk. n8n Code nodes can't read the filesystem directly. Two options:
- **Option A:** Use the datasets webhook (`/webhook/datasets {action: "list"}`) to get benchmark datasets from MLflow artifacts
- **Option B:** Have the benchmark script upload JSONL rows to MLflow datasets first, then pipeline reads from there

**Decision: Option A.** The `promote` action in trace.json already uploads cases to `/webhook/datasets`. We'll use the existing dataset infrastructure. The pipeline will:
1. Search MLflow for datasets matching the agent domain (e.g., `coder.*`)
2. Download rows from the dataset artifacts
3. Build test_cases for ab_eval from the rows

If no MLflow dataset exists, fall back: the pipeline requires at least one dataset to exist (seeded via `data/benchmarks/*.jsonl` upload or accumulated from the feedback loop).

## Phase 3: Benchmark baseline in trace.json (FR-003)

**File:** `n8n-data/workflows/trace.json`

Add `baseline_set_benchmark` action to the Trace Handler. Extends the existing `baseline_set`/`baseline_get` pattern with additional fields.

```javascript
if (action === 'baseline_set_benchmark') {
  // Same as baseline_set but:
  // - Additional metrics: pass_rate, cases_evaluated, latency_p50_ms, latency_p95_ms
  // - Tag: baseline_type = "benchmark" (vs "trace")
  // - Tag: prompt_version = body.version
  // - Scores object logged as individual metrics (relevance, accuracy, etc.)
}
```

The existing `baseline_get` already works for retrieval — the additional metrics are just more fields on the same MLflow run.

## Phase 4: Promotion status in agent catalog (FR-004)

**File:** `n8n-data/workflows/agents.json`

Extend the `getAgentInfo()` function in the Action Router to include promotion data:

1. Read canary tags from MLflow model: `canary.enabled`, `canary.staging_version`, `canary.traffic_pct`
2. Read production/staging aliases
3. Query `{agent}-promotions` experiment for latest run (most recent promotion decision)
4. Query `__baselines` experiment for latest benchmark baseline
5. Assemble `promotion` object in the agent response

This adds ~30 lines to `getAgentInfo()`. The data is already in MLflow — just need to read it.

## Phase 5: Dashboard updates (FR-006)

**Files:** `scripts/dashboard.py`, `scripts/dashboard-static/panels.js`, `scripts/dashboard-static/styles.css`

Extend agent cards to show:
- Production version badge
- Staging version badge (if canary active)
- Last benchmark score
- Last promotion decision (promoted/rejected + timestamp)

Data flows from the enriched agent catalog (Phase 4) through the existing dashboard polling.

## Phase 6: Smoke tests (FR-007)

**File:** `scripts/smoke-test.sh`

Add tests:
```bash
# Pipeline endpoint (use threshold 0.0 so it always passes)
check_status "pipeline" "${BASE}/prompts" POST '{"action":"pipeline","name":"coder.SYSTEM","staging_version":"1","threshold":0.0,"auto_promote":false}' 200

# Baseline management
check_status "baseline benchmark" "${BASE}/traces" POST '{"action":"baseline_set_benchmark","prompt_name":"coder.SYSTEM","version":"1","scores":{"relevance":0.85},"pass_rate":0.9,"cases_evaluated":10}' 200

# Agent catalog with promotion data
check_json "agents promotion" "${BASE}/agents" '{"action":"get","name":"coder"}' '.agent.promotion'
```

## Task Order

| # | Task | Files | Depends |
|---|------|-------|---------|
| 1 | Rewrite agent-benchmark.py with JSONL loading + argparse | agent-benchmark.py | — |
| 2 | Add `pipeline` action to prompt-crud.json | prompt-crud.json | — |
| 3 | Add `baseline_set_benchmark` to trace.json | trace.json | — |
| 4 | Extend agents.json with promotion status | agents.json | — |
| 5 | Add `--promote` flag to agent-benchmark.py | agent-benchmark.py | 1, 2 |
| 6 | Update dashboard with promotion data | dashboard.py, panels.js, styles.css | 4 |
| 7 | Add smoke tests | smoke-test.sh | 2, 3, 4 |
| 8 | Commit, import, test live | — | all |

Tasks 1-4 are independent and can be done in parallel. Task 5 depends on 1+2. Task 6 depends on 4. Task 7 depends on 2+3+4. Task 8 is the integration test.

## Risk: Pipeline timeout

The `pipeline` action runs ab_eval (2x LLM calls per test case) + judges across all dataset rows. For 15 test cases with 2 judges, that's 60+ LLM calls. At ~5s each = 300s minimum. n8n webhook timeout is 300s by default.

**Mitigation:** Limit pipeline to max 10 test cases by default (body.limit || 10). Enough for a quality signal, not too slow. The full dataset can be benchmarked via the CLI script which has no timeout.

## Risk: No datasets in MLflow yet

The JSONL files exist on disk but are not in MLflow's artifact store (they're written there by the `promote` action in trace.json when traces get positive feedback). For the pipeline to work, datasets need to be in MLflow.

**Mitigation:** Phase 1 (agent-benchmark.py rewrite) will include a `--seed-datasets` flag that uploads `data/benchmarks/*.jsonl` to MLflow via `/webhook/datasets {action: "upload"}`. This bootstraps the system.

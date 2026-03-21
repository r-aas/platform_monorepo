# Platform Monorepo — Session Resume

## Session: 2026-03-21 — Factory Worker Run 14

### Built

- **D.06: Eval dataset expansion** — 5 datasets, 56 total cases, 25 new schema validation tests

  **Expanded datasets:**
  - `skills/eval/kubernetes-ops/deploy-model.json`: 3 → 12 cases (replicas, resources, image update, rollout, staging, env vars, configmap, service exposure, dry-run, HPA)
  - `skills/eval/kubernetes-ops/check-status.json`: 2 → 11 cases (logs, events, resource usage, crashloop, pending, rollout status, service endpoints, node health, PVC)
  - `skills/eval/mlflow-tracking/log-metrics.json`: 1 → 11 cases (multi-metric, step, param+metric, AUC-ROC, batch, new experiment, latency metric, R2/MAE)

  **New datasets:**
  - `skills/eval/mlflow-tracking/search-experiments.json`: 11 cases (list, search by name/tag/metric/param, paginated, active runs, best run)
  - `skills/eval/n8n-workflow-ops/list-workflows.json`: 11 cases (active, inactive, webhook triggers, by tag, sub-workflows, summary, recently updated)

  **New test file:**
  - `tests/test_eval_datasets.py`: 25 parametrized tests across all 5 datasets
    - exists + valid JSON with correct skill/task metadata
    - min 10 cases per dataset
    - all required fields (id, input, expected_output_contains)
    - unique case IDs
    - expected_output_contains is list[str]

  **Fixed:**
  - `tests/test_benchmark.py`: removed hardcoded `"3"` count assertion; replaced with presence check for `total_cases` metric key

### Test Status

247 tests passing (+25 from run 14):
- 25 new in test_eval_datasets.py (D.06 coverage)
- 1 updated test in test_benchmark.py (flexible count assertion)
- All prior 222 tests still passing

### Commits This Run

- `dae7f7e` feat(agent-gateway): eval dataset expansion — 10+ cases per task [D.06]

### Branch

`001-agent-gateway` — clean

### Phase D Status

| Item | What | Status |
|------|------|--------|
| D.01 | Embedding service LRU cache | ✅ Done |
| D.02 | Skill search with semantic similarity | ✅ Done |
| D.03 | Agent search with semantic similarity | ✅ Done |
| D.04 | MCP tool search with semantic similarity | ✅ Done |
| D.05 | Benchmark runner end-to-end | ✅ Done |
| D.06 | Eval dataset expansion — 10+ cases per skill task | ✅ Done |
| D.07 | Auto-prompt optimization | ⏳ Next |

### Next Steps

- [local] Phase D: D.07 — Auto-prompt optimization
  - Run evals via benchmark runner on each skill's eval dataset
  - Measure pass_rate baseline per skill task
  - Identify lowest-performing task (lowest pass_rate)
  - Tweak prompt_fragment for that skill (add specificity or examples)
  - Re-run eval to verify improvement
  - Record in MLflow as a prompt optimization experiment

### Notes

- Parametrized test pattern for datasets: `@pytest.mark.parametrize("skill,task,min_cases", EXPECTED_DATASETS)` — O(N×M) coverage with O(1) code
- Hardcoded case counts in tests break when data grows — use `>= N` not `== N`
- Eval case design: mix single-tool (isolated skill test) with multi-tool (realistic workflow) cases

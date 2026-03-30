<!-- status: shipped -->
<!-- pr: #2 -->
# 006: Dataset-Driven Evaluation

## Problem

The eval pipeline (`POST /webhook/eval`) accepts inline `test_cases[]` but has no way to run an entire dataset. The dataset workflow (`POST /webhook/datasets`) stores only a 5-row preview tag and row count metadata — full row data is lost after upload. These two systems are disconnected.

The desired workflow:
1. Upload a dataset (rows with input variables + optional expected outputs)
2. Run eval against all rows in that dataset for a given prompt
3. Get aggregated scores, linked to the dataset for traceability

## Requirements

### FR-001: Persist full dataset rows

The `upload` action on `/webhook/datasets` MUST store all rows as an MLflow artifact (JSONL file), not just a 5-row preview tag.

- Store rows as artifact: `{run_id}/artifacts/rows.jsonl` (one JSON object per line)
- Keep existing preview tag for quick listing (first 5 rows, 5000 char cap)
- Keep existing params (dataset_name, format, row_count, schema)
- Artifact storage uses MLflow's artifact logging API

### FR-002: Retrieve full dataset rows

The `get` action on `/webhook/datasets` MUST return all rows when requested.

- Default: return metadata + preview (backward compatible)
- With `include_rows: true`: return metadata + full `rows[]` array
- Rows retrieved by downloading the `rows.jsonl` artifact from MLflow
- If artifact missing (legacy dataset), return preview only with `rows_available: false`

### FR-003: Run eval from dataset

Add `run_dataset` action to `/webhook/eval` endpoint.

Request:
```json
{
  "action": "run_dataset",
  "dataset_id": "<mlflow run_id of dataset>",
  "prompt_name": "assistant",
  "alias": "production",
  "temperature": 0,
  "judges": ["relevance"],
  "model": "qwen2.5:14b",
  "variable_mapping": {
    "message": "input"
  },
  "label_field": "label",
  "limit": 50
}
```

Behavior:
- Fetch dataset rows from artifact
- Map each row to a test case using `variable_mapping` (dataset column → prompt variable)
- If no `variable_mapping`, assume column names match prompt variable names
- Use `label_field` to set test case label (default: row index)
- `limit` caps rows evaluated (default: all rows, max: 200)
- Execute eval for all mapped test cases (reuse existing eval logic)
- Link dataset to eval experiment via MLflow `log-inputs`
- Return results array + summary (same format as regular eval)

### FR-004: Dataset eval summary

The `run_dataset` response includes aggregate metrics.

```json
{
  "action": "run_dataset",
  "dataset_id": "abc123",
  "dataset_name": "qa-test-set",
  "prompt_name": "assistant",
  "total_rows": 25,
  "evaluated": 25,
  "results": [...],
  "summary": {
    "avg_latency_ms": 1200,
    "avg_tokens": 150,
    "avg_scores": {
      "relevance": 0.91
    },
    "pass_rate": 0.92,
    "failures": 2
  }
}
```

### FR-005: Smoke test coverage

Add to `scripts/smoke-test.sh`:
- Upload dataset with 3+ rows → verify artifact stored
- Get dataset with `include_rows: true` → verify all rows returned
- Run dataset eval → verify results for all rows + summary

### FR-006: Integration test coverage

Add to `tests/test_integration.py`:
- `TestDatasets.test_upload_with_rows_artifact` — upload, get with include_rows, verify row count matches
- `TestDatasets.test_get_legacy_dataset` — get without artifact returns `rows_available: false`
- `TestEvaluation.test_run_dataset` — upload dataset, run_dataset eval, verify results count + summary

## Files Changed

| File | Action |
|------|--------|
| `specs/006-dataset-eval/spec.md` | CREATE |
| `n8n-data/workflows/mlflow-data.json` | EDIT — artifact storage + row retrieval |
| `n8n-data/workflows/prompt-eval.json` | EDIT — add run_dataset action |
| `scripts/smoke-test.sh` | EDIT — add dataset eval test cases |
| `tests/test_integration.py` | EDIT — add dataset eval tests |

## Verification

| Check | Expected |
|-------|----------|
| Upload 10-row dataset | `row_count: 10`, artifact exists |
| Get with `include_rows: true` | All 10 rows returned |
| Get without flag | Preview only (backward compat) |
| `run_dataset` with 10 rows | 10 results, summary with avg scores |
| `run_dataset` with limit=3 | 3 results only |
| `run_dataset` with variable_mapping | Correct column→variable mapping |
| `task qa:smoke` | All pass including new cases |
| `uv run pytest tests/test_integration.py -v` | All pass including new cases |

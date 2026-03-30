# Contract: POST /webhook/eval — run_dataset action

## Endpoint

`POST /webhook/eval`

## Request

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
    "<dataset_column>": "<prompt_variable>"
  },
  "label_field": "label",
  "limit": 50
}
```

### Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `action` | string | yes | — | Must be `"run_dataset"` |
| `dataset_id` | string | yes | — | MLflow run ID of the uploaded dataset |
| `prompt_name` | string | yes | — | Prompt to evaluate |
| `alias` | string | no | `"production"` | Prompt version alias |
| `temperature` | number | no | `0` | LLM temperature |
| `judges` | string[] | no | `["relevance"]` | Judge criteria to score against |
| `model` | string | no | env default | Model to use for generation |
| `variable_mapping` | object | no | identity | Maps dataset column names → prompt variable names |
| `label_field` | string | no | row index | Dataset column to use as test case label |
| `limit` | number | no | all rows (max 200) | Cap on rows evaluated |

## Response (200)

```json
{
  "action": "run_dataset",
  "dataset_id": "abc123",
  "dataset_name": "qa-test-set",
  "prompt_name": "assistant",
  "total_rows": 25,
  "evaluated": 25,
  "results": [
    {
      "label": "row-0",
      "response": "...",
      "scores": { "relevance": 0.95 },
      "latency_ms": 1100,
      "tokens": 142
    }
  ],
  "summary": {
    "avg_latency_ms": 1200,
    "avg_tokens": 150,
    "avg_scores": { "relevance": 0.91 },
    "pass_rate": 0.92,
    "failures": 2
  }
}
```

## Error Responses

| Status | Condition | Body |
|--------|-----------|------|
| 400 | Missing `dataset_id` or `prompt_name` | `{ "error": "dataset_id and prompt_name required" }` |
| 404 | Dataset not found in MLflow | `{ "error": "dataset not found" }` |
| 404 | Prompt not found | `{ "error": "prompt not found" }` |

## Side Effects

- Creates MLflow experiment run per evaluation
- Logs dataset input via `mlflow.log-inputs`
- Logs per-row scores and summary metrics

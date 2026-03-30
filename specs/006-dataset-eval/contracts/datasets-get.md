# Contract: POST /webhook/datasets — get action

## Endpoint

`POST /webhook/datasets`

## Request

```json
{
  "action": "get",
  "dataset_id": "<mlflow_run_id>",
  "include_rows": true
}
```

### Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `action` | string | yes | — | Must be `"get"` |
| `dataset_id` | string | yes | — | MLflow run ID of the dataset |
| `include_rows` | boolean | no | `false` | If true, fetch full rows from artifact |

## Response (200) — without include_rows

```json
{
  "action": "get",
  "dataset_id": "abc123",
  "dataset_name": "qa-test-set",
  "row_count": 25,
  "schema": ["input", "expected"],
  "preview": [
    { "input": "What is MLflow?", "expected": "MLflow is..." }
  ]
}
```

## Response (200) — with include_rows: true

```json
{
  "action": "get",
  "dataset_id": "abc123",
  "dataset_name": "qa-test-set",
  "row_count": 25,
  "schema": ["input", "expected"],
  "preview": [...],
  "rows_available": true,
  "rows": [
    { "input": "What is MLflow?", "expected": "MLflow is..." },
    { "input": "What is n8n?", "expected": "n8n is..." }
  ]
}
```

## Response (200) — legacy dataset (no artifact)

```json
{
  "action": "get",
  "dataset_id": "abc123",
  "dataset_name": "old-dataset",
  "row_count": 10,
  "schema": ["input"],
  "preview": [...],
  "rows_available": false
}
```

## Error Responses

| Status | Condition | Body |
|--------|-----------|------|
| 400 | Missing `dataset_id` | `{ "error": "dataset_id required" }` |
| 404 | Dataset not found | `{ "error": "dataset not found" }` |

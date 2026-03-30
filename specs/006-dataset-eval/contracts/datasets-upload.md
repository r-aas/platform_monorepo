# Contract: POST /webhook/datasets — upload action

## Endpoint

`POST /webhook/datasets`

## Request

```json
{
  "action": "upload",
  "dataset_name": "qa-test-set",
  "format": "jsonl",
  "rows": [
    { "input": "What is MLflow?", "expected": "MLflow is..." },
    { "input": "What is n8n?", "expected": "n8n is..." }
  ]
}
```

### Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `action` | string | yes | — | Must be `"upload"` |
| `dataset_name` | string | yes | — | Human-readable dataset name |
| `format` | string | no | `"jsonl"` | Data format hint |
| `rows` | object[] | yes | — | Array of data rows (arbitrary schema) |

## Response (200)

```json
{
  "action": "upload",
  "dataset_name": "qa-test-set",
  "dataset_id": "<mlflow_run_id>",
  "row_count": 25,
  "schema": ["input", "expected"],
  "preview": [
    { "input": "What is MLflow?", "expected": "MLflow is..." }
  ]
}
```

## Storage

- MLflow experiment: `datasets`
- Run params: `dataset_name`, `format`, `row_count`, `schema`
- Run tag: `preview` (first 5 rows, 5000 char cap)
- Run artifact: `rows.jsonl` (all rows, one JSON object per line)

## Error Responses

| Status | Condition | Body |
|--------|-----------|------|
| 400 | Missing `dataset_name` or `rows` | `{ "error": "dataset_name and rows required" }` |
| 400 | Empty rows array | `{ "error": "rows must not be empty" }` |

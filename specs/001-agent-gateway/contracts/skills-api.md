# Contract: Skills Registry CRUD API

**Spec**: FR-013, FR-014, FR-015, FR-018

## POST /skills — Create Skill

**Request**:
```json
{
  "name": "kubernetes-ops",
  "description": "Kubernetes cluster operations and deployment management",
  "version": "1.0.0",
  "tags": ["infrastructure", "deployment"],
  "mcp_servers": [
    {
      "url": "http://genai-metamcp.genai.svc.cluster.local:12008/metamcp/genai/mcp",
      "tool_filter": ["kubectl_get", "kubectl_apply", "kubectl_logs", "kubectl_describe"]
    }
  ],
  "prompt_fragment": "When performing Kubernetes operations:\n- Always check current state before making changes\n...",
  "tasks": [
    {
      "name": "deploy-model",
      "description": "Deploy a trained model to the cluster",
      "inputs": [
        {"name": "model_name", "type": "string"},
        {"name": "namespace", "type": "string", "default": "genai"}
      ],
      "evaluation": {
        "dataset": "skills/eval/kubernetes-ops/deploy-model.json",
        "metrics": ["task_completion", "correctness"]
      }
    },
    {
      "name": "check-status",
      "description": "Check deployment status and pod health",
      "inputs": [
        {"name": "deployment_name", "type": "string"}
      ]
    }
  ]
}
```

**Response** `201 Created`:
```json
{
  "name": "kubernetes-ops",
  "version": "1.0.0",
  "created_at": "2026-03-20T12:00:00Z",
  "mlflow_model_name": "skill:kubernetes-ops",
  "mlflow_version": 1
}
```

**Response** `409 Conflict` (skill already exists):
```json
{"error": {"message": "Skill 'kubernetes-ops' already exists. Use PUT to update.", "code": "skill_exists"}}
```

## GET /skills — List Skills

**Response** `200 OK`:
```json
{
  "skills": [
    {
      "name": "kubernetes-ops",
      "description": "Kubernetes cluster operations and deployment management",
      "version": "1.0.0",
      "tags": ["infrastructure", "deployment"],
      "task_count": 2,
      "used_by_agents": ["mlops", "data-eng"]
    },
    {
      "name": "mlflow-tracking",
      "description": "MLflow experiment tracking and model registry",
      "version": "1.0.0",
      "tags": ["mlops", "tracking"],
      "task_count": 3,
      "used_by_agents": ["mlops"]
    }
  ]
}
```

## GET /skills/{name} — Get Skill Detail

**Response** `200 OK`:
```json
{
  "name": "kubernetes-ops",
  "description": "Kubernetes cluster operations and deployment management",
  "version": "1.0.0",
  "tags": ["infrastructure", "deployment"],
  "mcp_servers": [
    {
      "url": "http://genai-metamcp.genai.svc.cluster.local:12008/metamcp/genai/mcp",
      "tool_filter": ["kubectl_get", "kubectl_apply", "kubectl_logs", "kubectl_describe"]
    }
  ],
  "prompt_fragment": "When performing Kubernetes operations:\n...",
  "tasks": [
    {
      "name": "deploy-model",
      "description": "Deploy a trained model to the cluster",
      "inputs": [{"name": "model_name", "type": "string"}, {"name": "namespace", "type": "string", "default": "genai"}],
      "evaluation": {
        "dataset": "skills/eval/kubernetes-ops/deploy-model.json",
        "metrics": ["task_completion", "correctness"]
      }
    },
    {
      "name": "check-status",
      "description": "Check deployment status and pod health",
      "inputs": [{"name": "deployment_name", "type": "string"}]
    }
  ],
  "used_by_agents": ["mlops", "data-eng"],
  "mlflow_model_name": "skill:kubernetes-ops",
  "mlflow_version": 1
}
```

## PUT /skills/{name} — Update Skill

Updates create a new version. Request body same schema as POST.

**Response** `200 OK`:
```json
{
  "name": "kubernetes-ops",
  "version": "1.1.0",
  "mlflow_version": 2,
  "updated_at": "2026-03-20T14:00:00Z",
  "changes": "New version created. Agents using 'latest' will pick up changes on next invocation."
}
```

## DELETE /skills/{name} — Delete Skill

**Response** `200 OK` (no agents reference it):
```json
{"message": "Skill 'kubernetes-ops' deleted."}
```

**Response** `409 Conflict` (agents reference it, no force flag):
```json
{
  "error": {
    "message": "Skill 'kubernetes-ops' is referenced by agents: mlops, data-eng. Use ?force=true to delete anyway.",
    "code": "skill_in_use",
    "referencing_agents": ["mlops", "data-eng"]
  }
}
```

**Response** `200 OK` (with `?force=true`):
```json
{"message": "Skill 'kubernetes-ops' force-deleted. Warning: agents mlops, data-eng will lose this skill on next invocation."}
```

## GET /skills/{name}/tasks — List Skill Tasks

**Response** `200 OK`:
```json
{
  "skill": "kubernetes-ops",
  "tasks": [
    {
      "name": "deploy-model",
      "description": "Deploy a trained model to the cluster",
      "inputs": [{"name": "model_name", "type": "string"}, {"name": "namespace", "type": "string", "default": "genai"}],
      "has_evaluation": true,
      "last_benchmark": {
        "timestamp": "2026-03-20T10:00:00Z",
        "pass_rate": 0.85,
        "avg_latency_seconds": 12.3
      }
    },
    {
      "name": "check-status",
      "description": "Check deployment status and pod health",
      "inputs": [{"name": "deployment_name", "type": "string"}],
      "has_evaluation": false,
      "last_benchmark": null
    }
  ]
}
```

## POST /skills/{name}/tasks/{task}/benchmark — Run Task Benchmark

**Request** (optional — defaults to evaluation dataset from skill definition):
```json
{
  "agent": "mlops",
  "dataset_override": null,
  "llm_config_override": null
}
```

**Response** `202 Accepted`:
```json
{
  "benchmark_id": "bench-abc123",
  "status": "running",
  "mlflow_experiment": "eval:mlops:kubernetes-ops:deploy-model",
  "mlflow_run_id": "run-xyz789"
}
```

**Response** (poll via GET /benchmarks/{id}):
```json
{
  "benchmark_id": "bench-abc123",
  "status": "completed",
  "results": {
    "total_cases": 10,
    "passed": 8,
    "failed": 2,
    "pass_rate": 0.80,
    "avg_latency_seconds": 11.2,
    "failures": [
      {"case_id": "deploy-gpu", "reason": "Missing expected tool call: kubectl_apply"},
      {"case_id": "deploy-multi-ns", "reason": "Output missing: 'staging'"}
    ]
  },
  "mlflow_experiment": "eval:mlops:kubernetes-ops:deploy-model",
  "mlflow_run_id": "run-xyz789"
}
```

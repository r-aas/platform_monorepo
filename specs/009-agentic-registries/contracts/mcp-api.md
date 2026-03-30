# API Contract: MCP Registry

## Endpoint

```
POST /webhook/mcp
Content-Type: application/json
X-API-Key: {WEBHOOK_API_KEY}
```

---

## Actions

### `list_servers` — List all MCP servers

**Request:**
```json
{ "action": "list_servers" }
```

**Response:**
```json
{
  "servers": [
    {
      "name": "mlflow",
      "title": "MLflow",
      "description": "Experiment tracking, run analysis, model registry",
      "tool_count": 10,
      "used_by_agents": ["mlops", "devops", "analyst"]
    },
    {
      "name": "n8n-manager",
      "title": "n8n Workflow Manager",
      "description": "Workflow CRUD, execution management, webhook triggers",
      "tool_count": 11,
      "used_by_agents": ["mlops", "mcp", "devops"]
    }
  ],
  "count": 6
}
```

### `get_server` — Get server detail with tool list

**Request:**
```json
{ "action": "get_server", "server": "mlflow" }
```

**Response:**
```json
{
  "name": "mlflow",
  "title": "MLflow",
  "description": "Experiment tracking, run analysis, model registry",
  "image": "genai-mcp-mlflow:latest",
  "tools": [
    "get_experiments",
    "get_runs",
    "get_run",
    "query_runs",
    "get_run_artifacts",
    "get_best_run",
    "compare_runs",
    "get_registered_models",
    "get_model_versions",
    "search_runs_by_tags"
  ],
  "tool_count": 10,
  "used_by_agents": ["mlops", "devops", "analyst"]
}
```

### `list_tools` — Flat list of all tools across all servers

**Request:**
```json
{ "action": "list_tools" }
```

**Response:**
```json
{
  "tools": [
    { "tool": "get_experiments", "server": "mlflow" },
    { "tool": "get_runs", "server": "mlflow" },
    { "tool": "list_workflows", "server": "n8n-manager" },
    { "tool": "search_nodes", "server": "n8n-knowledge" }
  ],
  "count": 31
}
```

### `list_by_agent` — MCP servers available to an agent

**Request:**
```json
{ "action": "list_by_agent", "agent": "devops" }
```

**Response:**
```json
{
  "agent": "devops",
  "servers": [
    {
      "name": "n8n-manager",
      "title": "n8n Workflow Manager",
      "tool_count": 11
    },
    {
      "name": "mlflow",
      "title": "MLflow",
      "tool_count": 10
    }
  ],
  "total_tools": 21
}
```

## Data Source

The MCP registry reads from two sources:

1. **`mcp-servers/catalog.yaml`** — server metadata (name, title, description, image)
2. **Gateway tool inventory** — live tool list per server (queried from running gateway or cached from last startup)

Tool lists are resolved by querying the gateway's SSE endpoint or by parsing the MCP server implementations directly. If the gateway is unavailable, the registry returns server metadata without tool lists.

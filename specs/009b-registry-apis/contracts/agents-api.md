# API Contract: Agent Registry

## Endpoint

```
POST /webhook/agents
Content-Type: application/json
X-API-Key: {WEBHOOK_API_KEY}
```

---

## Actions

### `list` — List all agents

**Request:**
```json
{ "action": "list" }
```

**Response:**
```json
{
  "agents": [
    {
      "name": "mlops",
      "description": "MLOps assistant for platform management",
      "config": {
        "provider": "ollama",
        "model": "",
        "temperature": 0.3,
        "top_p": 0.9,
        "num_ctx": 32768,
        "max_iterations": 10
      },
      "mcp_servers": ["n8n-knowledge", "n8n-manager", "mlflow"],
      "skills": ["mlops.evaluate"],
      "prompt_version": "3",
      "prompt_alias": "production"
    }
  ],
  "count": 7
}
```

### `get` — Get agent detail

**Request:**
```json
{ "action": "get", "name": "mlops" }
```

**Response:**
```json
{
  "name": "mlops",
  "description": "MLOps assistant for platform management",
  "config": {
    "provider": "ollama",
    "model": "",
    "temperature": 0.3,
    "top_p": 0.9,
    "num_ctx": 32768,
    "max_iterations": 10
  },
  "mcp_servers": ["n8n-knowledge", "n8n-manager", "mlflow"],
  "skills": ["mlops.evaluate"],
  "prompt_version": "3",
  "prompt_alias": "production",
  "prompt_template": "You are an MLOps assistant..."
}
```

**Error (404):**
```json
{ "error": "Agent 'unknown' not found" }
```

### `update_config` — Update agent configuration tags

Updates structured tags on the agent. Does NOT change the prompt template (use `/webhook/prompts` for that).

**Request:**
```json
{
  "action": "update_config",
  "name": "mlops",
  "config": {
    "temperature": 0.5,
    "max_iterations": 15
  }
}
```

**Response:**
```json
{
  "name": "mlops",
  "updated_tags": ["agent.temperature", "agent.max_iterations"],
  "config": { "temperature": 0.5, "max_iterations": 15 }
}
```

### `set_mcp_servers` — Set MCP server access

**Request:**
```json
{
  "action": "set_mcp_servers",
  "name": "mlops",
  "mcp_servers": ["n8n-knowledge", "n8n-manager", "mlflow"]
}
```

`mcp_servers` can be:
- Array of server names: `["n8n-manager", "mlflow"]`
- `["all"]` — unrestricted access
- `[]` — no MCP access

**Response:**
```json
{
  "name": "mlops",
  "mcp_servers": ["n8n-knowledge", "n8n-manager", "mlflow"]
}
```

### `set_skills` — Set equipped skills

**Request:**
```json
{
  "action": "set_skills",
  "name": "coder",
  "skills": ["coder.review", "coder.debug", "writer.rewrite"]
}
```

**Response:**
```json
{
  "name": "coder",
  "skills": ["coder.review", "coder.debug", "writer.rewrite"],
  "warnings": []
}
```

**Warning example** (skill requires MCP server the agent doesn't have):
```json
{
  "name": "coder",
  "skills": ["coder.review", "coder.debug", "mlops.evaluate"],
  "warnings": [
    "Skill 'mlops.evaluate' requires MCP server 'mlflow' but agent 'coder' does not have 'mlflow' in mcp_servers"
  ]
}
```

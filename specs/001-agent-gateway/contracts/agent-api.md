# Contract: Agent Discovery & Export API

**Spec**: FR-006, FR-007

## GET /agents

List all available agents.

**Response** `200 OK`:
```json
{
  "agents": [
    {
      "name": "mlops",
      "description": "MLOps assistant for model lifecycle management",
      "runtime": "n8n",
      "workflow": "chat-v1",
      "skills": ["kubernetes-ops", "mlflow-tracking"],
      "input_parameters": [
        {"name": "domain", "type": "string", "default": "machine learning operations"}
      ]
    },
    {
      "name": "agent-ops",
      "description": "Platform agent for managing agents, skills, workflows, and benchmarks",
      "runtime": "n8n",
      "workflow": "chat-v1",
      "skills": ["agent-management", "skill-management", "benchmark-runner", "n8n-workflow-ops"],
      "input_parameters": []
    }
  ]
}
```

## GET /agents/{name}

Get detailed agent info with resolved skills.

**Response** `200 OK`:
```json
{
  "name": "mlops",
  "description": "MLOps assistant for model lifecycle management",
  "runtime": "n8n",
  "workflow": "chat-v1",
  "version": 3,
  "agentspec_version": "26.2.0",
  "llm": {
    "model": "qwen2.5:14b",
    "url": "http://genai-litellm.genai.svc.cluster.local:4000/v1"
  },
  "skills": [
    {
      "name": "kubernetes-ops",
      "description": "Kubernetes cluster operations and deployment management",
      "tasks": ["deploy-model", "check-status"],
      "tool_count": 4
    },
    {
      "name": "mlflow-tracking",
      "description": "MLflow experiment tracking and model registry",
      "tasks": ["log-metrics", "search-experiments", "compare-runs"],
      "tool_count": 6
    }
  ],
  "input_parameters": [
    {"name": "domain", "type": "string", "default": "machine learning operations"}
  ],
  "system_prompt_preview": "You are an expert in {{domain}}..."
}
```

**Response** `404`:
```json
{"error": {"message": "Agent 'foo' not found", "code": "agent_not_found"}}
```

## GET /agents/{name}/spec

Export full Agent Spec JSON (FR-007). Compatible with pyagentspec and other Agent Spec runtimes.

**Response** `200 OK` (`Content-Type: application/json`):
```json
{
  "component_type": "Agent",
  "name": "mlops",
  "description": "MLOps assistant for model lifecycle management",
  "metadata": {
    "runtime": "n8n",
    "workflow": "chat-v1"
  },
  "inputs": [
    {"title": "domain", "type": "string", "default": "machine learning operations"}
  ],
  "outputs": [],
  "llm_config": {
    "component_type": "OllamaConfig",
    "name": "ollama-litellm",
    "url": "http://genai-litellm.genai.svc.cluster.local:4000/v1",
    "model_id": "qwen2.5:14b"
  },
  "system_prompt": "You are an expert in {{domain}}...",
  "tools": [],
  "toolboxes": [
    {
      "component_type": "MCPToolBox",
      "name": "genai-tools",
      "client_transport": {
        "component_type": "StreamableHTTPTransport",
        "name": "metamcp-genai",
        "url": "http://genai-metamcp.genai.svc.cluster.local:12008/metamcp/genai/mcp"
      }
    }
  ],
  "agentspec_version": "26.2.0"
}
```

**Notes**:
- MCP server URLs from skills are translated to Agent Spec `MCPToolBox` + `StreamableHTTPTransport` format for interop
- SensitiveField values (api_key, sensitive_headers) are excluded per Agent Spec convention (FR, acceptance scenario 5.2)
- Response validates against `pyagentspec.serialization.AgentSpecSerializer` schema
- `api_key` fields replaced with `"$SENSITIVE"` placeholder

## GET /health

**Response** `200 OK`:
```json
{"status": "healthy", "mlflow": "connected", "agents_loaded": 3}
```

# Research: Agent Gateway

**Date**: 2026-03-20
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## Oracle Agent Spec (pyagentspec)

### Current Version
- **26.2.0** (not 26.1.0 as originally stated in spec — updated)
- Versioning: `YEAR.QUARTER.PATCH` with deprecation cycle
- Source: `~/work/clones/agent-spec/`
- Package: `pyagentspec` (pip/uv installable)

### Agent Class (`pyagentspec.agent.Agent`)
```python
class Agent(AgenticComponent):
    llm_config: LlmConfig           # Polymorphic — OllamaConfig, OpenAiCompatibleConfig, etc.
    system_prompt: str               # Supports {{placeholder}} syntax
    tools: List[Tool]                # Individual tools
    toolboxes: List[ToolBox]         # MCPToolBox goes here (added in 25.4.2)
    human_in_the_loop: bool = True
    transforms: List[MessageTransform]  # Added in 26.2.0
    # Inherited from AgenticComponent:
    # name, description, metadata, inputs, outputs, id, component_type
```

### MCPToolBox (`pyagentspec.mcp.tools.MCPToolBox`)
```python
class MCPToolBox(ToolBox):
    client_transport: ClientTransport    # StreamableHTTPTransport, SSETransport, StdioTransport
    tool_filter: Optional[List[Union[MCPToolSpec, str]]]  # None = all tools
```

### Transport Types (`pyagentspec.mcp.clienttransport`)
```python
class StreamableHTTPTransport(RemoteTransport):
    # Inherits: url, headers, sensitive_headers, auth, session_parameters
    pass

class SSETransport(RemoteTransport):
    # Same as above — for SSE-based MCP servers
    pass

class StdioTransport(ClientTransport):
    command: str
    args: List[str]
    env: Optional[Dict[str, str]]
```

### LLM Configs
```python
class OpenAiCompatibleConfig(LlmConfig):
    url: str
    model_id: str
    api_type: OpenAIAPIType = CHAT_COMPLETIONS
    api_key: SensitiveField[Optional[str]]

class OllamaConfig(OpenAiCompatibleConfig):
    pass  # Inherits everything
```

### Serialization
- `AgentSpecSerializer().to_json(agent)` → JSON string
- `AgentSpecSerializer().to_dict(agent)` → dict
- Deserialization via `AgentSpecDeserializer` (schema-driven)
- YAML ↔ JSON interchangeable (YAML is just more readable for authoring)

### SensitiveField Convention
- `SensitiveField[T]` marks fields that should be excluded from exported configs
- Used for: `api_key`, `sensitive_headers`, mTLS key/cert paths
- Serializer replaces with `"$SENSITIVE"` reference on export

### $component_ref
- In YAML: `$component_ref: path/to/component`
- Resolves to a shared component defined in `$referenced_components` or external file
- Used for: shared LlmConfig, shared MCP server configs across agents

### {{placeholder}} Syntax
- Jinja2-like substitution in `system_prompt`
- Agent.inputs auto-inferred from placeholders via `get_placeholder_properties_from_json_object()`
- Resolved at runtime from request parameters

## MLflow Prompt Registry

### API (MLflow 3.x)
- `POST /api/2.0/mlflow/prompts/create` — create prompt
- `POST /api/2.0/mlflow/prompts/update` — update prompt metadata
- `POST /api/2.0/mlflow/prompt-versions/create` — create version with template text + tags
- `GET /api/2.0/mlflow/prompts/get?name=X` — get prompt + latest version
- `GET /api/2.0/mlflow/prompts/search` — list all prompts
- Python SDK: `mlflow.MlflowClient().create_prompt()`, `.create_prompt_version()`, `.get_prompt()`

### Tag Schema for Agents
```
runtime = "n8n" | "python"
workflow = "chat-v1"                    # n8n workflow name (if runtime=n8n)
llm_url = "http://...litellm:4000/v1"
llm_model = "qwen2.5:14b"
mcp_servers_json = '[{"url":"http://...metamcp:12008/metamcp/genai/mcp"}]'
agentspec_version = "26.2.0"
agent_description = "MLOps assistant..."
```

## MetaMCP Integration

### Current State
- 5 servers: fetch, time, gitlab, kubernetes, n8n
- 2 namespaces: genai (all 5), platform (gitlab, kubernetes, n8n)
- Endpoints expose Streamable HTTP at: `http://genai-metamcp.genai.svc.cluster.local:12008/metamcp/{namespace}/mcp`
- Each endpoint = one MCP interface aggregating all servers in that namespace

### Our Mapping
- MetaMCP namespace → MCP server URL (direct)
- Skills reference MCP server URLs with optional tool_filter — no MCPToolBox wrapping
- On Agent Spec export, URLs are translated to MCPToolBox + StreamableHTTPTransport for interop
- Tool filtering optional per MCP server entry

## n8n Workflow Architecture

### Existing Workflows (from import script)
Webhook-bearing (activatable): `prompt-crud-v1`, `prompt-eval-v1`, `openai-compat-v1`, `mlflow-data-v1`, `mlflow-experiments-v1`, `chat-v1`, `a2a-server-v1`, `trace-v1`, `sessions-v1`, `agents-v1`

### chat-v1 Webhook Interface
- URL: `http://genai-n8n.genai.svc.cluster.local:5678/webhook/chat-v1`
- Method: POST
- Body: `{ "chatInput": "user message", "sessionId": "optional-session-id" }`
- Response: SSE stream or JSON (depends on workflow config)

### n8n API for Workflow GitOps
- List workflows: `GET /api/v1/workflows`
- Get workflow: `GET /api/v1/workflows/{id}`
- Create workflow: `POST /api/v1/workflows`
- Update workflow: `PUT /api/v1/workflows/{id}`
- Activate/deactivate: `PATCH /api/v1/workflows/{id}` with `{ "active": true/false }`
- Auth: `X-N8N-API-KEY` header (from `n8n-api-credentials` k8s secret)

### Credential Resolution
- n8n stores credentials with: `id` (integer, instance-specific), `type` (e.g., "ollamaApi"), `name` (e.g., "Ollama Local")
- Portable reference: `{ "type": "ollamaApi", "name": "Ollama Local" }` → resolve to local ID on import
- Credential types in use: `ollamaApi`, `httpHeaderAuth`

## Alternatives Considered

### Alternative A: Extend existing openai-compat-v1 n8n workflow
**Rejected**: Adding agent routing inside n8n means the routing logic is in a workflow JSON (not version-controlled code), hard to test, and couples the gateway to n8n. A standalone FastAPI service is testable, deployable independently, and follows the one-interface-swap-implementations principle.

### Alternative B: Use LiteLLM custom routing
**Rejected**: LiteLLM supports custom model routing but doesn't understand agent definitions, MCP servers, or runtime dispatch. It's a model proxy, not an agent gateway.

### Alternative C: Store Agent Spec JSON in MLflow artifacts (not prompts)
**Rejected**: MLflow artifacts are blob storage — no structured querying, no version tags, no template rendering. Prompts with tags give us both the system_prompt text and queryable metadata.

### Alternative D: Build custom agent runtime instead of using n8n
**Rejected**: n8n already handles the tool loop, session management, and tracing. Building a custom runtime would duplicate significant infrastructure. The Python runtime (P2) will use pyagentspec for this purpose when n8n's overhead isn't needed.

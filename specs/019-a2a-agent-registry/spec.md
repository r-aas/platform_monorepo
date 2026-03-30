<!-- status: shipped -->
<!-- pr: #10 -->
# Spec 019: A2A-Compliant Agent Registry

## Problem

The platform has 7 agents with a working agent catalog (spec 017, `/webhook/agents`) and an A2A server (`a2a-server.json`). But these are disconnected --- the agent catalog returns platform-internal JSON while the A2A server builds agent cards from a separate MLflow query. The A2A implementation has spec compliance gaps (wrong error codes, non-standard discovery URL, missing required fields). Most importantly, there is no way to CRUD agents over A2A or configure multi-agent systems where agents delegate to each other via the A2A protocol.

The vision: the agent registry IS the A2A registry. Every agent is discoverable via `/.well-known/agent-card.json`. Agents can be created, configured, benchmarked, and promoted entirely over A2A-compatible APIs. Multi-agent systems compose by one agent calling another's A2A endpoint.

## Current State

### A2A server (`a2a-server.json`)

| Feature | Status | Gap |
|---------|--------|-----|
| Agent card discovery | `GET /webhook/a2a/agent-card` | Should be `/.well-known/agent-card.json` |
| `message/send` | Working | Correct |
| `tasks/get` | Working | Error code 1001 should be -32001 |
| `tasks/cancel` | Returns error | Code 1002 should be -32002 |
| `message/stream` | Not implemented | `capabilities.streaming: false` |
| Push notifications | Not implemented | Not needed yet |
| `agent/getAuthenticatedExtendedCard` | Implemented | Correct |
| Part discriminator | Handles `kind` and `type` | Correct (backward compat) |
| Skills | Built from MLflow prompts | Missing `tags` (required field) |
| Protocol version | `0.2.5` | Current |

### Agent catalog (`/webhook/agents`)

Returns internal format:
```json
{
  "name": "coder",
  "description": "...",
  "mode": "agent",
  "mcp_tools": ["all"],
  "skills": ["code-standards"],
  "tasks": [{"name": "review"}, {"name": "debug"}],
  "tags": ["domain:code"],
  "promotion": {...}
}
```

This overlaps with A2A agent cards but uses different field names and structure.

## Requirements

### FR-001: Unified agent registry backing both APIs

The agent catalog (`/webhook/agents`) becomes the single source of truth. The A2A agent card is generated FROM the catalog, not from a separate MLflow query.

Agent catalog response enriched with A2A-compatible fields:
```json
{
  "name": "coder",
  "description": "Expert software engineer...",
  "a2a": {
    "url": "http://localhost:5678/webhook/a2a",
    "protocolVersion": "0.2.5",
    "capabilities": {
      "streaming": false,
      "pushNotifications": false,
      "stateTransitionHistory": false
    },
    "skills": [
      {
        "id": "coder.review",
        "name": "Code Review",
        "description": "Review code for quality, security, and performance",
        "tags": ["code-review", "security", "quality"]
      },
      {
        "id": "coder.debug",
        "name": "Debug",
        "description": "Identify and fix bugs in code",
        "tags": ["debugging", "troubleshooting"]
      }
    ]
  }
}
```

A2A skills are derived from the agent's task prompts (`{agent}.{task}` naming).

### FR-002: Spec-compliant A2A agent card

Fix the A2A server to serve a fully spec-compliant agent card:

```json
{
  "protocolVersion": "0.2.5",
  "name": "GenAI MLOps Platform",
  "description": "Multi-agent platform with 7 specialized agents",
  "url": "http://localhost:5678/webhook/a2a",
  "version": "1.0.0",
  "provider": {
    "organization": "Applied AI Systems",
    "url": "https://github.com/r-aas"
  },
  "capabilities": {
    "streaming": false,
    "pushNotifications": false,
    "stateTransitionHistory": false
  },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [
    {
      "id": "coder",
      "name": "Coder Agent",
      "description": "Expert software engineer...",
      "tags": ["code", "review", "debug", "software-engineering"]
    },
    {
      "id": "writer",
      "name": "Writer Agent",
      "description": "Professional writing...",
      "tags": ["writing", "email", "rewrite", "content"]
    }
  ],
  "securitySchemes": {
    "apiKey": {
      "type": "apiKey",
      "in": "header",
      "name": "X-API-Key"
    }
  },
  "security": [{"apiKey": []}]
}
```

Changes from current:
- Skills populated from agent catalog (not separate MLflow query)
- Skills have required `tags` field (derived from agent tags + task names)
- `defaultInputModes`/`defaultOutputModes` use proper MIME types
- `securitySchemes` declares the API key auth used by webhooks

### FR-003: Standard error codes

Update the A2A JSON-RPC handler to use spec-defined error codes:

| Current | Spec | Constant |
|---------|------|----------|
| 1001 | -32001 | TaskNotFoundError |
| 1002 | -32002 | TaskNotCancelableError |
| 400 | -32600 | InvalidRequestError |
| N/A | -32601 | MethodNotFoundError |
| N/A | -32602 | InvalidParamsError |
| 500 | -32603 | InternalError |

### FR-004: Per-agent A2A routing

Currently, `message/send` to the A2A endpoint requires the client to specify which agent to use via the message text or metadata. Enable explicit agent targeting:

Option 1: Skill-based routing (A2A native):
```json
{
  "method": "message/send",
  "params": {
    "message": {
      "parts": [{"kind": "text", "text": "Review this code..."}],
      "role": "user"
    },
    "configuration": {
      "acceptedOutputModes": ["text/plain"]
    },
    "metadata": {
      "skill": "coder.review"
    }
  }
}
```

The A2A server maps `metadata.skill` to `agent_name` + `task` for the chat pipeline.

Option 2: Per-agent discovery via query param:
- `GET /webhook/a2a/agent-card?agent=coder` --- per-agent card with agent-specific skills

Both options should be supported. (n8n webhooks don't support path params, so query param is used for per-agent cards.)

### FR-005: Agent CRUD via A2A-compatible API

Extend the agent catalog to support creating and configuring agents over the API. This is not part of the A2A spec itself (A2A is for agent-to-agent communication, not management) but uses the same JSON structures for consistency.

```
POST /webhook/agents
{
  "action": "create",
  "name": "custom-agent",
  "description": "Custom domain agent",
  "system_prompt": "You are a specialist in...",
  "config": {
    "provider": "ollama",
    "model": "",
    "mcp_tools": "all",
    "skills": ["platform-knowledge"],
    "tags": ["domain:custom"]
  }
}
```

This creates:
1. MLflow registered model `custom-agent.SYSTEM` with the system prompt
2. Sets `agent.config` tag with the config JSON
3. Agent immediately appears in both `/webhook/agents` catalog and A2A agent card

```
POST /webhook/agents
{
  "action": "update",
  "name": "custom-agent",
  "system_prompt": "Updated prompt...",
  "config": {...}
}
```

```
POST /webhook/agents
{
  "action": "delete",
  "name": "custom-agent"
}
```

Guard: seed agents (mlops, coder, writer, reasoner, devops, analyst, mcp) cannot be deleted.

### FR-006: Multi-agent delegation via A2A

Enable agents to call other agents via A2A. When an agent's system prompt references another agent, the chat pipeline can delegate:

Add a built-in MCP tool to the chat pipeline:
```json
{
  "name": "delegate_to_agent",
  "description": "Delegate a task to another specialized agent",
  "parameters": {
    "agent": "string (agent name)",
    "task": "string (optional task name)",
    "message": "string (the task description)"
  }
}
```

Implementation: the tool calls `POST /webhook/a2a` with `message/send`, routing to the target agent. This uses A2A as the inter-agent protocol, keeping agents decoupled.

### FR-007: Smoke tests

- Agent card: `GET /webhook/a2a/agent-card` returns valid card with skills
- A2A message/send with skill routing: returns completed task
- Agent CRUD: create, get, update, delete cycle
- Per-agent card: `GET /webhook/a2a/agents/coder/agent-card`
- Error codes: invalid method returns -32601

## Files Changed

| File | What |
|------|------|
| `n8n-data/workflows/a2a-server.json` | FR-002, FR-003, FR-004: spec compliance, error codes, routing |
| `n8n-data/workflows/agents.json` | FR-001, FR-005: unified registry, CRUD actions |
| `n8n-data/workflows/chat.json` | FR-006: delegate_to_agent tool |
| `data/seed-prompts.json` | FR-005: add tags to existing agent configs for A2A skills |
| `scripts/smoke-test.sh` | FR-007: new tests |
| `specs/019-a2a-agent-registry/spec.md` | This spec |

## Dependencies

- Spec 016 (mcp-gateway) --- shipped, MCP tool routing
- Spec 017 (agent-executor) --- in-progress, agent catalog + skills
- Spec 018 (promotion-pipeline) --- in-progress, benchmark + promote
- A2A protocol v0.2.5 (Google)

## Verification

| Check | Expected |
|-------|----------|
| `GET /webhook/a2a/agent-card` | Valid A2A agent card with all 7 agents as skills |
| `POST /webhook/a2a` with `message/send` | Returns task with state `completed` |
| `POST /webhook/a2a` with `metadata.skill: "coder.review"` | Routes to coder agent with review task |
| `GET /webhook/a2a/agent-card?agent=coder` | Per-agent card with coder-specific skills |
| `POST /webhook/agents {action: "create", ...}` | Creates new agent in MLflow, appears in catalog + A2A |
| `POST /webhook/agents {action: "delete", name: "custom-agent"}` | Removes agent |
| Seed agent delete attempt | Returns error: "cannot delete seed agent" |
| Invalid JSON-RPC method | Returns error code -32601 |
| Task not found | Returns error code -32001 |
| Agent card `skills[].tags` | All skills have non-empty tags array |
| Observatory dashboard | Shows all agents including dynamically created ones |

## Non-requirements

- **A2A streaming** --- `message/stream` deferred (requires SSE support in n8n webhooks)
- **Push notifications** --- deferred (requires callback URL infrastructure)
- **Agent-to-agent authentication** --- agents within the platform trust each other; external A2A auth is deferred
- **A2A client** --- this spec covers the server side; an A2A client for calling external agents is a separate concern
- **Agent versioning** --- agents are versioned via their prompts (MLflow); A2A card `version` tracks the platform version, not individual agent versions

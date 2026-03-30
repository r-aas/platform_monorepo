<!-- status: deferred -->
<!-- parent: 009 -->
<!-- depends: 009a -->
<!-- note: agent registry API shipped in spec 019 (/webhook/agents CRUD). Skills and MCP APIs deferred. -->
# Spec 009b: Registry APIs

## Problem

No component in the stack can answer: "What agents exist?", "What can agent X do?", or "What MCP servers are available?" Agent configuration lives in MLflow tags (queryable only via raw API), MCP server definitions live in catalog.yaml (not queryable at all from inside the stack), and skill assignments are embedded in agent tags with no reverse-lookup capability.

This spec adds three webhook endpoints that expose registries as queryable APIs.

## Parent Spec

[Spec 009: AgenticOps Registries](../009-agentic-registries/spec.md) — this spec implements FR-003, FR-004, FR-005.

## Dependencies

- **009a** (Structured Agent Tags) — agents must have structured tags for the registry API to parse.

## Requirements

### FR-001: Agent Registry API

New webhook endpoint:

```
POST /webhook/agents
```

Actions:
- `list` — returns all agents (prompts where `use_case=agent`) with parsed config, mcp_servers list, and skills list
- `get` — returns specific agent with full config, skills, MCP servers, and prompt template
- `update_config` — updates structured tags (not the prompt — use `/prompts` for that)
- `set_mcp_servers` — set MCP server access for an agent
- `set_skills` — set equipped skills for an agent

Response format returns **resolved** objects — arrays instead of comma-separated strings, numbers instead of string numbers.

### FR-002: Skills Query API

New webhook endpoint:

```
POST /webhook/skills
```

Skills are a **view** on the prompts registry (`use_case=skill`), not a separate store.

Actions:
- `list` — returns all skills with descriptions and list of agents that equip them
- `get` — returns specific skill prompt with metadata
- `list_by_agent` — returns skills equipped by a specific agent
- `list_agents` — reverse lookup: agents that have a specific skill equipped
- `equip` — adds a skill to an agent's `agent.skills` tag
- `unequip` — removes a skill from an agent's `agent.skills` tag

Skill CRUD (create/update/delete) uses the existing `/webhook/prompts` endpoint.

### FR-003: MCP Registry API

New webhook endpoint:

```
POST /webhook/mcp
```

Actions:
- `list_servers` — returns all MCP servers from catalog.yaml with metadata
- `get_server` — returns specific server with live tool list from gateway
- `list_tools` — returns all tools across all servers (flat list)

Data source: catalog.yaml parsed at request time + gateway tool inventory.

### FR-004: Equip Validation Warning

When equipping a skill via `set_skills` or `equip`, if `skill.required_mcp_servers` lists servers not in the agent's `agent.mcp_servers`, return a warning (not an error). The skill can still be equipped, but it won't have the tools it needs.

### NFR-001: Query Performance

Registry queries must respond within 500ms. MLflow tag queries are indexed. MCP registry parses catalog.yaml (small file, <1ms).

## Files Changed

| File | Action |
|------|--------|
| `n8n-data/workflows/agent-registry.json` | NEW — `/webhook/agents` endpoint |
| `n8n-data/workflows/mcp-registry.json` | NEW — `/webhook/mcp` endpoint |
| `n8n-data/workflows/prompt-crud.json` | EDIT — add skill-specific actions to existing prompts workflow |
| `scripts/smoke-test.sh` | EDIT — add registry smoke tests |
| `tests/test_integration.py` | EDIT — add registry integration tests |
| `scripts/n8n-import-all.sh` | EDIT — import new workflow files |

## Verification

| Check | FR | Expected |
|-------|-----|----------|
| `POST /webhook/agents {"action":"list"}` | FR-001 | Returns all 7 agents with parsed config, mcp_servers array, skills array |
| `POST /webhook/agents {"action":"get","name":"mlops"}` | FR-001 | Returns mlops with description, config, mcp_servers, skills, prompt_template |
| `POST /webhook/agents {"action":"get","name":"unknown"}` | FR-001 | 404 error |
| `POST /webhook/agents {"action":"update_config","name":"mlops","config":{"temperature":0.5}}` | FR-001 | Updates tag, returns updated config |
| `POST /webhook/skills {"action":"list"}` | FR-002 | Returns all 6 skills with equipped_by agents |
| `POST /webhook/skills {"action":"list_by_agent","agent":"coder"}` | FR-002 | Returns coder.review, coder.debug, writer.rewrite |
| `POST /webhook/skills {"action":"list_agents","skill":"coder.review"}` | FR-002 | Returns coder, mlops, devops (agents with this skill equipped) |
| `POST /webhook/skills {"action":"equip","agent":"writer","skill":"coder.review"}` | FR-002 | Adds coder.review to writer's skills |
| `POST /webhook/mcp {"action":"list_servers"}` | FR-003 | Returns all MCP servers with title, description, tool_count |
| `POST /webhook/mcp {"action":"get_server","server":"mlflow"}` | FR-003 | Returns mlflow with tools list and used_by_agents |
| `POST /webhook/mcp {"action":"list_tools"}` | FR-003 | Returns flat list of all tools across all servers |
| Equip skill with unmet MCP dependency | FR-004 | Returns warnings array, skill still equipped |
| Registry query latency | NFR-001 | All queries < 500ms |
| `bash scripts/smoke-test.sh` | All | All pass including new registry tests |

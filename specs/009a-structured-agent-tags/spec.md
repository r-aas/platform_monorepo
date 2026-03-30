<!-- status: deferred -->
<!-- parent: 009 -->
<!-- note: agent.config structured config delivered by spec 017. Discrete MLflow tags deferred — blob works at current scale. -->
# Spec 009a: Structured Agent Tags

## Problem

Agent configuration is stored as a monolithic `agent.config` JSON blob — a single stringified JSON in one MLflow tag. Individual config values (temperature, model, MCP access) are buried inside, making them un-queryable, un-diffable, and invisible to any tool that reads MLflow tags.

Similarly, skills (task prompts) use `use_case: "task"` and `task.description` tags with agent-scoped semantics. A `coder.review` skill belongs to the coder agent by naming convention — it can't be shared with `devops` or `analyst` without duplication.

This is the foundational migration that all subsequent registry work (009b, 009c, 009d) depends on.

## Parent Spec

[Spec 009: AgenticOps Registries](../009-agentic-registries/spec.md) — this spec implements FR-001, FR-002 (partial), FR-006, FR-007, and NFR-001.

## Requirements

### FR-001: Structured Agent Tags

Replace the monolithic `agent.config` JSON blob with discrete, typed MLflow tags.

**Current** (single JSON string):
```json
{
  "agent.config": "{\"provider\":\"ollama\",\"model\":\"\",\"temperature\":0.3,...,\"mcp_tools\":\"all\"}"
}
```

**Proposed** (structured tags):
```json
{
  "use_case": "agent",
  "agent.description": "MLOps assistant for platform management",
  "agent.provider": "ollama",
  "agent.model": "",
  "agent.temperature": "0.3",
  "agent.top_p": "0.9",
  "agent.num_ctx": "32768",
  "agent.max_iterations": "10",
  "agent.mcp_servers": "n8n-knowledge,n8n-manager,mlflow",
  "agent.skills": "mlops.evaluate"
}
```

Key changes:
- `mcp_tools` string → `agent.mcp_servers` referencing catalog.yaml server names
- New `agent.skills` tag listing assigned skill names
- New `agent.description` for human-readable summary
- Config fields promoted to individual tags (queryable, not buried in JSON)
- `"all"` remains valid for `agent.mcp_servers` (unrestricted access)
- Empty string = no MCP access (chat-only agents like writer, reasoner)

### FR-002: Skill Tag Migration

Migrate skill tags from agent-scoped to domain-scoped semantics:

| Old Tag | New Tag |
|---------|---------|
| `use_case: "task"` | `use_case: "skill"` |
| `task.description` | `skill.description` |
| (none) | `skill.required_mcp_servers` |
| (none) | `skill.output_format` |

Names stay the same (`{DOMAIN}.{SKILL}` format). The domain prefix is organizational, not ownership.

### FR-003: Chat Workflow Reads Structured Tags

The Prompt Resolver in `chat.json` must read the new structured tags instead of parsing `agent.config` JSON blob.

Tag resolution logic:
1. Read `agent.provider`, `agent.model`, etc. as individual tags
2. Read `agent.mcp_servers` → split on comma → pass to MCP Client node
3. Read `agent.skills` → fetch matching skill prompts → inject into system prompt
4. If structured tags are missing, fall back to `agent.config` JSON blob (NFR-001)

### FR-004: Seed Data Migration

Update `data/seed-prompts.json` to use the new tag schema:

**Agents** (7 total):
- Add `agent.description`, `agent.mcp_servers`, `agent.skills`
- Add individual config tags (`agent.temperature`, etc.)
- Remove `agent.config` JSON blob

**Skills** (6 total):
- Change `use_case: "task"` → `use_case: "skill"`
- Change `task.description` → `skill.description`
- Add `skill.required_mcp_servers`, `skill.output_format`

**Utility prompts** (7 total): unchanged.

### NFR-001: Backward Compatibility

The Prompt Resolver must handle both old (`agent.config` JSON blob) and new (structured tags) formats during migration. If `agent.provider` exists, use structured tags. Otherwise, fall back to parsing `agent.config` JSON blob.

## Agent ↔ MCP Server Mapping

| Agent | `agent.mcp_servers` | Rationale |
|-------|---------------------|-----------|
| mlops | `n8n-knowledge,n8n-manager,mlflow` | Full platform access |
| mcp | `n8n-knowledge,n8n-manager` | Workflow management focus |
| devops | `n8n-manager,mlflow` | Monitoring + execution inspection |
| analyst | `mlflow` | Data analysis only |
| coder | `` | Code generation, no external tools |
| writer | `` | Writing, no external tools |
| reasoner | `` | Reasoning, no external tools |

## Agent ↔ Skill Mapping

| Agent | `agent.skills` | Rationale |
|-------|---------------|-----------|
| mlops | `mlops.evaluate` | Platform evaluation workflows |
| mcp | `` | Pure workflow management |
| devops | `coder.debug` | Infrastructure debugging |
| analyst | `mlops.evaluate,reasoner.solve` | Analysis + problem solving |
| coder | `coder.review,coder.debug,writer.rewrite` | Code lifecycle skills |
| writer | `writer.email,writer.rewrite` | Writing variations |
| reasoner | `reasoner.solve` | Math/logic problem solving |

## Files Changed

| File | Action |
|------|--------|
| `data/seed-prompts.json` | EDIT — migrate tags (agent.config → structured, task → skill) |
| `n8n-data/workflows/chat.json` | EDIT — Prompt Resolver reads structured tags with fallback |
| `tests/test_workflow_json.py` | EDIT — update assertions for new tag schema |
| `scripts/smoke-test.sh` | EDIT — verify structured tags work end-to-end |

## Verification

| Check | FR | Expected |
|-------|-----|----------|
| `python3 -c "import json; d=json.load(open('data/seed-prompts.json')); print(len(d))"` | FR-004 | 20 (unchanged count) |
| `grep -c 'agent.config' data/seed-prompts.json` | FR-001 | 0 (no JSON blobs remain) |
| `grep -c 'agent.provider' data/seed-prompts.json` | FR-001 | 7 (one per agent) |
| `grep -c 'agent.skills' data/seed-prompts.json` | FR-001 | 7 (one per agent) |
| `grep -c '"use_case": "skill"' data/seed-prompts.json` | FR-002 | 6 (all task prompts migrated) |
| `grep -c '"use_case": "task"' data/seed-prompts.json` | FR-002 | 0 (no old tags remain) |
| POST `/webhook/chat` with `agent_name=coder` | FR-003 | Chat works with structured tags |
| POST `/webhook/chat` with `agent_name=writer`, task=`email` | FR-003 | Skill prompt injected from `agent.skills` |
| `uv run pytest tests/test_workflow_json.py` | FR-004 | All pass |
| `bash scripts/smoke-test.sh` | FR-003 | All pass |
| Revert one agent to old `agent.config` blob, send chat | NFR-001 | Still works (fallback) |

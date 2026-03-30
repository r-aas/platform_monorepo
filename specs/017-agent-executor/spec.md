<!-- status: shipped -->
<!-- pr: #10 -->
# Spec 017: Parameterized Agent Executor

## Problem

The `chat.json` workflow already functions as a parameterized agent executor — it resolves prompts from MLflow, selects MCP tools per agent config, routes between agent mode and chat mode, logs traces, and manages sessions. But this behavior is implicit and undocumented. The constitution (v3.1.0 Principle V) formalizes the model:

```
Agent = System Prompt Template + MCP Servers + Skills
```

Three gaps exist between the constitution's model and the current implementation:

1. **No skills injection** — agents have prompts and MCP tools, but no mechanism to inject domain-specific instructions/knowledge at runtime
2. **No agent catalog API** — agents are discoverable only by MLflow naming convention (`*.SYSTEM`), with no unified endpoint to list agents and their capabilities
3. **No formal config schema** — `agent.config` is a freeform JSON string in MLflow model-level tags, with no validation or documentation of supported fields

## Current State

### Agent definition (MLflow)

Each agent is an MLflow registered model with naming convention `{agent}.SYSTEM`:
- `mlops.SYSTEM`, `mcp.SYSTEM`, `devops.SYSTEM`, `analyst.SYSTEM`, `coder.SYSTEM`, `writer.SYSTEM`, `reasoner.SYSTEM`
- Prompt template versioned with aliases (`production`, `staging`)
- Runtime config stored in `agent.config` model-level tag (JSON string)

### Agent config (current schema, undocumented)

```json
{
  "provider": "ollama",
  "model": "",
  "temperature": 0.3,
  "top_p": 0.9,
  "num_ctx": 32768,
  "max_iterations": 10,
  "mcp_tools": "all" | "tool1,tool2,..." | ""
}
```

### Executor flow (chat.json, 10 nodes)

```
POST /webhook/chat → Prompt Resolver → Error Gate → Mode Gate
  ├─ Agent Mode (mcp_tools non-empty) → AI Agent + MCP Client + Memory
  └─ Chat Mode (mcp_tools empty) → Chat Handler (direct LiteLLM)
→ Trace Logger → Response
```

### Task prompts (existing)

Task-specific prompts follow `{agent}.{task}` naming: `coder.review`, `coder.debug`, `writer.email`, `writer.rewrite`, `reasoner.solve`, `mlops.evaluate`, `analyst.traces`, `devops.health`, `mcp.workflow`. The Prompt Resolver classifies user messages against available tasks.

## Requirements

### FR-001: Agent config schema validation

Define and enforce a typed schema for `agent.config`:

```json
{
  "provider": "ollama",
  "model": "",
  "temperature": 0.3,
  "top_p": 0.9,
  "num_ctx": 32768,
  "max_iterations": 10,
  "mcp_tools": "all",
  "skills": [],
  "description": "",
  "tags": []
}
```

New fields:
- `skills` (array of strings) — skill names to inject at runtime (FR-003)
- `description` (string) — human-readable agent description for catalog
- `tags` (array of strings) — categorization tags for filtering (`domain:code`, `mode:agent`, `tier:platform`)

The Prompt Resolver in `chat.json` must validate `agent.config` against this schema and reject malformed configs with a clear error.

### FR-002: Agent catalog webhook

New action on the existing `/webhook/chat` endpoint (or new `/webhook/agents` endpoint):

```
POST /webhook/agents
{
  "action": "list"
}
```

Response:
```json
{
  "agents": [
    {
      "name": "coder",
      "description": "Expert software engineer...",
      "mode": "agent",
      "mcp_tools": ["fetch"],
      "skills": [],
      "tasks": ["review", "debug"],
      "tags": ["domain:code"],
      "prompt_version": 3,
      "prompt_alias": "production"
    }
  ]
}
```

```
POST /webhook/agents
{
  "action": "get",
  "name": "coder"
}
```

Response: single agent detail with full config and prompt template.

Implementation: new n8n workflow `agents.json` (sub-workflow, no trigger — called by a thin webhook workflow, or a new action in the prompts workflow).

### FR-003: Skills injection

Skills are markdown instruction blocks stored as MLflow registered models with naming convention `skill.{name}`:

```
skill.code-review → "When reviewing code, follow OWASP top 10..."
skill.platform-ops → "The genai-mlops stack has 7 subsystems..."
skill.data-analysis → "When analyzing traces, always report p50/p95..."
```

Skills are versioned in MLflow just like prompts (same registry, different naming prefix). The `skills` array in `agent.config` lists skill names to inject.

Injection mechanism in Prompt Resolver:
1. Read `config.skills` array
2. For each skill name, fetch `skill.{name}` from MLflow prompt registry
3. Append skill content to the system prompt after the agent's base template
4. Skills are additive — they extend the agent's instructions, never replace

Format in assembled prompt:
```
{agent system prompt}

---

## Skills

### {skill.name}
{skill.content}

### {skill.name}
{skill.content}
```

### FR-004: Seed skills in seed-prompts.json

Add initial skills to `data/seed-prompts.json`:

| Skill | Content | Used by |
|-------|---------|---------|
| `skill.platform-knowledge` | Stack topology, subsystem map, service ports, webhook endpoints | mlops, devops |
| `skill.eval-methodology` | Evaluation best practices, scoring calibration, sample size requirements | mlops, analyst |
| `skill.code-standards` | Code review checklist, security patterns, language-specific idioms | coder |

Update agent configs to reference skills:
```json
{
  "mlops.SYSTEM": { "skills": ["platform-knowledge", "eval-methodology"] },
  "devops.SYSTEM": { "skills": ["platform-knowledge"] },
  "analyst.SYSTEM": { "skills": ["eval-methodology"] },
  "coder.SYSTEM": { "skills": ["code-standards"] }
}
```

### FR-005: Agent catalog in Observatory dashboard

The Observatory dashboard (`scripts/dashboard.py`) already reads agents from MLflow. Extend the agents panel to show:
- Skills per agent (from config)
- Agent description (from config)
- Tags (from config)
- Task list per agent

This replaces the current minimal agent card with a richer view.

### FR-006: Smoke test coverage

Add smoke tests:
- Agent catalog: `POST /webhook/agents {action:"list"}` returns all 7 agents
- Agent detail: `POST /webhook/agents {action:"get", name:"coder"}` returns config with skills
- Skill resolution: `POST /webhook/chat` with agent that has skills → response includes `skills_loaded` in metadata

## Files Changed

| File | What |
|------|------|
| `n8n-data/workflows/chat.json` | FR-001: schema validation in Prompt Resolver, FR-003: skill injection |
| `n8n-data/workflows/agents.json` | FR-002: new agent catalog sub-workflow |
| `data/seed-prompts.json` | FR-001: add new config fields, FR-004: add skill definitions |
| `scripts/n8n-import-all.sh` | FR-002: import agents.json |
| `scripts/dashboard.py` | FR-005: extend agent panel |
| `scripts/smoke-test.sh` | FR-006: new test cases |
| `specs/017-agent-executor/spec.md` | This spec |

## Dependencies

- Spec 004 (agent-task-prompts) — shipped, established `{agent}.{task}` naming
- Spec 007 (agent-tool-routing) — shipped, established per-agent `mcp_tools`
- Spec 010 (global-config) — shipped, established `config.yaml` as source of truth
- Spec 014 (observatory-dashboard) — shipped, dashboard exists

## Verification

| Check | Expected |
|-------|----------|
| `POST /webhook/agents {action:"list"}` | Returns 7 agents with config, skills, tasks |
| `POST /webhook/agents {action:"get", name:"mlops"}` | Returns full config including `skills: ["platform-knowledge", "eval-methodology"]` |
| `POST /webhook/chat {agent_name:"mlops", message:"hello"}` | Response metadata includes `skills_loaded: ["platform-knowledge", "eval-methodology"]` |
| Malformed agent.config in MLflow | Prompt Resolver returns structured error, not crash |
| Observatory dashboard | Agent panel shows skills, descriptions, tags |
| Smoke tests | All pass including new agent catalog tests |
| Existing chat tests | No regressions — agents without skills work unchanged |

## Non-requirements

- **Sub-agent composition** — calling agents from agents is deferred (009d-meta-agents scope)
- **Dynamic skill selection** — skills are statically configured per agent, not selected at runtime by the LLM
- **Skill marketplace** — skills are internal to this platform, not shared externally
- **Agent CRUD API** — agents are defined in seed-prompts.json and managed via MLflow; no runtime creation

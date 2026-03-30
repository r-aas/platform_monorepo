# Plan: Spec 017 — Parameterized Agent Executor

## Approach

Extend the existing `chat.json` workflow with skills injection and config validation, add a new `agents.json` webhook workflow for the agent catalog API, update `seed-prompts.json` with skill definitions and enriched agent configs, and extend the dashboard agent panel.

## Implementation Order

Changes are ordered to minimize risk — seed data first, then workflow changes, then dashboard, then tests.

---

## Phase 1: Seed Data (seed-prompts.json)

### 1a. Add skill definitions

Add 3 skill entries to `data/seed-prompts.json`:

```json
{
  "name": "skill.platform-knowledge",
  "template": "## Platform Context\n\nThe GenAI MLOps platform has 7 subsystems...\n- orchestration: n8n (port 5678) — webhooks, agents, workflows\n- inference: LiteLLM (port 4000) — LLM proxy, Ollama bridge\n- tracing: Langfuse (port 3000) — traces, scores, observations\n- experiments: MLflow (port 5050) — prompts, experiments, model registry\n- dataops: Airflow, OpenMetadata, pgvector, Neo4j\n- platform: MCP Gateway (port 8811), ArgoCD, GitLab CE\n- agenticops: (virtual) — agents are compositions, not services\n\nWebhook endpoints (all POST, auth via X-API-Key):\n/chat, /prompts, /eval, /traces, /sessions, /datasets, /mlflow/experiments, /mlflow/data, /openai/v1/chat/completions\n\nMCP servers: n8n-manager, n8n-knowledge, mlflow, gitlab, kubernetes, claude-code",
  "commit_message": "Skill: platform knowledge — subsystem topology and API reference",
  "tags": {
    "use_case": "skill",
    "type": "knowledge"
  }
}
```

Similarly for `skill.eval-methodology` and `skill.code-standards`.

Skills use the `skill.{name}` naming convention, `use_case: "skill"` tag.

### 1b. Enrich agent configs

Update existing agent `agent.config` tags to add `skills`, `description`, `tags` fields:

```json
{
  "mlops.SYSTEM": {
    "skills": ["platform-knowledge", "eval-methodology"],
    "description": "MLOps platform assistant — manages prompts, evaluations, traces, and experiments",
    "tags": ["domain:mlops", "mode:agent", "tier:platform"]
  },
  "devops.SYSTEM": {
    "skills": ["platform-knowledge"],
    "description": "DevOps assistant — monitors infrastructure health and experiment results",
    "tags": ["domain:devops", "mode:agent", "tier:platform"]
  }
  // ... etc for all 7 agents
}
```

**Files**: `data/seed-prompts.json`

---

## Phase 2: Chat Workflow — Config Validation + Skills Injection

### 2a. Config schema validation (FR-001)

In `chat.json` Prompt Resolver node, after parsing `agent.config` from MLflow, validate:

```javascript
// After: config = Object.assign({}, defaults, storedCfg);
// Validate schema
var VALID_KEYS = ['provider','model','temperature','top_p','num_ctx','max_iterations','mcp_tools','skills','description','tags'];
for (var k in config) {
  if (VALID_KEYS.indexOf(k) === -1) {
    console.warn('Unknown agent.config key: ' + k);
  }
}
if (config.skills && !Array.isArray(config.skills)) {
  config.skills = [];
}
if (config.tags && !Array.isArray(config.tags)) {
  config.tags = [];
}
```

Validation is soft (warns, doesn't error) to avoid breaking existing agents during rollout.

### 2b. Skills injection (FR-003)

In `chat.json` Prompt Resolver, after system prompt is loaded but before task enrichment:

```javascript
// Between step 1 (system prompt resolution) and step 2 (task enumeration):
var skillsLoaded = [];
if (config.skills && config.skills.length > 0) {
  var skillBlocks = [];
  for (var si = 0; si < config.skills.length; si++) {
    try {
      var skillResult = await getPrompt('skill.' + config.skills[si]);
      skillBlocks.push('### ' + config.skills[si] + '\n' + skillResult.template);
      skillsLoaded.push(config.skills[si]);
    } catch (skillErr) {
      console.warn('Skill not found: ' + config.skills[si]);
    }
  }
  if (skillBlocks.length > 0) {
    systemPrompt += '\n\n---\n\n## Skills\n\n' + skillBlocks.join('\n\n');
  }
}
```

Add `skills_loaded` to the output JSON so the Trace Logger and response include it.

### 2c. Update response metadata

In `chat.json` Trace Logger + Chat Response nodes, include `skills_loaded` array in output.

**Files**: `n8n-data/workflows/chat.json`

---

## Phase 3: Agent Catalog Workflow (FR-002)

### New workflow: `agents.json`

A webhook workflow at `/webhook/agents` with two actions:

**`list`**: Query MLflow for all `*.SYSTEM` models, parse configs, enumerate tasks per agent.

```
POST /webhook/agents
{ "action": "list" }
→ { "agents": [ { "name": "coder", "description": "...", "mode": "agent|chat", "mcp_tools": [...], "skills": [...], "tasks": [...], "tags": [...], "prompt_version": 3, "prompt_alias": "production" } ] }
```

**`get`**: Return single agent detail including full prompt template.

```
POST /webhook/agents
{ "action": "get", "name": "coder" }
→ { "name": "coder", "description": "...", "template": "...", "config": {...}, "tasks": [...], "skills": [...], "tags": [...], ... }
```

Architecture: 4 nodes — Webhook → Action Router (Code) → Response / Error Response.

The Action Router code node reuses the same MLflow query patterns from the Prompt Resolver but returns metadata instead of executing.

**Files**: `n8n-data/workflows/agents.json` (new)

---

## Phase 4: Import Script Update

Add `agents.json` to `scripts/n8n-import-all.sh`:
- Add to workflow count (9 → 10)
- agents.json is a webhook workflow → activate it
- No RESOLVE: placeholders needed

**Files**: `scripts/n8n-import-all.sh`

---

## Phase 5: Dashboard Extension (FR-005)

In `scripts/dashboard.py`, the MLOps poller already reads agents from MLflow. Extend the agent cards to display:
- Description (from config)
- Skills list (from config)
- Tags (from config)
- Task list (from MLflow task enumeration)

This enriches the existing agent panel in the Operations tab.

**Files**: `scripts/dashboard.py`

---

## Phase 6: Smoke Tests (FR-006)

Add 3 new smoke test cases to `scripts/smoke-test.sh`:

```bash
# Agent catalog list
check_status "agents list" "$BASE/agents" POST '{"action":"list"}' 200

# Agent catalog get
check_status "agents get coder" "$BASE/agents" POST '{"action":"get","name":"coder"}' 200

# Chat with skills metadata
# (verify skills_loaded appears in response — check via jq)
```

**Files**: `scripts/smoke-test.sh`

---

## Task Order

| # | Task | Phase | Test First? | Dependencies |
|---|------|-------|-------------|--------------|
| 1 | Add skill definitions to seed-prompts.json | 1a | No (data) | — |
| 2 | Enrich agent configs with skills/description/tags | 1b | No (data) | — |
| 3 | Add config validation to Prompt Resolver | 2a | No (soft validation) | — |
| 4 | Add skills injection to Prompt Resolver | 2b | No (workflow JSON) | 1, 3 |
| 5 | Update response metadata (skills_loaded) | 2c | No (workflow JSON) | 4 |
| 6 | Create agents.json workflow | 3 | No (workflow JSON) | — |
| 7 | Update import script for agents.json | 4 | No (script) | 6 |
| 8 | Extend dashboard agent panel | 5 | No (dashboard) | 2 |
| 9 | Add smoke tests | 6 | Yes (TDD for tests) | 6 |
| 10 | Re-seed prompts + re-import workflows + smoke test | — | — | All |

## Risks

- **MLflow latency**: Skills injection adds N additional MLflow API calls per chat request (one per skill). Mitigate with short timeouts (5s) and parallel fetches.
- **Prompt size**: Injecting multiple skills could exceed model context window. Mitigate with `num_ctx` config and skill content brevity.
- **Backward compatibility**: Agents without `skills` field in config continue to work unchanged (skills defaults to empty array).

## Verification

After all changes:
1. `task seed-prompts` — re-seed all prompts including skills
2. `task workflow:import` — re-import all workflows including agents.json
3. `task qa:smoke` — all tests pass including 3 new agent catalog tests
4. Manual: `POST /webhook/agents {"action":"list"}` returns 7 agents with configs
5. Manual: `POST /webhook/chat {"agent_name":"mlops","message":"hello"}` response includes `skills_loaded`
6. Dashboard: agent panel shows skills, descriptions, tags

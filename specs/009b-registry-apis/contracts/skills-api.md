# API Contract: Skills Query API

Skills are a view on the prompts registry (MLflow), not a separate store. This endpoint filters prompts by `use_case=skill` and provides skill-specific operations. Skill CRUD uses `/webhook/prompts`.

## Endpoint

```
POST /webhook/skills
Content-Type: application/json
X-API-Key: {WEBHOOK_API_KEY}
```

---

## Actions

### `list` — List all skills

**Request:**
```json
{ "action": "list" }
```

**Response:**
```json
{
  "skills": [
    {
      "name": "coder.review",
      "domain": "coder",
      "description": "Structured code review with severity-tagged issues and verdict",
      "required_mcp_servers": [],
      "output_format": "structured",
      "equipped_by": ["coder", "mlops", "devops"],
      "prompt_version": "1"
    },
    {
      "name": "mlops.evaluate",
      "domain": "mlops",
      "description": "Run and summarize prompt evaluations",
      "required_mcp_servers": ["mlflow"],
      "output_format": "structured",
      "equipped_by": ["mlops", "analyst"],
      "prompt_version": "1"
    }
  ],
  "count": 6
}
```

### `get` — Get skill detail

**Request:**
```json
{ "action": "get", "name": "coder.review" }
```

**Response:**
```json
{
  "name": "coder.review",
  "domain": "coder",
  "description": "Structured code review with severity-tagged issues and verdict",
  "required_mcp_servers": [],
  "output_format": "structured",
  "equipped_by": ["coder", "mlops", "devops"],
  "prompt_version": "1",
  "prompt_template": "## Code Review Task\n\nReview the provided code..."
}
```

### `list_by_agent` — Skills equipped by an agent

**Request:**
```json
{ "action": "list_by_agent", "agent": "coder" }
```

**Response:**
```json
{
  "agent": "coder",
  "skills": [
    {
      "name": "coder.review",
      "description": "Structured code review with severity-tagged issues and verdict"
    },
    {
      "name": "coder.debug",
      "description": "Root cause analysis with structured fix"
    }
  ],
  "count": 2
}
```

### `list_agents` — Agents that have a skill equipped

**Request:**
```json
{ "action": "list_agents", "skill": "coder.review" }
```

**Response:**
```json
{
  "skill": "coder.review",
  "agents": ["coder", "mlops", "devops"],
  "count": 3
}
```

### `equip` — Add skill to agent

**Request:**
```json
{ "action": "equip", "agent": "writer", "skill": "coder.debug" }
```

**Response:**
```json
{
  "agent": "writer",
  "skill": "coder.debug",
  "equipped": true,
  "agent_skills": ["writer.email", "writer.rewrite", "coder.debug"],
  "warnings": []
}
```

### `unequip` — Remove skill from agent

**Request:**
```json
{ "action": "unequip", "agent": "writer", "skill": "coder.debug" }
```

**Response:**
```json
{
  "agent": "writer",
  "skill": "coder.debug",
  "unequipped": true,
  "agent_skills": ["writer.email", "writer.rewrite"]
}
```

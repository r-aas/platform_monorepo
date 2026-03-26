---
name: agent-management
version: 1.0.0
description: Create, update, delete, and list agents
tags:
- management
- agents
operations:
- list_agents
- get_agent
- create_agent
- update_agent
- delete_agent
---

When managing agents:
- List existing agents before creating duplicates
- Verify skill references exist before assigning to agents
- Confirm destructive actions (delete) before executing
- Report the full agent definition after creation or update


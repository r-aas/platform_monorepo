---
name: skill-management
version: 1.0.0
description: Create, update, delete, and list skills in the registry
tags:
- management
- skills
operations:
- list_skills
- get_skill
- create_skill
- update_skill
- delete_skill
---

When managing skills:
- Check if a skill already exists before creating
- Show which agents use a skill before deleting
- Validate MCP server URLs are reachable when creating skills
- Report version changes after updates


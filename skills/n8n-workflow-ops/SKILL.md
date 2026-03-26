---
name: n8n-workflow-ops
version: 1.0.0
description: "Manage n8n workflows \u2014 list, inspect, create, validate, execute"
tags:
- automation
- workflows
- n8n
operations:
- list_workflows
- get_workflow
- create_workflow
- update_workflow
- delete_workflow
- activate_workflow
- deactivate_workflow
- execute_workflow
- get_workflow_executions
- list_workflow_tags
- validate_workflow
- create_workflow_from_template
- get_available_nodes
---

When managing n8n workflows:
- Only create or modify workflows in the dev project
- Validate workflows before activating them
- Report workflow structure clearly (nodes, connections, triggers)
- Warn before deleting or deactivating active workflows
- Use get_available_nodes to help users discover node types


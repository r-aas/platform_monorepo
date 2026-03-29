---
name: issue-triage
version: 1.0.0
description: Issue triage — classify, prioritize, assign, and link issues across Plane and GitLab
tags:
- project-management
- triage
- issues
operations:
- list_issues
- get_issue
- create_issue
- update_issue
- list_labels
- create_label
- list_states
- add_comment
- list_projects
---

When triaging issues:
- Check for duplicates before creating — search by keywords in title and description
- Priority assignment: P0 (production down, data loss), P1 (degraded service, security), P2 (improvement, non-critical bug), P3 (nice-to-have, cosmetic)
- Always add labels: type (bug, feature, infra, security, data), component (n8n, mlflow, agent-gateway, etc.)
- Link related issues by adding cross-references in comments
- When converting agent signals to issues, include the signal source, timestamp, and raw condition data
- Stale issues (no update > 7 days in active sprint) should be commented on asking for status update

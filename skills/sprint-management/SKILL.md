---
name: sprint-management
version: 1.0.0
description: Sprint cycle management — create cycles, assign issues, track burndown, run retrospectives
tags:
- project-management
- sprints
- cycles
operations:
- list_cycles
- add_issue_to_cycle
- list_issues
- update_issue
- list_states
- add_comment
---

When managing sprints:
- Cycles should be 1-2 weeks duration — shorter for ops work, longer for feature development
- Only add issues to active sprint if they're triaged (have priority, labels, and assignee)
- Track velocity as issues completed per sprint, not story points — keep it simple
- Generate burndown updates at sprint midpoint and end
- Retrospective should cover: what shipped, what slipped, what blocked, and what to improve
- Move incomplete issues to next sprint with a comment explaining the carryover reason

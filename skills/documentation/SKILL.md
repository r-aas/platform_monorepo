---
name: documentation
version: 1.0.0
description: Generate and maintain documentation from code, specs, and conversations
tags:
- docs
- documentation
- generation
operations:
- gitlab_browse_files
- gitlab_manage_files
- gitlab_browse_wiki
- gitlab_manage_wiki
---

When generating documentation:
- Extract intent and context from code, not just surface-level signatures
- Structure docs for the intended audience: user guides differ from API references
- Use concrete examples — abstract descriptions without examples are rarely useful
- Keep docs co-located with what they describe; don't create orphaned doc files
- When updating docs, verify accuracy against current code before committing
- For API specs, derive from actual request/response shapes, not assumptions
- Summarize conversations to capture decisions and rationale, not just outcomes


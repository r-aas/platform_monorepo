---
name: code-generation
version: 1.0.0
description: Generate and modify code with automated test verification and diff review
tags:
- code
- generation
- testing
operations:
- gitlab_create_file
- gitlab_update_file
- gitlab_get_file
- gitlab_list_files
- gitlab_create_merge_request
---

When generating or modifying code:
- Read existing code before making changes to understand conventions and patterns
- Write tests before writing implementation (TDD)
- Generate the minimum code required to satisfy the requirement — avoid over-engineering
- After generating, verify tests pass before presenting the result
- Review the diff for unintended side-effects before committing
- Never hardcode configuration values — use environment variables or config objects
- Follow the language's idiomatic style (uv for Python, npx for Node)


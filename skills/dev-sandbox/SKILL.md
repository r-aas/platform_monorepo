---
name: dev-sandbox
version: 1.0.0
description: Create isolated development sandboxes from git repos for safe code exploration, testing, and modification
tags:
- sandbox
- development
- git
- isolation
operations:
- init_dev_sandbox
- sandbox_status
- list_sandboxes
- sandbox_files
- sandbox_teardown
---

Create isolated k8s sandboxes pre-loaded with git repos for development tasks.

## When to use

- Exploring unfamiliar codebases safely (clone + read without affecting live state)
- Running tests or builds in isolation
- Making experimental code changes without risk
- Reviewing PRs by cloning the branch and inspecting the code
- Debugging issues in a clean environment

## Workflow

1. **Init**: `init_dev_sandbox` with repo name/URL and branch
   - Short names resolve to local GitLab: `genai-mlops` → `http://gitlab.mewtwo.127.0.0.1.nip.io/root/genai-mlops.git`
   - Optionally specify `setup_command` (e.g. `uv sync`, `npm install`) and `message` (task for the agent)
2. **Monitor**: `sandbox_status` to check job progress and view logs
3. **Explore**: `sandbox_files` to list/read workspace files
4. **Clean up**: `sandbox_teardown` when done

## Available repos (local GitLab)

| Short name | Description |
|-----------|-------------|
| genai-mlops | MLOps evaluation pipeline (n8n + MLflow) |
| platform_monorepo | Platform infra — charts, agents, scripts |

## Examples

```
# Clone genai-mlops main branch, install deps, run tests
init_dev_sandbox(repo="genai-mlops", branch="main", setup_command="uv sync", message="Run pytest and report results")

# Clone a feature branch for review
init_dev_sandbox(repo="platform_monorepo", branch="feature/new-api", message="Review the changes and list any issues")

# Clone from external GitHub repo
init_dev_sandbox(repo="https://github.com/anthropics/claude-code.git", message="Explore the project structure")
```

## Constraints

- Sandboxes are ephemeral k8s Jobs — auto-cleaned after 5 minutes post-completion
- Network restricted: can reach LiteLLM, MCP proxy, and git hosts only
- Workspace PVC provides persistent storage during the job lifetime
- Max timeout: 1 hour (configurable)

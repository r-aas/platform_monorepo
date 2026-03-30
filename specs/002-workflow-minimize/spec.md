<!-- status: shipped -->
<!-- pr: none (incremental cleanup) -->
# 002: Workflow Minimization + Prompt Rename

## Problem

16 workflow files existed but only 9 are active entry points. The other 7 (3 sub-workflows + 4 tool workflows) are dead code — never called by any main workflow. All business logic was inlined in main workflow Code nodes during v3.1-v3.2 development, making sub/tool workflows obsolete.

The import script carried dead complexity: sub/tool directory imports, a deactivation loop for 7 workflows, and RESOLVE placeholder resolution (no placeholders exist in any workflow).

Agent prompts used `agent:mlops` naming in seed-prompts.json but the Prompt Resolver in chat.json expects `{agentName}.SYSTEM` format. These were misaligned.

## Requirements

### FR-001: Remove dead workflow files
Delete all sub-workflow and tool workflow JSON files and their directories.

**Acceptance**: `ls n8n-data/workflows/` shows exactly 9 JSON files with zero subdirectories.

### FR-002: Simplify import script
Remove dead code from `scripts/n8n-import-all.sh`:
- Sub/tool directory import blocks
- Step 2b deactivation loop
- Step 4 RESOLVE placeholder resolution

**Acceptance**: Script has 5 steps (import, activate, restart, Ollama cred, webhook auth cred). Bash syntax validates. No references to `_subworkflows`, `_tools`, or `RESOLVE`.

### FR-003: Rename agent prompts
Rename 7 agent prompt names from `agent:{name}` to `{name}.SYSTEM` format:

| Current | New |
|---------|-----|
| `agent:mlops` | `mlops.SYSTEM` |
| `agent:mcp` | `mcp.SYSTEM` |
| `agent:devops` | `devops.SYSTEM` |
| `agent:analyst` | `analyst.SYSTEM` |
| `agent:coder` | `coder.SYSTEM` |
| `agent:writer` | `writer.SYSTEM` |
| `agent:reasoner` | `reasoner.SYSTEM` |

Non-agent prompts unchanged.

**Acceptance**: `data/seed-prompts.json` contains `*.SYSTEM` names. After seed + list, Prompt Resolver in chat.json resolves `getPrompt(agentName + '.SYSTEM')` correctly.

### FR-004: Update tests
Remove deleted workflow references from `tests/test_workflow_json.py`:
- Remove `DEACTIVATED_IDS` set
- Remove `test_sub_workflows_have_no_trigger` test
- Remove `TestResolveplaceholders` class
- Remove unused `re` import

**Acceptance**: `uv run pytest tests/test_workflow_json.py` passes with only 9 workflow parametrizations.

## Files Changed

| File | Action |
|------|--------|
| `n8n-data/workflows/_subworkflows/*` | DELETE 3 files + dir |
| `n8n-data/workflows/_tools/*` | DELETE 4 files + dir |
| `n8n-data/workflows/_templates/` | DELETE empty dir |
| `scripts/n8n-import-all.sh` | EDIT — 449→325 lines (-124) |
| `data/seed-prompts.json` | EDIT — rename 7 prompt names |
| `tests/test_workflow_json.py` | EDIT — remove dead test classes |

## Verification

| Check | Expected |
|-------|----------|
| `ls n8n-data/workflows/` | 9 JSON files, no subdirs |
| `bash -n scripts/n8n-import-all.sh` | Syntax OK |
| `uv run pytest tests/test_workflow_json.py` | 63 passed |
| `task workflows:import` | Clean 5-step import |
| Prompt seed + list | Shows `mlops.SYSTEM`, `coder.SYSTEM`, etc. |
| `task qa:smoke` | All pass |

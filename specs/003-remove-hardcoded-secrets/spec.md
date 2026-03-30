<!-- status: shipped -->
<!-- pr: #1 -->
<!-- spec-check-skip: contracts — internal refactor, no API surface change -->
# 003: Remove Hardcoded Secret Fallbacks from Workflow JSON

## Problem

`chat.json` Code nodes contain a hardcoded LiteLLM API key as fallback:
```javascript
const INFERENCE_KEY = process.env.LITELLM_API_KEY || 'sk-EtjgxpqkGEKRnIxBhxOYrTdNXd62aUpq';
```

This key is committed to git — a leaked secret. The env var injection already works via docker-compose entrypoint (line 273), so the fallback is never needed at runtime. Replace with empty string fallback.

## Requirements

### FR-001: Remove hardcoded LiteLLM key from Prompt Resolver
Replace `|| 'sk-EtjgxpqkGEKRnIxBhxOYrTdNXd62aUpq'` with `|| ''` in Prompt Resolver Code node.

### FR-002: Remove hardcoded LiteLLM key from Chat Handler
Same replacement in Chat Handler Code node.

### FR-003: Remove hardcoded webhook key fallback
Replace `|| 'dev-webhook-key-genai-mlops'` with `|| ''` in Prompt Resolver. The env var is injected at runtime; committed JSON should not contain default keys.

**Acceptance**: `grep -r 'sk-Etjg' n8n-data/` returns nothing. `grep -r 'dev-webhook-key' n8n-data/` returns nothing. Workflow JSON contains only `|| ''` fallbacks for secrets.

## Files Changed

| File | Action |
|------|--------|
| `n8n-data/workflows/chat.json` | EDIT — replace 3 hardcoded secret fallbacks with `''` |
| `specs/003-remove-hardcoded-secrets/spec.md` | CREATE |

## Verification

| Check | Expected |
|-------|----------|
| `grep -r 'sk-Etjg' n8n-data/` | No matches |
| `grep -r 'dev-webhook-key' n8n-data/` | No matches |
| `uv run pytest tests/test_workflow_json.py` | All pass |
| `bash -n scripts/n8n-import-all.sh` | Syntax OK |

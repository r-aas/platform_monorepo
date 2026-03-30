<!-- status: shipped -->
<!-- pr: #8 -->
# Spec 010: Global Configuration

## Problem

Configuration is scattered across 5+ files with no single source of truth. The same concepts (service endpoints, ports, model lists) are declared in multiple places that must be kept in sync by hand:

| Concept | `.env.example` | `litellm/config.yaml` | `mcp-servers/catalog.yaml` | `docker-compose.yml` | `smoke-test.sh` |
|---------|:-:|:-:|:-:|:-:|:-:|
| Service ports | ✓ | | | ✓ | ✓ (hardcoded fallbacks) |
| Model list | ✓ (`INFERENCE_ALLOWED_MODELS`) | ✓ (`model_list`) | | | |
| Service URLs | ✓ (inter-container) | | ✓ (hardcoded) | ✓ (healthchecks) | ✓ (hardcoded `localhost`) |
| Ollama host | | ✓ (`api_base`) | | ✓ (env passthrough) | |

Adding a model requires editing `.env.example` AND `litellm/config.yaml`. Changing a port requires editing `.env.example` AND updating hardcoded references in scripts. There is no validation that these files agree.

## Requirements

### FR-001: `config.yaml` as Single Source of Truth

A new `config.yaml` in the repo root declares all stack configuration in one place. Structure:

```yaml
# config.yaml — GenAI MLOps Stack Configuration
# All other config files are GENERATED from this file.
# Edit here, run `task config:generate` to propagate.

stack:
  name: genai-mlops
  timezone: America/Denver

services:
  n8n:
    version: "1.123.21"
    port: 5678
    health: /healthz
    postgres: { version: "16.8", user: n8n, db: n8n }

  mlflow:
    version: "v3.10.0"
    port: 5050
    health: /health
    postgres: { version: "16.8", user: mlflow, db: mlflow }

  litellm:
    version: main-latest
    port: 4000
    health: /health/liveliness
    settings:
      callbacks: [mlflow, langfuse]
      drop_params: true
      request_timeout: 120

  langfuse:
    version: "3"
    port: 3100
    health: /api/public/health
    postgres: { version: "16.8", user: langfuse, db: langfuse }

  minio:
    version: "RELEASE.2025-04-22T22-12-26Z"
    mc_version: "RELEASE.2025-05-21T01-59-54Z"
    port: 9000
    health: /minio/health/live
    bucket: mlflow
    region: us-east-1

  pgvector:
    version: pg16
    user: vectors
    db: vectors

  streaming_proxy:
    port: 4010

  mcp_gateway:
    port: 8811
    health: /health

inference:
  provider: litellm                    # litellm | ollama-direct
  ollama_host: host.docker.internal:11434
  default_model: "qwen2.5:14b"
  models:
    - name: "qwen2.5:14b"
    - name: "qwen2.5:7b"
    - name: "qwen3:32b"
    - name: "qwen3:30b"
    - name: "mistral:7b-instruct"
    - name: "llama3.2:latest"
    - name: "nomic-embed-text:latest"
      type: embedding

webhook:
  api_key: dev-webhook-key-genai-mlops   # override in .env for production

session:
  max_messages: 50

drift:
  latency_max_ms: 10000
  error_rate_max: 0.1
  token_budget_daily: 100000
```

### FR-002: Config Generator Script

A script `scripts/config-gen.py` reads `config.yaml` and generates:

| Output | Generated From | Notes |
|--------|---------------|-------|
| `.env.generated` | All sections | Flat KEY=VALUE, same shape as current `.env.example` |
| `litellm/config.yaml` | `inference.models` + `services.litellm.settings` | Model routing + settings |
| Validation report | All sections | Prints warnings for inconsistencies |

The script does NOT generate `docker-compose.yml` or `mcp-servers/catalog.yaml` — those reference env vars from `.env` which are already generated. Keeping compose and catalog as hand-authored files avoids over-abstraction.

### FR-003: `.env.example` Becomes `.env.generated`

The current `.env.example` pattern changes:

- `config.yaml` → `scripts/config-gen.py` → `.env.generated` (committed, replaces `.env.example`)
- `.env` (gitignored) overrides `.env.generated` for local secrets
- `.env.local` (gitignored) for machine-specific overrides

Taskfile dotenv load order (highest → lowest):
```
.env.local → .env → .env.generated → ~/work/envs/global.env
```

### FR-004: LiteLLM Config Generation

The generator produces `litellm/config.yaml` from `config.yaml`:

- Each entry in `inference.models` becomes a `model_list` entry
- `api_base` derived from `inference.ollama_host` (prefixed `http://`)
- `litellm_settings` from `services.litellm.settings`
- `master_key` always reads from env: `os.environ/LITELLM_MASTER_KEY`

This eliminates the manual sync between `INFERENCE_ALLOWED_MODELS` and `litellm/config.yaml`.

### FR-005: Validation

`scripts/config-gen.py --validate` (no generation, exit 0/1):

| Check | Logic |
|-------|-------|
| Required fields | All services have `version` and `port` (where applicable) |
| Port conflicts | No two services share a port |
| Model consistency | `inference.default_model` exists in `inference.models` |
| Health endpoints | Every service with a `port` has a `health` path |
| Schema | YAML structure matches expected schema (no typos in keys) |

### FR-006: Taskfile Integration

New tasks in `taskfiles/quality.yml` (or new `taskfiles/config.yml`):

```
config:generate   — Run config-gen.py, update .env.generated + litellm/config.yaml
config:validate   — Run config-gen.py --validate, exit 1 on errors
config:diff       — Show what would change without writing
```

`task setup` calls `config:generate` as a dependency.

### FR-007: Smoke Test Uses Config

`scripts/smoke-test.sh` reads service URLs and ports from `.env.generated` instead of hardcoding `localhost:XXXX` fallbacks. The `BASE` variable construction becomes:

```bash
# Current (hardcoded):
BASE="${N8N_BASE_URL:-http://localhost:5678/webhook}"
LITELLM_URL="${LITELLM_URL:-http://localhost:4000}"

# New (from .env.generated, still overridable):
BASE="${N8N_BASE_URL:-http://localhost:${N8N_PORT:-5678}/webhook}"
LITELLM_URL="${LITELLM_URL:-http://localhost:${LITELLM_PORT:-4000}}"
```

This way, changing a port in `config.yaml` propagates to smoke tests automatically.

### NFR-001: No Runtime Dependency

`config.yaml` is a build-time / setup-time artifact. No service reads `config.yaml` at runtime — they read env vars from `.env.generated` (via compose `env_file`) or their own generated configs. If `config-gen.py` is never run, the stack still works with manually maintained `.env` files.

### NFR-002: Idempotent Generation

Running `config:generate` twice produces identical output. Generated files include a header comment:

```
# AUTO-GENERATED from config.yaml — do not edit directly.
# Run: task config:generate
```

### NFR-003: Minimal Dependencies

`scripts/config-gen.py` uses only Python stdlib + PyYAML (already a transitive dep via MLflow). No Jinja2, no Pydantic, no schema library. Keep it simple — this is a ~150-line script, not a framework.

## Non-Goals

- Generating `docker-compose.yml` from config (too complex, too many edge cases)
- Generating `mcp-servers/catalog.yaml` from config (catalog has its own structure with volumes, secrets)
- Environment-specific config profiles (dev/staging/prod) — `.env` override is sufficient
- Config UI or API — this is a developer tool, not a service
- Encrypting secrets in config.yaml — secrets stay in `.env` / `secrets/`

## Files Changed

| File | Action |
|------|--------|
| `config.yaml` | NEW — single source of truth |
| `scripts/config-gen.py` | NEW — generator + validator (~150 lines) |
| `.env.example` | DELETE — replaced by `.env.generated` |
| `.env.generated` | NEW (committed) — generated flat env file |
| `litellm/config.yaml` | EDIT — now auto-generated (header comment added) |
| `taskfiles/quality.yml` | EDIT — add `config:validate` task |
| `Taskfile.yml` | EDIT — add `config:generate`, `config:diff` tasks; `setup` depends on `config:generate` |
| `scripts/smoke-test.sh` | EDIT — use `${N8N_PORT}` / `${LITELLM_PORT}` vars instead of hardcoded ports |
| `.gitignore` | EDIT — ensure `.env.generated` is NOT ignored (it's committed) |
| `.gitlab-ci.yml` | EDIT — add `config-validate` job in validate stage |
| `tests/test_config.py` | NEW — unit tests for config-gen.py |

## Verification

| Check | FR | Expected |
|-------|-----|----------|
| `python scripts/config-gen.py --validate` | FR-005 | Exit 0 on valid config.yaml |
| `python scripts/config-gen.py --validate` with duplicate port | FR-005 | Exit 1 with error message |
| `python scripts/config-gen.py --validate` with missing default model | FR-005 | Exit 1 with error message |
| `task config:generate && diff .env.generated .env.generated` | NFR-002 | Idempotent — no diff on second run |
| Generated `.env.generated` has all keys from old `.env.example` | FR-003 | `diff <(grep -oE '^[A-Z_]+' .env.example) <(grep -oE '^[A-Z_]+' .env.generated)` is empty |
| Generated `litellm/config.yaml` has all models from config.yaml | FR-004 | Model count matches `inference.models` length |
| `litellm/config.yaml` header contains "AUTO-GENERATED" | NFR-002 | `head -1 litellm/config.yaml` contains comment |
| `task config:validate` | FR-006 | Runs validation, exit 0 |
| `task config:diff` | FR-006 | Shows diff without writing |
| Smoke test with non-default port | FR-007 | Uses `N8N_PORT` from env, not hardcoded 5678 |
| `config-gen.py` has no deps beyond stdlib + PyYAML | NFR-003 | `grep import scripts/config-gen.py` shows only yaml, os, sys, pathlib |
| Stack boots without running config:generate | NFR-001 | Manual `.env` still works |
| `uv run pytest tests/test_config.py` | All | All pass |
| `bash scripts/spec-check.sh` | All | Spec 010 passes all checks |

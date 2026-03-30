# Environment Strategy

How to run the GenAI MLOps stack across development, staging, and production — same workflows, same prompts, different infrastructure.

## Core Principle

**Nothing changes between environments except env vars and secrets.** The n8n workflows, MLflow prompt registry, and evaluation pipelines are identical everywhere. Provider swaps happen through 3 environment variables:

```env
INFERENCE_BASE_URL=...
INFERENCE_DEFAULT_MODEL=...
INFERENCE_ALLOWED_MODELS=...
```

## Development

Your laptop. Full stack in Docker Compose, local inference via Ollama.

```bash
task setup       # sync deps, create .env, generate secrets
task dev         # start n8n + MLflow + Postgres + MinIO
task health      # verify all services
```

| Component | Where | URL |
|-----------|-------|-----|
| n8n | Docker Compose | http://localhost:5678 |
| MLflow | Docker Compose | http://localhost:5050 |
| Postgres (x2) | Docker Compose | internal |
| MinIO | Docker Compose | http://localhost:9001 |
| Ollama | Host process (GPU) | http://localhost:11434 |

**Provider config:**
```env
INFERENCE_BASE_URL=http://host.docker.internal:11434/v1
INFERENCE_DEFAULT_MODEL=qwen2.5:14b
```

**Workflow:**
1. Edit prompts via API or seed script
2. Evaluate with test cases → results in MLflow
3. Optimize with GEPA → new version on `staging` alias
4. Benchmark → verify quality metrics
5. Promote to `production` alias when satisfied

## Staging

Same Docker Compose, different `.env` pointing at the staging provider. Could be a shared Ollama instance, a staging Bedrock endpoint, or any OpenAI-compatible API.

**What changes from dev:**
- `INFERENCE_BASE_URL` → staging provider endpoint
- `INFERENCE_DEFAULT_MODEL` → staging model
- Secrets → staging credentials (if provider requires auth)

**What stays the same:**
- n8n workflow JSONs (identical)
- MLflow prompt registry (same schema, different instance)
- Evaluation pipeline and benchmark scripts
- All API endpoints and behavior

**Provider config (example — Bedrock staging):**
```env
INFERENCE_BASE_URL=https://staging-api.corp.example.com/v1
INFERENCE_DEFAULT_MODEL=anthropic.claude-3-haiku-20240307-v1:0
INFERENCE_ALLOWED_MODELS=anthropic.claude-3-haiku-20240307-v1:0,anthropic.claude-3-sonnet-20240229-v1:0
```

**Workflow:**
1. Deploy same Docker Compose with staging `.env`
2. Seed prompts (idempotent — safe to re-run)
3. Run full benchmark suite against staging provider
4. Compare metrics: latency, token usage, quality scores
5. Validate prompts work correctly with the target model

## Production

The platform team's infrastructure. n8n workflows imported via CLI or API, MLflow on shared infra (or managed service), provider is the internal API in front of Bedrock (or whatever production uses).

**What the platform team provides:**
- n8n instance (managed, access-controlled)
- Database backend (Postgres or equivalent)
- Artifact storage (S3-compatible)
- Provider endpoint (internal API → Bedrock)

**What you provide:**
- n8n workflow JSON files (from `n8n-data/workflows/`)
- MLflow prompt definitions (via seed script or API)
- Environment variable specification
- Benchmark suite for validation

**Importing workflows to production n8n:**
```bash
# Export from dev (already in git)
ls n8n-data/workflows/*.json

# Import via n8n CLI on the production instance
n8n import:workflow --input=openai-compat-v1.json
n8n import:workflow --input=prompt-crud-v1.json
n8n import:workflow --input=prompt-eval-v1.json
```

**Production provider config:**
```env
INFERENCE_BASE_URL=https://internal-api.corp.example.com/v1
INFERENCE_DEFAULT_MODEL=anthropic.claude-3-haiku-20240307-v1:0
INFERENCE_ALLOWED_MODELS=anthropic.claude-3-haiku-20240307-v1:0,anthropic.claude-3-sonnet-20240229-v1:0
```

## Promotion Flow

Prompts move through environments using MLflow aliases. The same versioned prompt exists in the registry — only the alias pointer changes.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Development  │────►│   Staging    │────►│ Production   │
│              │     │              │     │              │
│ task optimize│     │ task benchmark│    │ POST /prompts│
│ → staging    │     │ → verify     │     │ {promote}    │
│   alias      │     │   quality    │     │ → production │
│              │     │              │     │   alias      │
└─────────────┘     └─────────────┘     └─────────────┘
```

### Step by Step

**1. Develop and optimize (dev environment)**
```bash
# Optimize a prompt — creates new version, sets staging alias
task optimize -- summarizer

# Check what version is on staging
curl -s localhost:5678/webhook/prompts \
  -d '{"action":"get","name":"summarizer","alias":"staging"}' | jq .version
```

**2. Validate on staging provider**
```bash
# Run benchmarks against staging
task benchmark

# Compare staging vs current production
curl -s localhost:5678/webhook/prompts \
  -d '{"action":"get","name":"summarizer","alias":"production"}' | jq .version
```

**3. Promote to production**
```bash
# Promote specific version to production alias
curl -s localhost:5678/webhook/prompts \
  -H 'Content-Type: application/json' \
  -d '{"action":"promote","name":"summarizer","version":3}'

# Verify
curl -s localhost:5678/webhook/prompts \
  -d '{"action":"get","name":"summarizer","alias":"production"}' | jq .version
```

**4. Rollback if needed**
```bash
# Re-promote the previous version
curl -s localhost:5678/webhook/prompts \
  -H 'Content-Type: application/json' \
  -d '{"action":"promote","name":"summarizer","version":2}'
```

## MLflow Across Environments

Each environment runs its own MLflow instance, but prompt definitions and versions are portable.

| Concern | Development | Staging | Production |
|---------|-------------|---------|------------|
| MLflow backend | Docker Compose Postgres | Shared Postgres / RDS | Managed service / RDS |
| Artifact store | MinIO (local) | S3 bucket (staging) | S3 bucket (prod) |
| Prompt seeding | `task seed-prompts` | Same script, different endpoint | Same script, different endpoint |
| Experiment data | Local only | Shared team access | Auditable, retained |

## Security Considerations

| Concern | How it's handled |
|---------|-----------------|
| Secrets | Docker secrets (file-based), never in `.env` or env vars |
| Provider auth | API keys in secrets, referenced by n8n credentials |
| Network | n8n → provider is the only external call |
| Prompt data | Stored in MLflow (Postgres + MinIO/S3), not in n8n |
| Audit trail | MLflow experiment tracking logs every eval run |

## CI/CD Integration

The GitHub Actions pipeline validates everything that doesn't require a running stack:

```yaml
# Runs on every push/PR
- Docker Compose syntax validation
- Dockerfile linting (hadolint)
- Python linting (ruff)
- Unit tests (pytest — no stack required)
```

**Extending for staging/production deploys:**
```yaml
# Add to CI for staging
- Deploy Docker Compose to staging host
- Run seed-prompts against staging MLflow
- Run benchmark suite
- Gate on quality thresholds

# Add to CI for production
- Import workflow JSONs to production n8n
- Run smoke tests against production endpoints
- Promote prompts via API
- Notify team
```

## Quick Reference

| Task | Command |
|------|---------|
| Start dev stack | `task dev` |
| Seed prompts | `task seed-prompts` |
| Run benchmarks | `task benchmark` |
| Optimize prompt | `task optimize -- NAME` |
| Smoke test endpoints | `task test-smoke` |
| Unit tests (no stack) | `task test-unit` |
| Check staging version | `curl ... {"action":"get","alias":"staging"}` |
| Promote to production | `curl ... {"action":"promote","version":N}` |
| Rollback | `curl ... {"action":"promote","version":PREV}` |
| Full health check | `task doctor` |

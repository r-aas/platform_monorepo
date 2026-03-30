# Data Model: Webhook Authentication Middleware

**Feature**: 001-webhook-auth | **Date**: 2026-03-11

## Entities

### API Key

A shared secret string used for symmetric authentication of webhook requests.

| Attribute | Type | Source | Notes |
|-----------|------|--------|-------|
| Value | String | `WEBHOOK_API_KEY` env var | Stripped of whitespace; empty = open mode |
| Header Name | String (fixed) | `X-API-Key` | Always this header; not configurable |
| Scope | Global | All `/webhook/*` endpoints | Single key per deployment |

**Lifecycle**:
- Defined in `.env.example` with default value
- Read by import script from environment at import time
- Stored in n8n as encrypted `httpHeaderAuth` credential
- Referenced by all 12 webhook trigger nodes
- Read by Code nodes via hardcoded fallback for internal calls

**States**:

```
WEBHOOK_API_KEY unset/empty/whitespace
  → Open mode: no credential created, webhook nodes stay auth=none

WEBHOOK_API_KEY set to non-empty value
  → Auth mode: credential created, webhook nodes patched to headerAuth
```

### n8n Credential (httpHeaderAuth)

An n8n-managed credential record that stores the header auth configuration.

| Attribute | Type | Value |
|-----------|------|-------|
| name | String | `"Webhook API Key"` |
| type | String | `"httpHeaderAuth"` |
| data.name | String | `"X-API-Key"` |
| data.value | String | `<WEBHOOK_API_KEY value>` |

**Storage**: n8n PostgreSQL `credentials_entity` table (encrypted at rest by n8n).

**Created by**: Import script Step 6 via `POST /api/v1/credentials`.

### Webhook Trigger Node (modified)

Each of the 12 webhook nodes gets two field changes when auth is enabled:

| Field | Before | After (auth mode) |
|-------|--------|-------------------|
| `parameters.authentication` | `"none"` | `"headerAuth"` |
| `credentials.httpHeaderAuth.id` | (absent) | `"<credential-id>"` |

**Important**: Workflow JSON files in git always have `authentication: "none"`. The import script dynamically patches nodes after import. This keeps the source files clean and makes open mode the default for fresh clones.

## Relationships

```
.env.example
  └── WEBHOOK_API_KEY ──→ Import Script
                            ├── Creates: httpHeaderAuth credential (n8n DB)
                            └── Patches: 12 webhook nodes → reference credential

httpHeaderAuth credential
  └── Referenced by: all 12 webhook trigger nodes (via credentials.httpHeaderAuth.id)

Code nodes (internal calls)
  └── Read: WEBHOOK_API_KEY via hardcoded fallback
  └── Send: X-API-Key header in axios requests to other webhook endpoints
```

## Validation Rules

| Rule | Enforcement |
|------|-------------|
| Empty/whitespace key = open mode | Import script: `webhook_key.strip()` check |
| Special characters in key allowed | httpHeaderAuth credential handles arbitrary string values |
| Key never logged or exposed | n8n encrypts credentials; FR-008 |
| Auth applied to all HTTP methods | n8n native: headerAuth covers GET, POST, PUT, DELETE on the node |

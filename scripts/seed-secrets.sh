#!/usr/bin/env bash
# seed-secrets.sh — Create all platform secrets from envs/secrets.env
#
# Single source of truth for k3d cluster secrets. All service credentials
# are defined in ~/work/envs/secrets.env (gitignored) and created as k8s
# Secrets in the appropriate namespaces.
#
# Usage:
#   task seed-secrets              # create missing secrets
#   task seed-secrets -- --force   # recreate all secrets
#
# The secrets.env file is auto-generated with random values if missing.

set -euo pipefail

SECRETS_FILE="${HOME}/work/envs/secrets.env"
FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

# ── Generate secrets.env if missing ──────────────────────────────────────────

generate_password() {
  openssl rand -base64 24 | tr -d '/+=' | head -c 24
}

if [[ ! -f "${SECRETS_FILE}" ]]; then
  echo "Generating ${SECRETS_FILE}..."
  cat > "${SECRETS_FILE}" <<EOF
# Platform secrets — auto-generated $(date -u +%Y-%m-%dT%H:%M:%SZ)
# DO NOT commit this file. It is gitignored.

# ── PostgreSQL ──
PG_N8N_PASSWORD=n8n
PG_MLFLOW_PASSWORD=mlflow
PG_LANGFUSE_PASSWORD=langfuse
PG_PLANE_PASSWORD=plane

# ── n8n ──
N8N_ENCRYPTION_KEY=$(generate_password)

# ── MLflow ──
MLFLOW_FLASK_SECRET_KEY=$(generate_password)

# ── MinIO ──
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin

# ── LiteLLM ──
LITELLM_API_KEY=sk-litellm-mewtwo-local

# ── GitLab ──
GITLAB_PAT=glpat-yGDTb8B7H5v4owSrN3Vxh286MQp1OjEH.01.0w06dez0e

# ── Plane ──
PLANE_API_TOKEN=plane_api_2ae384a415bd4c29acaa40872639e189

# ── Langfuse ──
LANGFUSE_PUBLIC_KEY=pk-lf-placeholder
LANGFUSE_SECRET_KEY=sk-lf-placeholder

# ── DataHub ──
DATAHUB_MYSQL_ROOT_PASSWORD=datahub

# ── n8n API ──
# Set after n8n boots: task n8n-setup creates the owner and API key
N8N_API_KEY=
EOF
  echo "  ✓ Generated ${SECRETS_FILE}"
  echo "  Edit as needed, then re-run this script."
fi

# ── Load secrets ─────────────────────────────────────────────────────────────

set -a
# shellcheck source=/dev/null
source "${SECRETS_FILE}"
set +a

# ── Helper ───────────────────────────────────────────────────────────────────

create_secret() {
  local ns="$1"
  local name="$2"
  shift 2
  # remaining args are --from-literal=key=value

  if [[ "${FORCE}" == "false" ]] && kubectl -n "${ns}" get secret "${name}" &>/dev/null; then
    echo "  ⊘ ${ns}/${name} exists — skipping"
    return
  fi

  kubectl -n "${ns}" create secret generic "${name}" "$@" \
    --dry-run=client -o yaml | kubectl apply -f - &>/dev/null
  echo "  ✓ ${ns}/${name}"
}

# ── Create Secrets ───────────────────────────────────────────────────────────

echo ""
echo "Seeding platform secrets..."

# PostgreSQL credentials
create_secret genai genai-pg-n8n \
  --from-literal=password="${PG_N8N_PASSWORD}" \
  --from-literal=postgres-password="${PG_N8N_PASSWORD}" \
  --from-literal=replication-password="${PG_N8N_PASSWORD}"

create_secret genai genai-pg-mlflow \
  --from-literal=password="${PG_MLFLOW_PASSWORD}" \
  --from-literal=postgres-password="${PG_MLFLOW_PASSWORD}" \
  --from-literal=replication-password="${PG_MLFLOW_PASSWORD}"

create_secret genai genai-pg-plane \
  --from-literal=password="${PG_PLANE_PASSWORD}" \
  --from-literal=postgres-password="${PG_PLANE_PASSWORD}"

# n8n
create_secret genai genai-n8n-encryption-key-secret-v2 \
  --from-literal=N8N_ENCRYPTION_KEY="${N8N_ENCRYPTION_KEY}"

create_secret genai genai-n8n-postgresql \
  --from-literal=password="${PG_N8N_PASSWORD}"

# MLflow
create_secret genai genai-mlflow-flask-server-secret-key \
  --from-literal=secret-key="${MLFLOW_FLASK_SECRET_KEY}"

create_secret genai genai-mlflow-env-secret \
  --from-literal=MLFLOW_FLASK_SECRET_KEY="${MLFLOW_FLASK_SECRET_KEY}"

# MinIO
create_secret genai genai-minio \
  --from-literal=root-user="${MINIO_ROOT_USER}" \
  --from-literal=root-password="${MINIO_ROOT_PASSWORD}"

# LiteLLM
create_secret genai kagent-litellm \
  --from-literal=LITELLM_MASTER_KEY="${LITELLM_API_KEY}"

# GitLab PAT (for sandbox git clone, MCP server, etc.)
create_secret genai gitlab-pat \
  --from-literal=token="${GITLAB_PAT}" \
  --from-literal=.git-credentials="http://root:${GITLAB_PAT}@gitlab-ce.platform.svc.cluster.local"

create_secret genai genai-mcp-gitlab-secret \
  --from-literal=GITLAB_PERSONAL_ACCESS_TOKEN="${GITLAB_PAT}"

# Plane
create_secret genai plane-api-token \
  --from-literal=token="${PLANE_API_TOKEN}"

# Langfuse
create_secret genai langfuse-api-keys \
  --from-literal=public-key="${LANGFUSE_PUBLIC_KEY}" \
  --from-literal=secret-key="${LANGFUSE_SECRET_KEY}"

# DataHub MySQL
create_secret genai mysql-secrets \
  --from-literal=mysql-root-password="${DATAHUB_MYSQL_ROOT_PASSWORD}"

# n8n sensitive env vars (loaded via extraSecretNamesForEnvFrom)
create_secret genai n8n-env-secrets \
  --from-literal=LITELLM_API_KEY="${LITELLM_API_KEY:-sk-litellm-mewtwo-local}" \
  --from-literal=PLANE_API_TOKEN="${PLANE_API_TOKEN}" \
  --from-literal=GITLAB_PAT="${GITLAB_PAT}"

# n8n API credentials (if set)
if [[ -n "${N8N_API_KEY:-}" ]]; then
  create_secret genai n8n-api-credentials \
    --from-literal=api-key="${N8N_API_KEY}" \
    --from-literal=owner-email="admin@platform.local" \
    --from-literal=owner-password="Admin-k3d-L0cal"
fi

# Agent Registry JWT signing key
create_secret genai agentregistry-jwt \
  --from-literal=AGENT_REGISTRY_JWT_PRIVATE_KEY="${AGENTREGISTRY_JWT_KEY:-$(openssl rand -hex 32)}"

# GitLab automation PAT (platform namespace)
create_secret platform gitlab-automation-pat \
  --from-literal=token="${GITLAB_PAT}"

echo ""
echo "Done. Secrets seeded from ${SECRETS_FILE}"

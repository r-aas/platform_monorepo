#!/usr/bin/env bash
# Ensure critical k8s secrets exist. Idempotent — creates only missing secrets.
# Run after cluster start to catch any secrets lost to chart upgrades or node restarts.
set -euo pipefail

SECRETS_ENV="${HOME}/work/envs/secrets.env"

ok()   { echo "  ✓ $*"; }
warn() { echo "  ⚠ $*"; }
fix()  { echo "  ▸ $*"; }

# Source secrets.env if available
if [ -f "$SECRETS_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$SECRETS_ENV"
  set +a
fi

# ── n8n encryption key (v2 secret name used by newer chart) ──
if ! kubectl get secret genai-n8n-encryption-key-secret-v2 -n genai &>/dev/null; then
  if [ -n "${N8N_ENCRYPTION_KEY:-}" ]; then
    fix "Creating genai-n8n-encryption-key-secret-v2"
    kubectl create secret generic genai-n8n-encryption-key-secret-v2 -n genai \
      --from-literal=N8N_ENCRYPTION_KEY="$N8N_ENCRYPTION_KEY"
  else
    warn "N8N_ENCRYPTION_KEY not set in secrets.env — n8n may fail to start"
  fi
else
  ok "genai-n8n-encryption-key-secret-v2 exists"
fi

# ── n8n env secrets (GITLAB_PAT, LITELLM_API_KEY, PLANE_API_TOKEN) ──
if ! kubectl get secret n8n-env-secrets -n genai &>/dev/null; then
  fix "Creating n8n-env-secrets"
  kubectl create secret generic n8n-env-secrets -n genai \
    --from-literal=GITLAB_PAT="${GITLAB_PAT:-}" \
    --from-literal=LITELLM_API_KEY="${LITELLM_API_KEY:-sk-litellm-mewtwo-local}" \
    --from-literal=PLANE_API_TOKEN="${PLANE_API_TOKEN:-}"
else
  ok "n8n-env-secrets exists"
fi

# ── GitLab PAT (used by sandbox, agent-gateway) ──
if ! kubectl get secret gitlab-pat -n genai &>/dev/null; then
  if [ -n "${GITLAB_PAT:-}" ]; then
    fix "Creating gitlab-pat secret"
    kubectl create secret generic gitlab-pat -n genai \
      --from-literal=token="$GITLAB_PAT"
  else
    warn "GITLAB_PAT not set — sandbox git clone will fail"
  fi
else
  ok "gitlab-pat exists"
fi

# ── n8n postgres password sync ──
# Bitnami postgres chart may generate a random password in the secret that
# doesn't match what the DB was initialized with. Sync if needed.
if kubectl get pod -n genai genai-pg-n8n-0 &>/dev/null; then
  PG_SECRET_PASS=$(kubectl get secret genai-pg-n8n -n genai -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d)
  if [ -n "$PG_SECRET_PASS" ]; then
    # Test if the secret password works
    if kubectl exec -n genai genai-pg-n8n-0 -- sh -c "PGPASSWORD='${PG_SECRET_PASS}' psql -U n8n -d n8n -c 'SELECT 1'" &>/dev/null; then
      ok "n8n postgres password in sync"
    else
      fix "Syncing n8n postgres password to match secret"
      # Find working password (try 'n8n' as fallback — common Bitnami default)
      for pw in n8n postgres; do
        if kubectl exec -n genai genai-pg-n8n-0 -- sh -c "PGPASSWORD='${pw}' psql -U n8n -d n8n -c \"ALTER USER n8n PASSWORD '${PG_SECRET_PASS}'\"" &>/dev/null; then
          ok "n8n postgres password synced"
          break
        fi
      done
    fi
  fi
fi

echo "  Secrets check complete."

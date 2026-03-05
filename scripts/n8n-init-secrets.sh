#!/usr/bin/env bash
# Generate n8n secrets for each namespace (idempotent — skips if exists)
set -euo pipefail

NAMESPACES="${*:-dev stage prod}"

for NS in $NAMESPACES; do
  if kubectl get secret n8n-secrets -n "$NS" &>/dev/null; then
    echo "✓ n8n-secrets already exists in $NS — skipping"
    continue
  fi

  PG_PASS=$(openssl rand -base64 24)
  ENC_KEY=$(openssl rand -hex 32)

  kubectl create secret generic n8n-secrets \
    --namespace="$NS" \
    --from-literal=postgres-password="$PG_PASS" \
    --from-literal=encryption-key="$ENC_KEY"

  echo "✓ Created n8n-secrets in $NS"
done

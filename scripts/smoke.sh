#!/usr/bin/env bash
set -euo pipefail

# Smoke tests — verify all platform services are reachable after deploy.
# Tests ingress endpoints, internal services, and database connectivity.
#
# Usage:
#   bash scripts/smoke.sh

PASS=0
FAIL=0
WARN=0

ok()   { echo "  ✓ $*"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $*"; FAIL=$((FAIL + 1)); }
warn() { echo "  ⚠ $*"; WARN=$((WARN + 1)); }

http_check() {
  local url="$1" label="$2" expect="${3:-200}"
  CODE=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null) || CODE=000
  if [ "$CODE" = "$expect" ]; then
    ok "$label ($CODE)"
  elif [ "$CODE" = "302" ] || [ "$CODE" = "301" ]; then
    ok "$label ($CODE redirect)"
  else
    fail "$label (got $CODE, expected $expect)"
  fi
}

# ── ArgoCD apps ─────────────────────────────────────────────
echo "ArgoCD Applications:"
TOTAL=$(kubectl get app -n platform --no-headers 2>/dev/null | wc -l | tr -d ' ')
HEALTHY=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -c "Healthy" || true)
SYNCED=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -c "Synced" || true)
if [ "$TOTAL" -gt 0 ]; then
  ok "${HEALTHY}/${TOTAL} Healthy, ${SYNCED}/${TOTAL} Synced"
  # Show unhealthy apps
  UNHEALTHY_APPS=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -v "Healthy" || true)
  if [ -n "$UNHEALTHY_APPS" ]; then
    echo "$UNHEALTHY_APPS" | while read -r line; do
      APP=$(echo "$line" | awk '{print $1}')
      STATUS=$(echo "$line" | awk '{print $2"/"$3}')
      warn "$APP: $STATUS"
    done
  fi
else
  fail "No ArgoCD applications found"
fi
echo ""

# ── Ingress endpoints ───────────────────────────────────────
echo "Ingress (HTTP):"
http_check "http://argocd.mewtwo.127.0.0.1.nip.io"           "ArgoCD"
http_check "http://gitlab.mewtwo.127.0.0.1.nip.io"           "GitLab"         302
http_check "http://n8n.mewtwo.127.0.0.1.nip.io"              "n8n"
http_check "http://mlflow.genai.127.0.0.1.nip.io/health"     "MLflow"
http_check "http://langfuse.genai.127.0.0.1.nip.io"          "Langfuse"
http_check "http://minio.genai.127.0.0.1.nip.io/minio/health/live" "MinIO"
http_check "http://minio-console.genai.127.0.0.1.nip.io"     "MinIO Console"
echo ""

# ── Internal services (via kubectl exec) ────────────────────
echo "Internal services:"
# Airflow API
if kubectl exec -n genai deploy/genai-airflow-api-server -- curl -sf -o /dev/null -w '%{http_code}' http://localhost:8080/api/v2/version 2>/dev/null | grep -q "200"; then
  ok "Airflow API"
else
  fail "Airflow API unreachable"
fi

# LiteLLM — check pod readiness
if kubectl get pod -n genai -l app.kubernetes.io/instance=genai-litellm --no-headers 2>/dev/null | grep -q "Running"; then
  ok "LiteLLM (pod running)"
else
  fail "LiteLLM pod not running"
fi

# Neo4j
if kubectl get pod -n genai genai-neo4j-0 --no-headers 2>/dev/null | grep -q "Running"; then
  ok "Neo4j (pod running)"
else
  fail "Neo4j pod not running"
fi
echo ""

# ── Databases ───────────────────────────────────────────────
echo "Databases:"
# Check each database individually (avoid IFS issues with repeated field values)
db_check() {
  local pod="$1" user="$2" db="$3" pass="$4"
  if kubectl exec -n genai "${pod}-0" -- env PGPASSWORD="$pass" psql -h 127.0.0.1 -U "$user" -d "$db" -c "SELECT 1;" &>/dev/null; then
    ok "$pod → $db"
  else
    fail "$pod → $db (connection failed)"
  fi
}
db_check "genai-pg-n8n"              "n8n"      "n8n"      "n8n"
db_check "genai-pg-mlflow"           "mlflow"   "mlflow"   "mlflow"
db_check "genai-pg-langfuse"         "langfuse" "langfuse" "langfuse"
db_check "genai-airflow-postgresql"  "postgres" "airflow"  "postgres"
# pgvector — might have different creds from old PV
if kubectl get pod -n genai genai-pgvector-0 --no-headers 2>/dev/null | grep -q "Running"; then
  ok "genai-pgvector (pod running)"
else
  fail "genai-pgvector pod not running"
fi
echo ""

# ── Pod health ──────────────────────────────────────────────
echo "Pod health:"
NOT_READY=$(kubectl get pods -n genai --no-headers 2>/dev/null | grep -v "Running\|Completed" | grep -v "Error.*0/" || true)
if [ -z "$NOT_READY" ]; then
  RUNNING=$(kubectl get pods -n genai --no-headers 2>/dev/null | grep -c "Running" || true)
  ok "All genai pods healthy ($RUNNING running)"
else
  echo "$NOT_READY" | while read -r line; do
    POD=$(echo "$line" | awk '{print $1}')
    STATUS=$(echo "$line" | awk '{print $3}')
    fail "$POD ($STATUS)"
  done
fi

PLATFORM_NOT_READY=$(kubectl get pods -n platform --no-headers 2>/dev/null | grep -v "Running\|Completed" || true)
if [ -z "$PLATFORM_NOT_READY" ]; then
  PLATFORM_RUNNING=$(kubectl get pods -n platform --no-headers 2>/dev/null | grep -c "Running" || true)
  ok "All platform pods healthy ($PLATFORM_RUNNING running)"
else
  echo "$PLATFORM_NOT_READY" | while read -r line; do
    POD=$(echo "$line" | awk '{print $1}')
    STATUS=$(echo "$line" | awk '{print $3}')
    fail "$POD ($STATUS)"
  done
fi
echo ""

# ── Ollama ──────────────────────────────────────────────────
echo "Host services:"
if curl -sf http://localhost:11434/api/version &>/dev/null; then
  ok "Ollama"
else
  warn "Ollama not running"
fi
echo ""

# ── Summary ─────────────────────────────────────────────────
echo "═══════════════════════════════════════════"
echo "Result: ${PASS} passed, ${FAIL} failed, ${WARN} warnings"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi

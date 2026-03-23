#!/usr/bin/env bash
set -euo pipefail

# Smoke tests — verify all platform services are reachable after deploy.
# Dynamically checks only services that ArgoCD is managing.
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

# Helper: check if an ArgoCD app exists
app_exists() {
  echo "$ARGO_APPS" | grep -qw "$1"
}

# ── Discover deployed apps ────────────────────────────────
ARGO_APPS=$(kubectl get app -n platform --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null || true)

# ── ArgoCD apps ─────────────────────────────────────────────
echo "ArgoCD Applications:"
TOTAL=$(echo "$ARGO_APPS" | grep -c '.' || true)
HEALTHY=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -c "Healthy" || true)
SYNCED=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -c "Synced" || true)
if [ "$TOTAL" -gt 0 ]; then
  ok "${HEALTHY}/${TOTAL} Healthy, ${SYNCED}/${TOTAL} Synced"
  UNHEALTHY_APPS=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -v "Healthy" || true)
  if [ -n "$UNHEALTHY_APPS" ]; then
    while IFS= read -r line; do
      APP=$(echo "$line" | awk '{print $1}')
      STATUS=$(echo "$line" | awk '{print $2"/"$3}')
      warn "$APP: $STATUS"
    done <<< "$UNHEALTHY_APPS"
  fi
else
  fail "No ArgoCD applications found"
fi
echo ""

# ── Ingress endpoints ───────────────────────────────────────
echo "Ingress (HTTP):"
# Always check platform services
http_check "http://argocd.mewtwo.127.0.0.1.nip.io"           "ArgoCD"
app_exists "gitlab-ce" && \
  http_check "http://gitlab.mewtwo.127.0.0.1.nip.io"         "GitLab"         302
# genai services — only if deployed
app_exists "genai-n8n" && \
  http_check "http://n8n.mewtwo.127.0.0.1.nip.io"            "n8n"
app_exists "genai-mlflow" && \
  http_check "http://mlflow.genai.127.0.0.1.nip.io/health"   "MLflow"
app_exists "genai-litellm" && \
  http_check "http://litellm.genai.127.0.0.1.nip.io/v1/models" "LiteLLM"
app_exists "genai-minio" && \
  http_check "http://minio.genai.127.0.0.1.nip.io/minio/health/live" "MinIO"
app_exists "genai-minio" && \
  http_check "http://minio-console.genai.127.0.0.1.nip.io"   "MinIO Console"
echo ""

# ── Internal services (via kubectl) ───────────────────────
echo "Internal services:"
if app_exists "genai-litellm"; then
  if kubectl get pod -n genai -l app.kubernetes.io/instance=genai-litellm --no-headers 2>/dev/null | grep -q "Running"; then
    ok "LiteLLM (pod running)"
    # Test LiteLLM → Ollama chat
    CHAT_RESP=$(curl -s --max-time 30 http://litellm.genai.127.0.0.1.nip.io/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d '{"model":"qwen2.5:14b","messages":[{"role":"user","content":"Reply OK"}],"max_tokens":5}' 2>/dev/null)
    if echo "$CHAT_RESP" | grep -q '"choices"'; then
      ok "LiteLLM → Ollama chat"
    else
      warn "LiteLLM → Ollama chat failed (Ollama may be loading model)"
    fi
  else
    fail "LiteLLM pod not running"
  fi
fi

# n8n → LiteLLM connectivity
if app_exists "genai-n8n" && app_exists "genai-litellm"; then
  if kubectl exec -n genai deploy/genai-n8n -- wget -q -O- http://genai-litellm.genai.svc.cluster.local:4000/v1/models 2>/dev/null | grep -q '"id"'; then
    ok "n8n → LiteLLM"
  else
    fail "n8n → LiteLLM (unreachable)"
  fi
fi

# n8n → MLflow connectivity
if app_exists "genai-n8n" && app_exists "genai-mlflow"; then
  if kubectl exec -n genai deploy/genai-n8n -- wget -q -O- --post-data='{"max_results":1}' --header='Content-Type: application/json' http://genai-mlflow.genai.svc.cluster.local/api/2.0/mlflow/experiments/search 2>/dev/null | grep -q '"experiments"'; then
    ok "n8n → MLflow"
  else
    fail "n8n → MLflow (unreachable)"
  fi
fi

# agent-gateway e2e (user → agent-gateway → n8n → LiteLLM → Ollama)
if app_exists "genai-agent-gateway"; then
  AGENT_RESP=$(curl -s --max-time 60 http://agent-gateway.genai.127.0.0.1.nip.io/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"agent:mlops","messages":[{"role":"user","content":"ping"}],"stream":false}' 2>/dev/null)
  if echo "$AGENT_RESP" | grep -q '"choices"'; then
    ok "agent-gateway e2e (mlops → n8n → LiteLLM → Ollama)"
  else
    warn "agent-gateway e2e failed (n8n import or agent sync may be needed)"
  fi
fi

echo ""

# ── Databases ───────────────────────────────────────────────
echo "Databases:"
db_check() {
  local pod="$1" user="$2" db="$3" pass="$4"
  if kubectl exec -n genai "${pod}-0" -- env PGPASSWORD="$pass" psql -h 127.0.0.1 -U "$user" -d "$db" -c "SELECT 1;" &>/dev/null; then
    ok "$pod → $db"
  else
    fail "$pod → $db (connection failed)"
  fi
}
app_exists "genai-pg-n8n"     && db_check "genai-pg-n8n"              "n8n"      "n8n"      "n8n"
app_exists "genai-pg-mlflow"  && db_check "genai-pg-mlflow"           "mlflow"   "mlflow"   "mlflow"
if app_exists "genai-pgvector"; then
  if kubectl get pod -n genai genai-pgvector-0 --no-headers 2>/dev/null | grep -q "Running"; then
    ok "genai-pgvector (pod running)"
  else
    fail "genai-pgvector pod not running"
  fi
fi
echo ""

# ── Pod health ──────────────────────────────────────────────
echo "Pod health:"
# Only check genai namespace if we have genai apps
if echo "$ARGO_APPS" | grep -q "genai-"; then
  NOT_READY=$(kubectl get pods -n genai --no-headers 2>/dev/null | grep -v "Running\|Completed\|Terminating" | grep -v "Error.*0/" || true)
  if [ -z "$NOT_READY" ]; then
    RUNNING=$(kubectl get pods -n genai --no-headers 2>/dev/null | grep -c "Running" || true)
    ok "All genai pods healthy ($RUNNING running)"
  else
    while IFS= read -r line; do
      POD=$(echo "$line" | awk '{print $1}')
      STATUS=$(echo "$line" | awk '{print $3}')
      fail "$POD ($STATUS)"
    done <<< "$NOT_READY"
  fi
fi

PLATFORM_NOT_READY=$(kubectl get pods -n platform --no-headers 2>/dev/null | grep -v "Running\|Completed\|Terminating" || true)
if [ -z "$PLATFORM_NOT_READY" ]; then
  PLATFORM_RUNNING=$(kubectl get pods -n platform --no-headers 2>/dev/null | grep -c "Running" || true)
  ok "All platform pods healthy ($PLATFORM_RUNNING running)"
else
  while IFS= read -r line; do
    POD=$(echo "$line" | awk '{print $1}')
    STATUS=$(echo "$line" | awk '{print $3}')
    fail "$POD ($STATUS)"
  done <<< "$PLATFORM_NOT_READY"
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

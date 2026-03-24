#!/usr/bin/env bash
set -euo pipefail

# Wait for ArgoCD applications to reach Synced+Healthy state.
# Polls every 15s, with configurable timeout.
# Also waits for genai pods to be Running.
#
# Three phases:
#   1. Wait for ArgoCD repo-server to render at least one app (Synced > 0)
#   2. Wait for all apps Healthy
#   3. Wait for genai pods Running
#
# Usage:
#   bash scripts/wait-healthy.sh           # default 15min timeout
#   bash scripts/wait-healthy.sh 300       # 5min timeout

TIMEOUT="${1:-900}"
INTERVAL=15
ELAPSED=0

log() { echo "▸ $*"; }

# ── Phase 1: Wait for repo-server to start rendering ─────
log "Phase 1: Waiting for ArgoCD repo-server to render charts (timeout: ${TIMEOUT}s)..."

while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
  TOTAL=$(kubectl get app -n platform --no-headers 2>/dev/null | wc -l | tr -d ' ')
  SYNCED=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -c "Synced" || true)

  # Require at least half of apps to be Synced — proves repo-server is working
  if [ "$TOTAL" -gt 0 ] && [ "$SYNCED" -gt "$((TOTAL / 2))" ]; then
    log "${SYNCED}/${TOTAL} apps Synced — repo-server is rendering."
    break
  fi

  printf "\r  %d/%d Synced [%ds]          " "$SYNCED" "$TOTAL" "$ELAPSED"

  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))

  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo ""
    log "Timeout waiting for sync. Current state:"
    kubectl get app -n platform 2>/dev/null
    exit 1
  fi
done

# ── Phase 2: Wait for all apps Healthy ───────────────────
log "Phase 2: Waiting for all apps to be Healthy..."

while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
  TOTAL=$(kubectl get app -n platform --no-headers 2>/dev/null | wc -l | tr -d ' ')
  HEALTHY=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -c "Healthy" || true)
  SYNCED=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -c "Synced" || true)

  if [ "$TOTAL" -gt 0 ] && [ "$HEALTHY" = "$TOTAL" ]; then
    log "All ${TOTAL} applications Healthy (${SYNCED} Synced)."
    break
  fi

  NOT_HEALTHY=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -v "Healthy" | awk '{printf "%s(%s) ", $1, $3}' || true)
  printf "\r  %d/%d Healthy, %d Synced [%ds] %s          " "$HEALTHY" "$TOTAL" "$SYNCED" "$ELAPSED" "$NOT_HEALTHY"

  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))

  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo ""
    log "⚠ Timeout after ${TIMEOUT}s. Current state:"
    kubectl get app -n platform 2>/dev/null
    break
  fi
done

# ── Phase 3: Wait for genai pods to actually be Running ──
log "Phase 3: Waiting for genai pods to be Ready..."

while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
  GENAI_TOTAL=$(kubectl get pods -n genai --no-headers 2>/dev/null | grep -v "Completed\|Terminating" | wc -l | tr -d ' ')
  GENAI_READY=$(kubectl get pods -n genai --no-headers 2>/dev/null | grep "Running" | grep -c "1/1\|2/2\|3/3" || true)

  if [ "$GENAI_TOTAL" -gt 3 ] && [ "$GENAI_READY" -ge "$((GENAI_TOTAL - 2))" ]; then
    # Allow up to 2 pods not ready (init jobs, etc.)
    log "${GENAI_READY}/${GENAI_TOTAL} genai pods Ready."
    exit 0
  fi

  NOT_READY=$(kubectl get pods -n genai --no-headers 2>/dev/null | grep -v "Running\|Completed\|Terminating" | awk '{printf "%s(%s) ", $1, $3}' || true)
  printf "\r  %d/%d genai pods Ready [%ds] %s          " "$GENAI_READY" "$GENAI_TOTAL" "$ELAPSED" "$NOT_READY"

  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo ""
log "⚠ Timeout after ${TIMEOUT}s — some apps still converging (cold image pulls?)."
log "Continuing with n8n-import and agent-sync; run 'task smoke' later to verify."
kubectl get pods -n genai 2>/dev/null
exit 0

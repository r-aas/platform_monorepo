#!/usr/bin/env bash
set -euo pipefail

# Wait for ArgoCD applications to reach Synced+Healthy state.
# Polls every 15s, with configurable timeout.
# Also waits for genai pods to be Running.
#
# Usage:
#   bash scripts/wait-healthy.sh           # default 15min timeout
#   bash scripts/wait-healthy.sh 300       # 5min timeout

TIMEOUT="${1:-900}"
INTERVAL=15
ELAPSED=0

log() { echo "▸ $*"; }

log "Waiting for ArgoCD applications to sync and be Healthy (timeout: ${TIMEOUT}s)..."

# Phase 1: Wait for all ArgoCD apps to be Synced + Healthy
while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
  TOTAL=$(kubectl get app -n platform --no-headers 2>/dev/null | wc -l | tr -d ' ')
  HEALTHY=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -c "Healthy" || true)
  SYNCED=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -c "Synced" || true)

  # Need all apps both Synced AND Healthy (or at least Healthy with some OutOfSync which is OK for SSA diffs)
  # The real gate: at least 1 app must be Synced (meaning repo-server has rendered something)
  if [ "$TOTAL" -gt 0 ] && [ "$HEALTHY" = "$TOTAL" ] && [ "$SYNCED" -gt 0 ]; then
    log "All ${TOTAL} applications Healthy (${SYNCED} Synced)."
    break
  fi

  # Show progress
  NOT_HEALTHY=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -v "Healthy" | awk '{printf "%s(%s) ", $1, $3}' || true)
  printf "\r  %d/%d Healthy, %d Synced [%ds] %s          " "$HEALTHY" "$TOTAL" "$SYNCED" "$ELAPSED" "$NOT_HEALTHY"

  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))

  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo ""
    log "Timeout after ${TIMEOUT}s. Current state:"
    kubectl get app -n platform 2>/dev/null
    exit 1
  fi
done

# Phase 2: Wait for genai pods to actually be Running
log "Waiting for genai pods to be Ready..."
REMAINING=$((TIMEOUT - ELAPSED))
[ "$REMAINING" -lt 60 ] && REMAINING=60

while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
  GENAI_TOTAL=$(kubectl get pods -n genai --no-headers 2>/dev/null | grep -v "Completed" | wc -l | tr -d ' ')
  GENAI_READY=$(kubectl get pods -n genai --no-headers 2>/dev/null | grep "Running" | grep -c "1/1\|2/2\|3/3" || true)

  if [ "$GENAI_TOTAL" -gt 5 ] && [ "$GENAI_READY" -ge "$((GENAI_TOTAL - 2))" ]; then
    # Allow up to 2 pods not ready (init jobs, etc.)
    log "${GENAI_READY}/${GENAI_TOTAL} genai pods Ready."
    exit 0
  fi

  NOT_READY=$(kubectl get pods -n genai --no-headers 2>/dev/null | grep -v "Running\|Completed" | awk '{printf "%s(%s) ", $1, $3}' || true)
  printf "\r  %d/%d genai pods Ready [%ds] %s          " "$GENAI_READY" "$GENAI_TOTAL" "$ELAPSED" "$NOT_READY"

  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo ""
log "Timeout. Current pod state:"
kubectl get pods -n genai 2>/dev/null
exit 1

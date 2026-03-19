#!/usr/bin/env bash
set -euo pipefail

# Wait for ArgoCD applications to reach Healthy state.
# Polls every 10s, with configurable timeout.
#
# Usage:
#   bash scripts/wait-healthy.sh           # default 10min timeout
#   bash scripts/wait-healthy.sh 300       # 5min timeout

TIMEOUT="${1:-600}"
INTERVAL=10
ELAPSED=0

log() { echo "▸ $*"; }

log "Waiting for ArgoCD applications to be Healthy (timeout: ${TIMEOUT}s)..."

while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
  TOTAL=$(kubectl get app -n platform --no-headers 2>/dev/null | wc -l | tr -d ' ')
  HEALTHY=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -c "Healthy" || true)

  if [ "$TOTAL" -gt 0 ] && [ "$HEALTHY" = "$TOTAL" ]; then
    log "All ${TOTAL} applications Healthy."
    exit 0
  fi

  # Show progress
  UNHEALTHY=$(kubectl get app -n platform --no-headers 2>/dev/null | grep -v "Healthy" | awk '{printf "%s(%s) ", $1, $3}')
  printf "\r  %d/%d Healthy [%ds] — waiting: %s" "$HEALTHY" "$TOTAL" "$ELAPSED" "$UNHEALTHY"

  sleep "$INTERVAL"
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo ""
log "Timeout after ${TIMEOUT}s. Current state:"
kubectl get app -n platform 2>/dev/null
exit 1

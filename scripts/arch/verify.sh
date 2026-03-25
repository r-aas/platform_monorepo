#!/usr/bin/env bash
# Detect drift between C4 diagrams and live k3d cluster
# Compares service names in diagrams vs kubectl output
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PLATFORM_DIR"

ARCH_DIR="docs/architecture"
SUMMARY_ONLY="${1:-}"  # pass --summary for counts only

# Collect live services (exclude headless -hl and kube-system)
LIVE_SVCS=$(kubectl get svc -A --no-headers 2>/dev/null \
  | grep -vE '^(kube-system|kube-node-lease|kube-public|default)\s' \
  | awk '{print $2}' \
  | grep -v '\-hl$' \
  | sort -u)

# Collect service IDs mentioned in diagrams
DIAG_SVCS=""
for mmd in "$ARCH_DIR"/c4-containers-*.mmd; do
  [ -f "$mmd" ] || continue
  # Extract entity names from Container() calls — second arg is display name
  names=$(grep -oE 'Container\([^,]+, "[^"]+"' "$mmd" | sed 's/Container([^,]*, "//; s/"//' | sort -u)
  DIAG_SVCS="$DIAG_SVCS
$names"
done
DIAG_SVCS=$(echo "$DIAG_SVCS" | grep -v '^$' | sort -u)

# Normalize names for comparison (strip genai-/platform- prefix from live names)
LIVE_NORM=$(echo "$LIVE_SVCS" | sed 's/^genai-//; s/^platform-//' | sort -u)
DIAG_NORM=$(echo "$DIAG_SVCS" | sort -u)

# Find stale (in diagram, not in cluster)
STALE=$(comm -23 <(echo "$DIAG_NORM") <(echo "$LIVE_NORM"))
STALE_COUNT=$(echo "$STALE" | grep -c '[a-z]' || true)

# Find undocumented (in cluster, not in any diagram)
UNDOC=$(comm -13 <(echo "$DIAG_NORM") <(echo "$LIVE_NORM"))
UNDOC_COUNT=$(echo "$UNDOC" | grep -c '[a-z]' || true)

if [ "$SUMMARY_ONLY" = "--summary" ]; then
  echo "${STALE_COUNT} stale, ${UNDOC_COUNT} undocumented"
  exit 0
fi

echo ""
echo "  Architecture Drift Report"
echo "  ─────────────────────────────────────────"
echo "  Live services:       $(echo "$LIVE_SVCS" | wc -l | tr -d ' ')"
echo "  Diagrammed services: $(echo "$DIAG_SVCS" | grep -c '[a-z]' || echo 0)"
echo ""

if [ "$STALE_COUNT" -gt 0 ]; then
  echo "  STALE (in diagram, not in cluster):"
  echo "$STALE" | sed 's/^/    ⚠ /'
  echo ""
fi

if [ "$UNDOC_COUNT" -gt 0 ]; then
  echo "  UNDOCUMENTED (in cluster, not in any diagram):"
  echo "$UNDOC" | sed 's/^/    ? /'
  echo ""
fi

if [ "$STALE_COUNT" -eq 0 ] && [ "$UNDOC_COUNT" -eq 0 ]; then
  echo "  No drift detected."
  echo ""
  exit 0
fi

TOTAL=$((STALE_COUNT + UNDOC_COUNT))
echo "  Total drift items: ${TOTAL}"
echo ""
exit 1

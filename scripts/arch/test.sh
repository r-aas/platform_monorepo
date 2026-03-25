#!/usr/bin/env bash
# Run connectivity tests derived from C4 Container diagrams
# Every Rel() edge becomes a connectivity test (any HTTP response = PASS)
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PLATFORM_DIR"

ARCH_DIR="docs/architecture"
RESULTS=$(mktemp)
trap "rm -f $RESULTS" EXIT

echo ""
echo "  Architecture Connectivity Tests"
echo "  ─────────────────────────────────────────"

for mmd in "$ARCH_DIR"/c4-containers-*.mmd; do
  [ -f "$mmd" ] || continue
  ns=$(basename "$mmd" .mmd | sed 's/c4-containers-//')

  # Match Rel(id_with_nums, id_with_nums, ...)
  grep -oE 'Rel\([a-z0-9_]+, [a-z0-9_]+' "$mmd" 2>/dev/null | while IFS= read -r rel; do
    src_id=$(echo "$rel" | sed 's/Rel(//; s/,.*//' | tr -d ' ')
    dst_id=$(echo "$rel" | sed 's/.*,//; s/)//' | tr -d ' ')

    src_svc=$(echo "$src_id" | tr '_' '-')
    dst_svc=$(echo "$dst_id" | tr '_' '-')

    # Skip external systems
    if [ "$dst_svc" = "ollama" ] || [ "$src_svc" = "ollama" ]; then
      printf "  %-45s SKIP (external)\n" "${src_svc} → ${dst_svc}"
      echo "SKIP" >> "$RESULTS"
      continue
    fi

    # Find destination port
    dst_port=$(kubectl get svc "$dst_svc" -n "$ns" -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || echo "")
    if [ -z "$dst_port" ]; then
      printf "  %-45s SKIP (svc not found)\n" "${src_svc} → ${dst_svc}"
      echo "SKIP" >> "$RESULTS"
      continue
    fi

    # Find a running source pod
    src_pod=$(kubectl get pods -n "$ns" --no-headers 2>/dev/null | grep "^${src_svc}" | grep Running | head -1 | awk '{print $1}')
    if [ -z "$src_pod" ]; then
      printf "  %-45s SKIP (no running pod)\n" "${src_svc} → ${dst_svc}"
      echo "SKIP" >> "$RESULTS"
      continue
    fi

    # Skip non-HTTP services (databases on 5432, 6379, etc.)
    case "$dst_port" in
      5432|3306|6379|27017|9042)
        printf "  %-45s SKIP (non-HTTP port %s)\n" "${src_svc} → ${dst_svc}" "$dst_port"
        echo "SKIP" >> "$RESULTS"
        continue
        ;;
    esac

    # Test connectivity — try python3, wget, curl in order
    url="http://${dst_svc}.${ns}.svc.cluster.local:${dst_port}/"
    HTTP=$(kubectl exec "$src_pod" -n "$ns" -- python3 -c "
import urllib.request, urllib.error
try:
    r = urllib.request.urlopen('$url', timeout=5)
    print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print(0)
" 2>/dev/null || echo "0")

    if [ "$HTTP" = "0" ]; then
      HTTP=$(kubectl exec "$src_pod" -n "$ns" -- wget -q -O /dev/null -S --timeout=5 "$url" 2>&1 | grep -oE 'HTTP/[0-9.]+ [0-9]+' | tail -1 | awk '{print $2}' 2>/dev/null || echo "0")
    fi
    if [ "$HTTP" = "0" ]; then
      HTTP=$(kubectl exec "$src_pod" -n "$ns" -- curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo "0")
    fi

    if [ "$HTTP" != "0" ]; then
      printf "  %-45s PASS (HTTP %s)\n" "${src_svc} → ${dst_svc}" "$HTTP"
      echo "PASS" >> "$RESULTS"
    else
      printf "  %-45s FAIL\n" "${src_svc} → ${dst_svc}"
      echo "FAIL" >> "$RESULTS"
    fi
  done
done

PASS=$(grep -c PASS "$RESULTS" 2>/dev/null; true)
FAIL=$(grep -c FAIL "$RESULTS" 2>/dev/null; true)
SKIP=$(grep -c SKIP "$RESULTS" 2>/dev/null; true)

echo "  ─────────────────────────────────────────"
echo "  Pass: ${PASS}  Fail: ${FAIL}  Skip: ${SKIP}"
echo ""

[ "$FAIL" -eq 0 ] || exit 1

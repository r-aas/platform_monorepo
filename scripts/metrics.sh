#!/usr/bin/env bash
# Platform metrics dashboard — spec delivery, task burn-down, smoke health
set -euo pipefail

SPECS_DIR="${PLATFORM_DIR:-$(cd "$(dirname "$0")/.." && pwd)}/specs"
SMOKE_SCRIPT="${PLATFORM_DIR:-$(cd "$(dirname "$0")/.." && pwd)}/scripts/smoke.sh"

# ── Colors ───────────────────────────────────────────────────
BOLD='\033[1m' DIM='\033[2m' GREEN='\033[32m' YELLOW='\033[33m' RED='\033[31m' CYAN='\033[36m' RESET='\033[0m'

echo -e "\n${BOLD}  Platform Metrics${RESET}"
echo -e "  ─────────────────────────────────────────"

# ── 1. Spec delivery ────────────────────────────────────────
shipped=0 planned=0 in_progress=0 draft=0 total=0
for spec_dir in "$SPECS_DIR"/*/; do
  [ -f "$spec_dir/spec.md" ] || continue
  total=$((total + 1))
  # Check both <!-- status: X --> and **Status**: X formats
  status=$(head -10 "$spec_dir/spec.md" | sed -n 's/.*status:[[:space:]]*\([a-zA-Z-]*\).*/\1/p' | head -1)
  [ -z "$status" ] && status=$(head -10 "$spec_dir/spec.md" | sed -n 's/.*\*\*Status\*\*:[[:space:]]*\([a-zA-Z-]*\).*/\1/p' | head -1)
  [ -z "$status" ] && status="unknown"
  status=$(echo "$status" | tr '[:upper:]' '[:lower:]')
  case "$status" in
    shipped)     shipped=$((shipped + 1)) ;;
    in-progress) in_progress=$((in_progress + 1)) ;;
    planned)     planned=$((planned + 1)) ;;
    draft)       draft=$((draft + 1)) ;;
  esac
done

echo -e "\n${CYAN}  Specs${RESET}"
printf "  %-20s %s\n" "Total:" "$total"
printf "  %-20s ${GREEN}%s${RESET}\n" "Shipped:" "$shipped"
[ "$in_progress" -gt 0 ] && printf "  %-20s ${YELLOW}%s${RESET}\n" "In Progress:" "$in_progress"
[ "$planned" -gt 0 ] && printf "  %-20s %s\n" "Planned:" "$planned"
[ "$draft" -gt 0 ] && printf "  %-20s ${DIM}%s${RESET}\n" "Draft:" "$draft"

# ── 2. Task burn-down ───────────────────────────────────────
echo -e "\n${CYAN}  Task Burn-down${RESET}"
grand_done=0 grand_total=0
for spec_dir in "$SPECS_DIR"/*/; do
  [ -f "$spec_dir/tasks.md" ] || continue
  name=$(basename "$spec_dir")
  done_count=$(grep -cE '^- \[x\]' "$spec_dir/tasks.md" 2>/dev/null; true)
  total_count=$(grep -cE '^- \[' "$spec_dir/tasks.md" 2>/dev/null; true)
  [ "$total_count" -eq 0 ] && continue
  grand_done=$((grand_done + done_count))
  grand_total=$((grand_total + total_count))
  pct=0
  [ "$total_count" -gt 0 ] && pct=$((done_count * 100 / total_count))
  # Color based on completion
  if [ "$pct" -eq 100 ]; then
    color="$GREEN"
  elif [ "$pct" -gt 0 ]; then
    color="$YELLOW"
  else
    color="$DIM"
  fi
  # Progress bar (20 chars wide)
  filled=$((pct / 5))
  empty=$((20 - filled))
  bar=""
  [ "$filled" -gt 0 ] && bar=$(printf '%0.s█' $(seq 1 $filled))
  [ "$empty" -gt 0 ] && bar="${bar}$(printf '%0.s░' $(seq 1 $empty))"
  printf "  ${color}%-24s %s %3d%% (%d/%d)${RESET}\n" "$name" "$bar" "$pct" "$done_count" "$total_count"
done

grand_pct=0
[ "$grand_total" -gt 0 ] && grand_pct=$((grand_done * 100 / grand_total))
echo -e "  ────────────────────────────────────────────────"
printf "  ${BOLD}%-24s      %3d%% (%d/%d)${RESET}\n" "TOTAL" "$grand_pct" "$grand_done" "$grand_total"

# ── 3. Smoke pass rate (optional — only if --smoke flag) ────
if [[ "${1:-}" == "--smoke" ]]; then
  echo -e "\n${CYAN}  Smoke Tests${RESET}"
  if [ -x "$SMOKE_SCRIPT" ]; then
    output=$("$SMOKE_SCRIPT" 2>&1 || true)
    pass=$(echo "$output" | grep -c '✓' || echo 0)
    fail=$(echo "$output" | grep -c '✗' || echo 0)
    smoke_total=$((pass + fail))
    smoke_pct=0
    [ "$smoke_total" -gt 0 ] && smoke_pct=$((pass * 100 / smoke_total))
    if [ "$smoke_pct" -eq 100 ]; then
      color="$GREEN"
    elif [ "$smoke_pct" -ge 80 ]; then
      color="$YELLOW"
    else
      color="$RED"
    fi
    printf "  ${color}Pass rate: %d%% (%d/%d)${RESET}\n" "$smoke_pct" "$pass" "$smoke_total"
    if [ "$fail" -gt 0 ]; then
      echo -e "  ${RED}Failures:${RESET}"
      echo "$output" | grep '✗' | sed 's/^/    /'
    fi
  else
    echo -e "  ${DIM}smoke.sh not found — skipping${RESET}"
  fi
fi

# ── 4. Platform assets ──────────────────────────────────────
echo -e "\n${CYAN}  Platform Assets${RESET}"
chart_count=$(ls -d "${SPECS_DIR}/../charts"/*/ 2>/dev/null | wc -l | tr -d ' ')
agent_count=$(ls "${SPECS_DIR}/../agents"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
service_count=$(ls -d "${SPECS_DIR}/../services"/*/ 2>/dev/null | wc -l | tr -d ' ')
printf "  %-20s %s\n" "Helm charts:" "$chart_count"
printf "  %-20s %s\n" "Agents:" "$agent_count"
printf "  %-20s %s\n" "Services:" "$service_count"

echo ""

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# spec-check.sh — Headless spec artifact linter
#
# Validates spec hygiene without AI. Designed for CI (GitLab) and local use.
# Exit 0 = all checks pass, Exit 1 = at least one failure.
#
# Usage: bash scripts/spec-check.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPECS_DIR="$REPO_ROOT/specs"
PASS=0
FAIL=0
WARN=0

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }
warn() { echo "  ⚠ $1"; WARN=$((WARN + 1)); }
section() { echo -e "\n── $1 ──"; }

# ── Guard: specs/ must exist ─────────────────────────────────────────────────
if [[ ! -d "$SPECS_DIR" ]]; then
  echo "No specs/ directory found — nothing to check."
  exit 0
fi

spec_dirs=("$SPECS_DIR"/*/spec.md)
if [[ ${#spec_dirs[@]} -eq 0 || ! -f "${spec_dirs[0]}" ]]; then
  echo "No specs found — nothing to check."
  exit 0
fi

# ── Detect branch ────────────────────────────────────────────────────────────
CURRENT_BRANCH="main"
if git rev-parse --abbrev-ref HEAD >/dev/null 2>&1; then
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
fi

echo "spec-check: validating $(echo "$SPECS_DIR"/*/spec.md | wc -w | tr -d ' ') specs (branch: $CURRENT_BRANCH)"

# ── Check 1: Status frontmatter ──────────────────────────────────────────────
section "Status frontmatter"
for spec in "$SPECS_DIR"/*/spec.md; do
  dir=$(basename "$(dirname "$spec")")
  if head -1 "$spec" | grep -q '<!-- status:'; then
    pass "$dir — has status frontmatter"
  else
    fail "$dir — missing <!-- status: ... --> on line 1"
  fi
done

# ── Check 2: Required sections ───────────────────────────────────────────────
section "Required sections"
for spec in "$SPECS_DIR"/*/spec.md; do
  dir=$(basename "$(dirname "$spec")")
  status=$(head -1 "$spec" | sed -n 's/.*status: \([a-z-]*\).*/\1/p')
  status="${status:-unknown}"
  has_req=$(grep -cE '^## .*(Requirements|requirements)' "$spec" || true)
  has_ver=$(grep -cE '^## .*(Verification|Success Criteria|Acceptance Criteria)' "$spec" || true)
  if [[ "$has_req" -gt 0 && "$has_ver" -gt 0 ]]; then
    pass "$dir — has Requirements + Verification/Criteria"
  elif [[ "$has_req" -eq 0 ]]; then
    if [[ "$status" == "shipped" || "$status" == "in-review" ]]; then
      fail "$dir — missing ## Requirements section"
    else
      warn "$dir — missing ## Requirements section (status: $status)"
    fi
  else
    if [[ "$status" == "shipped" || "$status" == "in-review" ]]; then
      fail "$dir — missing ## Verification/Criteria section"
    else
      warn "$dir — missing ## Verification/Criteria section (status: $status)"
    fi
  fi
done

# ── Check 3: FR IDs ──────────────────────────────────────────────────────────
section "Functional requirement IDs"
for spec in "$SPECS_DIR"/*/spec.md; do
  dir=$(basename "$(dirname "$spec")")
  fr_count=$(grep -cE '(^###? FR-|FR-[0-9]{3})' "$spec" || true)
  if [[ "$fr_count" -gt 0 ]]; then
    pass "$dir — $fr_count FR references"
  else
    fail "$dir — no FR-XXX requirement IDs found"
  fi
done

# ── Check 4: Contracts for webhook-touching specs ────────────────────────────
section "Contracts for webhook specs"
for spec in "$SPECS_DIR"/*/spec.md; do
  dir=$(basename "$(dirname "$spec")")
  spec_dir="$(dirname "$spec")"

  # Allow specs to skip this check: <!-- spec-check-skip: contracts -->
  skip_contracts=$(grep -c 'spec-check-skip:.*contracts' "$spec" || true)
  if [[ "$skip_contracts" -gt 0 ]]; then
    pass "$dir — contracts check skipped (explicit override)"
    continue
  fi

  # Check if spec modifies workflow JSON files (Files Changed table) or defines endpoints
  touches_workflow=$(grep -cE '\.(json)\b.*workflow|workflow.*\.json' "$spec" || true)
  defines_endpoint=$(grep -cE '^#+\s+Endpoint|^`(POST|GET|PUT|DELETE) /webhook/' "$spec" || true)

  if [[ "$touches_workflow" -gt 0 || "$defines_endpoint" -gt 0 ]]; then
    if [[ -d "$spec_dir/contracts" ]] && [[ -n "$(ls -A "$spec_dir/contracts" 2>/dev/null)" ]]; then
      pass "$dir — has contracts/ (touches webhooks/workflows)"
    else
      # Check status — only enforce for shipped specs
      status=$(head -1 "$spec" | sed -n 's/.*status: \([a-z-]*\).*/\1/p')
      status="${status:-unknown}"
      if [[ "$status" == "shipped" ]]; then
        fail "$dir — touches webhooks but missing contracts/ (status: shipped)"
      else
        warn "$dir — touches webhooks but no contracts/ yet (status: $status)"
      fi
    fi
  else
    pass "$dir — no webhook/workflow references (contracts not required)"
  fi
done

# ── Check 5: Data-model for DB-touching specs ────────────────────────────────
section "Data-model for DB specs"
for spec in "$SPECS_DIR"/*/spec.md; do
  dir=$(basename "$(dirname "$spec")")
  spec_dir="$(dirname "$spec")"

  touches_db=$(grep -ciE 'postgres|pgvector|migration|CREATE TABLE|ALTER TABLE|data.model' "$spec" || true)
  if [[ "$touches_db" -gt 0 ]]; then
    if [[ -f "$spec_dir/data-model.md" ]]; then
      pass "$dir — has data-model.md (touches DB)"
    else
      status=$(head -1 "$spec" | sed -n 's/.*status: \([a-z-]*\).*/\1/p')
      status="${status:-unknown}"
      if [[ "$status" == "shipped" ]]; then
        fail "$dir — touches DB but missing data-model.md (status: shipped)"
      else
        warn "$dir — touches DB but no data-model.md yet (status: $status)"
      fi
    fi
  else
    pass "$dir — no DB references (data-model not required)"
  fi
done

# ── Check 6: No orphan spec directories ──────────────────────────────────────
section "Orphan directories"
for spec_dir in "$SPECS_DIR"/*/; do
  dir=$(basename "$spec_dir")
  if [[ -f "$spec_dir/spec.md" ]]; then
    pass "$dir — has spec.md"
  else
    fail "$dir — directory exists but no spec.md"
  fi
done

# ── Check 7: No draft specs on main ──────────────────────────────────────────
section "Draft specs on main"
if [[ "$CURRENT_BRANCH" == "main" ]]; then
  for spec in "$SPECS_DIR"/*/spec.md; do
    dir=$(basename "$(dirname "$spec")")
    status=$(head -1 "$spec" | sed -n 's/.*status: \([a-z-]*\).*/\1/p')
    status="${status:-unknown}"
    if [[ "$status" == "draft" ]]; then
      warn "$dir — draft spec on main branch (should be on feature branch)"
    else
      pass "$dir — status: $status"
    fi
  done
else
  echo "  (skipped — not on main branch)"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo -e "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ $PASS passed  ✗ $FAIL failed  ⚠ $WARN warnings"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ "$FAIL" -gt 0 ]]; then
  echo "FAILED — $FAIL check(s) did not pass."
  exit 1
fi

echo "ALL CHECKS PASSED."
exit 0

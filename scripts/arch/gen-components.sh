#!/usr/bin/env bash
# Generate C4 Component diagram for a service from source code or OpenAPI
# Usage: gen-components.sh <service-name> [source-dir]
set -euo pipefail

SERVICE="${1:?Usage: gen-components.sh <service-name> [source-dir]}"
PLATFORM_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PLATFORM_DIR"

# Try to find source directory
SRC_DIR="${2:-services/${SERVICE}/src}"
if [ ! -d "$SRC_DIR" ]; then
  SRC_DIR="services/${SERVICE}"
fi

OUT="docs/architecture/c4-components-${SERVICE}.mmd"

cat > "$OUT" << HEADER
%% C4 Component Diagram — ${SERVICE}
%% Auto-generated from source code analysis
%% Re-generate: task arch:components -- ${SERVICE}
C4Component
  title ${SERVICE} Components

  Boundary(svc_${SERVICE//[-.]/_}, "${SERVICE}") {
HEADER

# Strategy 1: Parse FastAPI routers from source (.py only, no .pyc)
if [ -d "$SRC_DIR" ]; then
  ROUTERS=$(grep -rl --include='*.py' '@router\.\|app\.include_router\|APIRouter' "$SRC_DIR" 2>/dev/null | sort || true)

  if [ -n "$ROUTERS" ]; then
    for router_file in $ROUTERS; do
      module=$(basename "$router_file" .py)
      [[ "$module" == __* ]] && continue
      [[ "$module" == test_* ]] && continue

      prefixes=$(grep -oE 'prefix="[^"]*"' "$router_file" 2>/dev/null | sed 's/prefix="//;s/"//' | head -3 | tr '\n' ', ' | sed 's/,$//' || echo "")
      methods=$(grep -oE '@router\.(get|post|put|delete|patch)' "$router_file" 2>/dev/null | sed 's/@router\.//' | sort -u | tr '\n' ',' | sed 's/,$//' || echo "")
      endpoint_count=$(grep -cE '@router\.(get|post|put|delete|patch)' "$router_file" 2>/dev/null; true)

      desc="Routes: ${prefixes:-/} | ${methods:-mixed} | ${endpoint_count} endpoints"
      echo "    Component(${module//[-.]/_}, \"${module}\", \"FastAPI Router\", \"${desc}\")" >> "$OUT"
    done
  fi

  # Find non-router modules (.py only)
  MODULES=$(find "$SRC_DIR" -name "*.py" -not -name "__*" -not -name "test_*" | sort)
  for mod_file in $MODULES; do
    module=$(basename "$mod_file" .py)
    if echo "$ROUTERS" | grep -q "/${module}.py$" 2>/dev/null; then
      continue
    fi

    if grep -qE 'class.*Registry|class.*Store' "$mod_file" 2>/dev/null; then
      mod_type="Registry"
    elif grep -qE 'class.*Runtime|class.*Client' "$mod_file" 2>/dev/null; then
      mod_type="Runtime"
    elif grep -qE 'class.*Model|class.*Schema|BaseModel' "$mod_file" 2>/dev/null; then
      mod_type="Model"
    elif grep -qE 'def (sync|load|import|export)' "$mod_file" 2>/dev/null; then
      mod_type="Service"
    else
      continue
    fi

    class_count=$(grep -cE '^class ' "$mod_file" 2>/dev/null; true)
    func_count=$(grep -cE '^def |^async def ' "$mod_file" 2>/dev/null; true)
    desc="${class_count} classes, ${func_count} functions"
    echo "    Component(${module//[-.]/_}, \"${module}\", \"${mod_type}\", \"${desc}\")" >> "$OUT"
  done
fi

echo '  }' >> "$OUT"

# Add relationships based on imports (.py only)
if [ -d "$SRC_DIR" ]; then
  echo '' >> "$OUT"
  for mod_file in $(find "$SRC_DIR" -name "*.py" -not -name "__*" -not -name "test_*"); do
    src_mod=$(basename "$mod_file" .py)
    src_id=${src_mod//[-.]/_}
    imports=$(grep -oE 'from \.[a-z_]+ import|from \.\.[a-z_]+ import' "$mod_file" 2>/dev/null | sed 's/from \.\.*//' | sed 's/ import//' | tr -d '.' || true)
    for imp in $imports; do
      imp_id=${imp//[-.]/_}
      [ "$imp_id" = "$src_id" ] && continue
      echo "  Rel(${src_id}, ${imp_id}, \"imports\")" >> "$OUT"
    done
  done
fi

echo ""
echo "Generated $OUT ($(wc -l < "$OUT" | tr -d ' ') lines)"

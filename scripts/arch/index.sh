#!/usr/bin/env bash
# Generate docs/architecture/INDEX.md from diagram files
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PLATFORM_DIR"

ARCH_DIR="docs/architecture"
OUT="$ARCH_DIR/INDEX.md"

# Get drift summary if verify.sh exists
DRIFT="n/a"
if [ -x "scripts/arch/verify.sh" ]; then
  DRIFT=$(bash scripts/arch/verify.sh --summary 2>/dev/null || echo "unknown")
fi

cat > "$OUT" << HEADER
# Architecture Diagrams

> Auto-generated index. Run \`task arch:index\` to rebuild.
> Run \`task arch:regenerate\` after shipping a spec that changes platform services.

**Drift**: ${DRIFT}

| Diagram | C4 Level | Last Generated | Lines |
|---------|----------|---------------|-------|
HEADER

for mmd in "$ARCH_DIR"/*.mmd; do
  [ -f "$mmd" ] || continue
  name=$(basename "$mmd" .mmd)
  lines=$(wc -l < "$mmd" | tr -d ' ')

  # Determine C4 level from filename
  case "$name" in
    c4-context*)    level="Context" ;;
    c4-containers*) level="Container" ;;
    c4-components*) level="Component" ;;
    c4-code*)       level="Code" ;;
    *)              level="Other" ;;
  esac

  # Get last modified date from git or filesystem
  last_gen=$(git log -1 --format='%ci' -- "$mmd" 2>/dev/null | cut -d' ' -f1)
  if [ -z "$last_gen" ]; then
    last_gen=$(date -r "$mmd" '+%Y-%m-%d' 2>/dev/null || echo "unknown")
  fi

  echo "| [${name}](./${name}.mmd) | ${level} | ${last_gen} | ${lines} |" >> "$OUT"
done

cat >> "$OUT" << 'FOOTER'

## Regeneration

```bash
task arch:all          # Regenerate all diagrams + verify + rebuild index
task arch:context      # C4 Context only
task arch:containers   # C4 Container diagrams (all namespaces)
task arch:components   # C4 Component diagram (default: agent-gateway)
task arch:verify       # Drift detection
task arch:test         # Connectivity tests from container diagrams
```
FOOTER

echo "Generated $OUT"

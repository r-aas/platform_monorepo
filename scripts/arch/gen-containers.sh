#!/usr/bin/env bash
# Generate C4 Container diagram for a namespace from live k3d cluster
# Usage: gen-containers.sh <namespace>
set -euo pipefail

NS="${1:?Usage: gen-containers.sh <namespace>}"
PLATFORM_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PLATFORM_DIR"

OUT="docs/architecture/c4-containers-${NS}.mmd"

# Get services with their selectors to infer connections
SVCS_JSON=$(kubectl get svc -n "$NS" -o json 2>/dev/null)
DEPLOYS_JSON=$(kubectl get deploy,statefulset -n "$NS" -o json 2>/dev/null)

# Extract service names and types
SVC_NAMES=$(echo "$SVCS_JSON" | jq -r '.items[].metadata.name' | sort)

cat > "$OUT" << HEADER
%% C4 Container Diagram — ${NS} namespace
%% Auto-generated from live k3d cluster
%% Re-generate: task arch:containers
C4Container
  title ${NS} Namespace Containers

HEADER

echo "  Boundary(ns_${NS}, \"${NS}\") {" >> "$OUT"

for svc in $SVC_NAMES; do
  # Skip headless services (name ends with -hl)
  [[ "$svc" == *-hl ]] && continue

  # Get port info
  ports=$(echo "$SVCS_JSON" | jq -r ".items[] | select(.metadata.name==\"$svc\") | .spec.ports[]? | \"\(.port)/\(.protocol // \"TCP\")\"" | tr '\n' ', ' | sed 's/,$//')

  # Determine workload type
  kind=$(echo "$DEPLOYS_JSON" | jq -r ".items[] | select(.metadata.name==\"$svc\" or .metadata.name==(\"$svc\" | sub(\"^genai-\";\"\"))) | .kind" | head -1)
  [ -z "$kind" ] && kind="Service"

  # Get image for technology label
  image=$(echo "$DEPLOYS_JSON" | jq -r ".items[] | select(.metadata.name==\"$svc\" or .metadata.name==(\"$svc\" | sub(\"^genai-\";\"\"))) | .spec.template.spec.containers[0].image" 2>/dev/null | head -1)
  tech=""
  if [ -n "$image" ] && [ "$image" != "null" ]; then
    tech=$(echo "$image" | sed 's|.*/||; s|:.*||')
  fi

  # Clean display name
  display=$(echo "$svc" | sed "s/^genai-//; s/^platform-//")

  echo "    Container(${svc//[-.]/_}, \"${display}\", \"${tech}\", \"${kind} — ${ports}\")" >> "$OUT"
done

echo '  }' >> "$OUT"
echo '' >> "$OUT"

# External dependencies
echo '  System_Ext(ollama, "Ollama", "LLM on Mac host 192.168.65.254:11434")' >> "$OUT"
echo '' >> "$OUT"

# Infer relationships from environment variables referencing other services
for svc in $SVC_NAMES; do
  [[ "$svc" == *-hl ]] && continue
  svc_id=${svc//[-.]/_}

  # Check env vars for references to other services in this namespace
  envs=$(echo "$DEPLOYS_JSON" | jq -r ".items[] | select(.metadata.name==\"$svc\" or .metadata.name==(\"$svc\" | sub(\"^genai-\";\"\"))) | .spec.template.spec.containers[0].env[]? | \"\(.name)=\(.value // \"\")\"" 2>/dev/null || true)

  for other in $SVC_NAMES; do
    [[ "$other" == *-hl ]] && continue
    [ "$other" = "$svc" ] && continue
    other_id=${other//[-.]/_}
    # Check if this service references the other in env vars
    if echo "$envs" | grep -qi "$other" 2>/dev/null; then
      echo "  Rel(${svc_id}, ${other_id}, \"\")" >> "$OUT"
    fi
  done
done

# LiteLLM → Ollama relationship
if echo "$SVC_NAMES" | grep -q "litellm"; then
  echo "  Rel(genai_litellm, ollama, \"LLM inference\")" >> "$OUT"
fi

echo ""
echo "Generated $OUT ($(wc -l < "$OUT" | tr -d ' ') lines)"

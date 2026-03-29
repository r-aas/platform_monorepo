#!/usr/bin/env bash
set -euo pipefail

# Build custom images and import into k3d cluster.
# Called during bootstrap to ensure all images exist before ArgoCD deploys.
#
# Usage:
#   bash scripts/build-images.sh          # build all
#   bash scripts/build-images.sh --check  # just verify images exist

K3D_CLUSTER="${K3D_CLUSTER:-mewtwo}"
CHECK_ONLY="${1:-}"
GENAI_MLOPS="${HOME}/work/repos/genai-mlops"

log() { echo "▸ $*"; }
err() { echo "✗ $*" >&2; exit 1; }

# ── Image registry ──────────────────────────────────────────
# Images that need local builds (not from public registries).
# Format: name:tag:dockerfile_path:context_dir
PLATFORM_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGES=(
  "agent-gateway:latest:${PLATFORM_DIR}/services/agent-gateway/Dockerfile:${PLATFORM_DIR}"
  "litellm-mlflow:latest:${PLATFORM_DIR}/images/litellm/Dockerfile:${PLATFORM_DIR}/images/litellm"
  "mcp-kubernetes:latest:${PLATFORM_DIR}/images/mcp-kubernetes/Dockerfile:${PLATFORM_DIR}/images/mcp-kubernetes"
  "datahub-ingestion-mlflow:latest:${PLATFORM_DIR}/images/datahub-ingestion-mlflow/Dockerfile:${PLATFORM_DIR}/images/datahub-ingestion-mlflow"
  "datahub-bridge:latest:${PLATFORM_DIR}/services/n8n-datahub-bridge/Dockerfile:${PLATFORM_DIR}/services/n8n-datahub-bridge"
  "mcp-plane:latest:${PLATFORM_DIR}/images/mcp-plane/Dockerfile:${PLATFORM_DIR}/images/mcp-plane"
  "mcp-mlflow:latest:${PLATFORM_DIR}/images/mcp-mlflow/Dockerfile:${PLATFORM_DIR}/images/mcp-mlflow"
  "mcp-langfuse:latest:${PLATFORM_DIR}/images/mcp-langfuse/Dockerfile:${PLATFORM_DIR}/images/mcp-langfuse"
  "mcp-minio:latest:${PLATFORM_DIR}/images/mcp-minio/Dockerfile:${PLATFORM_DIR}/images/mcp-minio"
  "mcp-ollama:latest:${PLATFORM_DIR}/images/mcp-ollama/Dockerfile:${PLATFORM_DIR}/images/mcp-ollama"
  "open-ontologies:latest:${PLATFORM_DIR}/images/open-ontologies/Dockerfile:${PLATFORM_DIR}/images/open-ontologies"
  "agent-registry:latest:${PLATFORM_DIR}/images/agent-registry/Dockerfile:${HOME}/work/repos/agent-platform"
)

if [ "$CHECK_ONLY" = "--check" ]; then
  log "Checking custom images..."
  ALL_OK=true
  for entry in "${IMAGES[@]}"; do
    IFS=: read -r NAME TAG _ _ <<< "$entry"
    if docker image inspect "${NAME}:${TAG}" &>/dev/null; then
      echo "  ✓ ${NAME}:${TAG}"
    else
      echo "  ✗ ${NAME}:${TAG} — not built"
      ALL_OK=false
    fi
  done
  $ALL_OK || exit 1
  exit 0
fi

# ── Build and import ────────────────────────────────────────
# --import-only: skip builds, just re-import existing images into k3d
# Useful after k3d restart when images are already built locally.
IMPORT_ONLY="${2:-}"

for entry in "${IMAGES[@]}"; do
  IFS=: read -r NAME TAG DOCKERFILE CONTEXT <<< "$entry"

  if [ ! -f "$DOCKERFILE" ]; then
    echo "  ⚠ Skipping ${NAME}:${TAG} — Dockerfile not found: $DOCKERFILE"
    continue
  fi

  if [ "$IMPORT_ONLY" = "--import-only" ]; then
    if docker image inspect "${NAME}:${TAG}" &>/dev/null; then
      log "Importing ${NAME}:${TAG} into k3d-${K3D_CLUSTER}..."
      k3d image import "${NAME}:${TAG}" -c "$K3D_CLUSTER"
    else
      echo "  ⚠ ${NAME}:${TAG} not built locally — skipping (run without --import-only to build)"
    fi
    continue
  fi

  log "Building ${NAME}:${TAG}..."
  docker build -t "${NAME}:${TAG}" -f "$DOCKERFILE" "$CONTEXT"

  log "Importing ${NAME}:${TAG} into k3d-${K3D_CLUSTER}..."
  k3d image import "${NAME}:${TAG}" -c "$K3D_CLUSTER"

  log "${NAME}:${TAG} ready."
done

log "All custom images built and imported."

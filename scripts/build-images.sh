#!/usr/bin/env bash
set -euo pipefail

# Build or pull custom images and import into k3d cluster.
# Pulls pre-built ARM64 images from ghcr.io when available.
# Falls back to local build if pull fails.
#
# Usage:
#   bash scripts/build-images.sh              # pull or build all
#   bash scripts/build-images.sh --check      # just verify images exist
#   bash scripts/build-images.sh --local      # force local build (skip pull)
#   bash scripts/build-images.sh --import-only # re-import existing images to k3d

K3D_CLUSTER="${K3D_CLUSTER:-mewtwo}"
MODE="${1:-}"
REGISTRY="${IMAGE_REGISTRY:-ghcr.io/r-aas}"

log() { echo "▸ $*"; }
err() { echo "✗ $*" >&2; exit 1; }

# ── Image registry ──────────────────────────────────────────
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
  "mcp-claude-code:latest:${PLATFORM_DIR}/images/mcp-claude-code/Dockerfile:${PLATFORM_DIR}/images/mcp-claude-code"
  "mcp-gitlab:latest:${PLATFORM_DIR}/images/mcp-gitlab/Dockerfile:${PLATFORM_DIR}/images/mcp-gitlab"
  "mcp-n8n-knowledge:latest:${PLATFORM_DIR}/images/mcp-n8n-knowledge/Dockerfile:${PLATFORM_DIR}/images/mcp-n8n-knowledge"
  "mcp-n8n-manager:latest:${PLATFORM_DIR}/images/mcp-n8n-manager/Dockerfile:${PLATFORM_DIR}/images/mcp-n8n-manager"
  "open-ontologies:latest:${PLATFORM_DIR}/images/open-ontologies/Dockerfile:${PLATFORM_DIR}/images/open-ontologies"
)

# ── Check mode ──────────────────────────────────────────────
if [ "$MODE" = "--check" ]; then
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

# ── Import-only mode ────────────────────────────────────────
if [ "$MODE" = "--import-only" ]; then
  log "Re-importing existing images into k3d-${K3D_CLUSTER}..."
  for entry in "${IMAGES[@]}"; do
    IFS=: read -r NAME TAG _ _ <<< "$entry"
    if docker image inspect "${NAME}:${TAG}" &>/dev/null; then
      log "Importing ${NAME}:${TAG}..."
      k3d image import "${NAME}:${TAG}" -c "$K3D_CLUSTER"
    else
      echo "  ⚠ ${NAME}:${TAG} not found locally — skipping"
    fi
  done
  log "Done."
  exit 0
fi

# ── Pull or build ───────────────────────────────────────────
PULLED=0
BUILT=0
FAILED=0

for entry in "${IMAGES[@]}"; do
  IFS=: read -r NAME TAG DOCKERFILE CONTEXT <<< "$entry"

  # Try pulling from registry first (unless --local)
  if [ "$MODE" != "--local" ]; then
    REMOTE="${REGISTRY}/${NAME}:${TAG}"
    if docker pull "$REMOTE" 2>/dev/null; then
      docker tag "$REMOTE" "${NAME}:${TAG}"
      log "Pulled ${NAME}:${TAG} from registry"
      k3d image import "${NAME}:${TAG}" -c "$K3D_CLUSTER"
      PULLED=$((PULLED + 1))
      continue
    fi
  fi

  # Fall back to local build
  if [ ! -f "$DOCKERFILE" ]; then
    echo "  ⚠ Skipping ${NAME}:${TAG} — Dockerfile not found: $DOCKERFILE"
    FAILED=$((FAILED + 1))
    continue
  fi

  log "Building ${NAME}:${TAG} locally..."
  if docker build -t "${NAME}:${TAG}" -f "$DOCKERFILE" "$CONTEXT"; then
    k3d image import "${NAME}:${TAG}" -c "$K3D_CLUSTER"
    BUILT=$((BUILT + 1))
    log "${NAME}:${TAG} ready."
  else
    echo "  ✗ Failed to build ${NAME}:${TAG}"
    FAILED=$((FAILED + 1))
  fi
done

log "Done: ${PULLED} pulled, ${BUILT} built, ${FAILED} failed."
[ "$FAILED" -eq 0 ] || exit 1

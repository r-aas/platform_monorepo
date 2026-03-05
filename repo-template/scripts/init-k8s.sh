#!/usr/bin/env bash
# Replace APP_NAME placeholders in k8s/ manifests with actual project name.
# Usage: bash scripts/init-k8s.sh [project-name]
#        Defaults to the directory name if no argument given.

set -euo pipefail

PROJECT_NAME="${1:-$(basename "$(pwd)")}"

if [ ! -d k8s ]; then
  echo "ERROR: k8s/ directory not found. Run from project root." >&2
  exit 1
fi

echo "Replacing APP_NAME → ${PROJECT_NAME} in k8s/ manifests..."

if [[ "$(uname)" == "Darwin" ]]; then
  sed -i '' "s/APP_NAME/${PROJECT_NAME}/g" k8s/*.yaml
else
  sed -i "s/APP_NAME/${PROJECT_NAME}/g" k8s/*.yaml
fi

echo "Done. Verify with: cat k8s/deployment.yaml"

#!/usr/bin/env bash
# Create a KUBECONFIG file-type CI/CD variable on a GitLab project.
#
# The kubeconfig points at the k3d API via host.docker.internal so CI job
# containers (which run on the Docker bridge network) can reach the cluster.
#
# Usage:
#   export GITLAB_PAT=glpat-xxxx   # needs api scope
#   bash scripts/setup-ci-kubeconfig.sh root/myproject
#
# Requires: curl, jq, docker, kubectl

set -euo pipefail

PROJECT="${1:?Usage: setup-ci-kubeconfig.sh <namespace/project>}"
GITLAB_URL="${GITLAB_URL:-http://gitlab.platform.127.0.0.1.nip.io}"
GITLAB_PAT="${GITLAB_PAT:?Set GITLAB_PAT with api-scope token}"

# URL-encode the project path (e.g., root/myproject → root%2Fmyproject)
PROJECT_ENCODED=$(printf '%s' "$PROJECT" | jq -sRr @uri)

# ── 1. Get k3d API server port ──────────────────────────────────
API_PORT=$(docker port k3d-mewtwo-serverlb 6443/tcp 2>/dev/null | head -1 | cut -d: -f2)
if [ -z "$API_PORT" ]; then
  echo "ERROR: Cannot find k3d API port. Is the cluster running?" >&2
  echo "  Check: docker port k3d-mewtwo-serverlb 6443/tcp" >&2
  exit 1
fi
echo "k3d API port: $API_PORT"

# ── 2. Get CA cert and token from existing kubeconfig ────────────
CA_DATA=$(kubectl config view --raw -o jsonpath='{.clusters[?(@.name=="k3d-mewtwo")].cluster.certificate-authority-data}')
USER_CERT=$(kubectl config view --raw -o jsonpath='{.users[?(@.name=="admin@k3d-mewtwo")].user.client-certificate-data}')
USER_KEY=$(kubectl config view --raw -o jsonpath='{.users[?(@.name=="admin@k3d-mewtwo")].user.client-key-data}')

if [ -z "$CA_DATA" ] || [ -z "$USER_CERT" ] || [ -z "$USER_KEY" ]; then
  echo "ERROR: Cannot extract k3d-mewtwo credentials from kubeconfig." >&2
  echo "  Check: kubectl config view --raw" >&2
  exit 1
fi

# ── 3. Generate CI kubeconfig ────────────────────────────────────
CI_KUBECONFIG=$(cat <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: k3d-mewtwo
    cluster:
      server: https://host.docker.internal:${API_PORT}
      certificate-authority-data: ${CA_DATA}
contexts:
  - name: ci
    context:
      cluster: k3d-mewtwo
      user: ci-admin
current-context: ci
users:
  - name: ci-admin
    user:
      client-certificate-data: ${USER_CERT}
      client-key-data: ${USER_KEY}
EOF
)

echo "Generated CI kubeconfig (server: https://host.docker.internal:${API_PORT})"

# ── 4. Create or update the CI variable ──────────────────────────
# Try to delete existing variable first (ignore 404)
curl -sf -X DELETE \
  "${GITLAB_URL}/api/v4/projects/${PROJECT_ENCODED}/variables/KUBECONFIG" \
  -H "PRIVATE-TOKEN: ${GITLAB_PAT}" \
  > /dev/null 2>&1 || true

# Create as file-type variable
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  "${GITLAB_URL}/api/v4/projects/${PROJECT_ENCODED}/variables" \
  -H "PRIVATE-TOKEN: ${GITLAB_PAT}" \
  --form "key=KUBECONFIG" \
  --form "value=${CI_KUBECONFIG}" \
  --form "variable_type=file" \
  --form "protected=false" \
  --form "masked=false")

if [ "$HTTP_CODE" = "201" ]; then
  echo "✓ KUBECONFIG variable created on ${PROJECT}"
  echo "  CI jobs will see it as a file path in \$KUBECONFIG"
else
  echo "ERROR: Failed to create variable (HTTP ${HTTP_CODE})" >&2
  echo "  Check: GITLAB_PAT has api scope, project path is correct" >&2
  exit 1
fi

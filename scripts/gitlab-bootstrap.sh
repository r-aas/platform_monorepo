#!/usr/bin/env bash
set -euo pipefail

# GitLab Bootstrap — fully automated post-helmfile setup
#
# Creates PAT, registers runner, configures ArgoCD, pushes repo.
# Idempotent — safe to re-run.
#
# Usage:
#   task gitlab:setup          # runs this script
#   bash scripts/gitlab-bootstrap.sh  # direct
#
# Requires: kubectl, curl, jq, git

NAMESPACE="${NAMESPACE:-platform}"
GITLAB_POD="gitlab-ce-0"
GITLAB_SVC="http://gitlab-ce.${NAMESPACE}.svc.cluster.local"
GITLAB_EXTERNAL="${GITLAB_EXTERNAL_URL:-http://gitlab.mewtwo.127.0.0.1.nip.io}"
REPO_DIR="${PLATFORM_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PAT_NAME="platform-automation"
RUNNER_SECRET="gitlab-runner-token"

log() { echo "▸ $*"; }
err() { echo "✗ $*" >&2; exit 1; }

# ─── Step 1: Wait for GitLab readiness ──────────────────────────
log "Waiting for GitLab pod to be ready..."
kubectl -n "$NAMESPACE" wait --for=condition=ready pod/"$GITLAB_POD" --timeout=600s

# Verify HTTP is responding (reconfigure may still be running)
log "Waiting for GitLab HTTP to respond..."
for i in $(seq 1 60); do
  STATUS=$(kubectl -n "$NAMESPACE" exec "$GITLAB_POD" -- \
    curl -sf -o /dev/null -w '%{http_code}' http://localhost/-/readiness 2>/dev/null) || STATUS=0
  [ "$STATUS" = "200" ] && break
  [ "$i" = "60" ] && err "GitLab HTTP not ready after 5 minutes"
  sleep 5
done
log "GitLab is ready."

# ─── Step 2: Create Personal Access Token via Rails console ─────
log "Creating Personal Access Token..."

# Check if PAT already exists (stored in a k8s secret for idempotency)
EXISTING_PAT=$(kubectl -n "$NAMESPACE" get secret gitlab-automation-pat \
  -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null) || true

if [ -n "$EXISTING_PAT" ]; then
  log "PAT already exists (secret gitlab-automation-pat). Reusing."
  PAT="$EXISTING_PAT"
else
  # Create PAT via Rails console — the only reliable way on fresh GitLab
  # GitLab 18.x hashes tokens; must use auto-generated value, not set_token()
  PAT_VALUE=$(kubectl -n "$NAMESPACE" exec "$GITLAB_POD" -- \
    gitlab-rails runner "
      user = User.find_by_username('root')
      user.personal_access_tokens.where(name: '${PAT_NAME}').destroy_all
      token = user.personal_access_tokens.create!(
        name: '${PAT_NAME}',
        scopes: [:api, :read_api, :read_repository, :write_repository, :create_runner],
        expires_at: 1.year.from_now
      )
      print token.token
    " 2>/dev/null) || err "Failed to create PAT via Rails console"

  PAT="$PAT_VALUE"

  # Store PAT in k8s secret for future runs
  kubectl create secret generic gitlab-automation-pat \
    --namespace "$NAMESPACE" \
    --from-literal=token="$PAT" \
    --dry-run=client -o yaml | kubectl apply -f -
  log "PAT created and stored in secret gitlab-automation-pat."
fi

# ─── Step 3: Create runner via API ──────────────────────────────
log "Creating GitLab Runner via API..."

# Check if runner token secret already exists
EXISTING_RUNNER_TOKEN=$(kubectl -n "$NAMESPACE" get secret "$RUNNER_SECRET" \
  -o jsonpath='{.data.runner-token}' 2>/dev/null | base64 -d 2>/dev/null) || true

if [ -n "$EXISTING_RUNNER_TOKEN" ]; then
  log "Runner token already exists (secret $RUNNER_SECRET). Skipping creation."
else
  # Use kubectl exec to call the API from inside the cluster
  RUNNER_RESPONSE=$(kubectl -n "$NAMESPACE" exec "$GITLAB_POD" -- \
    curl -sf --request POST \
      --url "http://localhost/api/v4/user/runners" \
      --header "PRIVATE-TOKEN: ${PAT}" \
      --data "runner_type=instance_type" \
      --data "description=k8s-platform-runner" \
      --data "tag_list=k8s,platform" \
      --data "run_untagged=true" \
    2>/dev/null) || err "Failed to create runner via API"

  RUNNER_TOKEN=$(echo "$RUNNER_RESPONSE" | jq -r '.token // empty')
  [ -z "$RUNNER_TOKEN" ] && err "No token in API response: $RUNNER_RESPONSE"

  # Store runner token as k8s secret (referenced by gitlab-runner chart)
  kubectl create secret generic "$RUNNER_SECRET" \
    --namespace "$NAMESPACE" \
    --from-literal=runner-token="$RUNNER_TOKEN" \
    --dry-run=client -o yaml | kubectl apply -f -
  log "Runner created (token stored in secret $RUNNER_SECRET)."
fi

# ─── Step 4: Configure ArgoCD repo credentials ─────────────────
log "Configuring ArgoCD repo credentials..."

kubectl create secret generic argocd-repo-gitlab \
  --namespace "$NAMESPACE" \
  --from-literal=type=git \
  --from-literal=url="http://gitlab-ce.${NAMESPACE}.svc.cluster.local/root/platform_monorepo.git" \
  --from-literal=username=root \
  --from-literal=password="$PAT" \
  --from-literal=insecure=true \
  --dry-run=client -o yaml | \
kubectl label --local -f - argocd.argoproj.io/secret-type=repo-creds -o yaml | \
kubectl apply -f -
log "ArgoCD repo credential configured."

# ─── Step 5: Create GitLab project and push repo ───────────────
log "Pushing platform_monorepo to in-cluster GitLab..."

# Create project via API if it doesn't exist
PROJECT_EXISTS=$(kubectl -n "$NAMESPACE" exec "$GITLAB_POD" -- \
  curl -sf "http://localhost/api/v4/projects?search=platform_monorepo" \
    --header "PRIVATE-TOKEN: ${PAT}" 2>/dev/null | jq 'length') || PROJECT_EXISTS=0

if [ "$PROJECT_EXISTS" = "0" ]; then
  kubectl -n "$NAMESPACE" exec "$GITLAB_POD" -- \
    curl -sf --request POST \
      --url "http://localhost/api/v4/projects" \
      --header "PRIVATE-TOKEN: ${PAT}" \
      --data "name=platform_monorepo" \
      --data "visibility=internal" \
      --data "initialize_with_readme=false" \
    >/dev/null 2>&1
  log "Created GitLab project platform_monorepo."
else
  log "Project platform_monorepo already exists."
fi

# Push via git (from the host, through ingress)
cd "$REPO_DIR"
REMOTE_URL="http://root:${PAT}@gitlab.mewtwo.127.0.0.1.nip.io/root/platform_monorepo.git"

if git remote get-url gitlab >/dev/null 2>&1; then
  git remote set-url gitlab "$REMOTE_URL"
else
  git remote add gitlab "$REMOTE_URL"
fi

# Push all branches
git push gitlab --all --force 2>&1 || log "Warning: git push failed (GitLab may still be initializing). Retry with: git push gitlab --all"

log ""
log "Bootstrap complete."
log ""
log "  GitLab:     $GITLAB_EXTERNAL"
log "  ArgoCD:     http://argocd.mewtwo.127.0.0.1.nip.io"
log "  GitLab root password: $(kubectl -n "$NAMESPACE" get secret gitlab-ce-initial-password -o jsonpath='{.data.initial_root_password}' 2>/dev/null | base64 -d 2>/dev/null || echo '(check with: task gitlab-password)')"
log "  ArgoCD admin password: $(kubectl -n "$NAMESPACE" get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || echo '(check with: task argocd-password)')"
log ""
log "ArgoCD will now sync all workloads from GitLab. Monitor with:"
log "  task argocd-apps"

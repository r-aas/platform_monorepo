---
name: platform-gitlab-ci
description: |
  GitLab CI/CD patterns for the k3d platform. Use when configuring CI runners, writing
  .gitlab-ci.yml, debugging pipeline failures, fixing Kaniko builds, or troubleshooting
  CI networking (registry push, kubectl access, host.docker.internal). Covers every
  networking gotcha that has burned us.
version: 1.0.0
---

# Platform GitLab CI

## Architecture

- GitLab CE runs in k3d `platform` namespace (Helm chart, not docker-compose)
- GitLab Runner runs alongside (separate Helm chart in `platform` namespace)
- CI job containers run in Docker (Colima VM), NOT in k8s pods
- Builds use Kaniko (no Docker-in-Docker, no privileged containers)

## Runner Configuration

Key `config.toml` settings:

```toml
[[runners]]
  [runners.docker]
    network_mode = "platform_monorepo_gitlab"  # join GitLab's Docker network
    pull_policy = ["if-not-present"]            # fast CI with local cache
    extra_hosts = [
      "host.docker.internal:host-gateway",                          # k3d API access
      "gitlab.mewtwo.127.0.0.1.nip.io:<gitlab-container-ip>",      # GitLab HTTP
      "registry.mewtwo.127.0.0.1.nip.io:<gitlab-container-ip>"     # Registry
    ]
  url = "http://gitlab:80"        # Docker service name (NOT nip.io)
  clone_url = "http://gitlab:80"  # Same
```

**config.toml gotcha**: Never use `docker cp /dev/stdin` to write config — creates broken
symlinks. Use `docker exec` with heredoc instead.

## CI Networking Gotchas

### 1. host.docker.internal DNS

CI job containers on custom Docker bridge networks don't resolve `host.docker.internal`
via Docker's embedded DNS.

**Fix**: `extra_hosts = ["host.docker.internal:host-gateway"]` in runner config.

### 2. bitnami/kubectl entrypoint

`bitnami/kubectl:latest` has `kubectl` as entrypoint. GitLab runner wraps scripts in
`sh -c`, which becomes `kubectl sh -c ...` — fails.

**Fix**: Always add `entrypoint: [""]` in `.gitlab-ci.yml`:
```yaml
deploy:
  image:
    name: bitnami/kubectl:latest
    entrypoint: [""]
```

### 3. Smoke tests via ingress

nip.io resolves to 127.0.0.1 (pod-local inside CI containers).

**Fix**: Use host.docker.internal with Host header:
```bash
curl -f http://host.docker.internal \
  -H "Host: app.dev.127.0.0.1.nip.io" \
  --max-time 10
```

### 4. kubectl in CI

CI containers can't use the default kubeconfig. Generate a CI-specific one:
```bash
# In CI job:
export KUBECONFIG=/tmp/ci-kubeconfig.yaml
kubectl config set-cluster k3d \
  --server=https://host.docker.internal:$(k3d kubeconfig get mewtwo | grep server | grep -o '[0-9]*$') \
  --insecure-skip-tls-verify=true
```

Or use `scripts/setup-ci-kubeconfig.sh` which does this.

### 5. Secret detection (gitleaks)

Requires full git history for meaningful scans:
```yaml
secret_detection:
  variables:
    GIT_DEPTH: 0  # full history, not shallow clone
```

### 6. pip-audit + uv

pip-audit doesn't understand uv.lock. Export first:
```yaml
security_scan:
  script:
    - uv export --no-hashes --frozen > requirements.txt
    - pip-audit -r requirements.txt
```

## Kaniko Builds

Kaniko builds images without Docker daemon access. Key flags:

```yaml
build:
  image:
    name: gcr.io/kaniko-project/executor:latest
    entrypoint: [""]
  script:
    - /kaniko/executor
      --context $CI_PROJECT_DIR
      --dockerfile $CI_PROJECT_DIR/Dockerfile
      --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
      --destination $CI_REGISTRY_IMAGE:latest
      --insecure                    # HTTP registry (no TLS locally)
      --skip-tls-verify             # same
      --cache=true                  # layer caching
      --cache-repo=$CI_REGISTRY_IMAGE/cache
```

## Standard .gitlab-ci.yml Template

```yaml
stages:
  - lint
  - test
  - build
  - deploy
  - smoke

variables:
  GIT_DEPTH: 0

lint:
  image: python:3.12-slim
  script:
    - pip install uv && uv run ruff check .

test:
  image: python:3.12-slim
  script:
    - pip install uv && uv sync && uv run pytest

build:
  image:
    name: gcr.io/kaniko-project/executor:latest
    entrypoint: [""]
  script:
    - /kaniko/executor --context $CI_PROJECT_DIR --dockerfile Dockerfile
      --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
      --insecure --skip-tls-verify

deploy:
  image:
    name: bitnami/kubectl:latest
    entrypoint: [""]
  script:
    - source scripts/setup-ci-kubeconfig.sh
    - kubectl apply -k k8s/overlays/dev/

smoke:
  image: curlimages/curl:latest
  script:
    - curl -f http://host.docker.internal -H "Host: app.dev.127.0.0.1.nip.io" --max-time 30
```

## Rationalizations to Reject

- "I'll use Docker-in-Docker for builds" — NO, use Kaniko (no privileged containers)
- "nip.io URLs will work in CI" — NO, they resolve to container-local 127.0.0.1
- "I don't need extra_hosts, DNS should work" — NO, custom bridge networks break host.docker.internal
- "I'll use docker cp to write config" — NO, creates broken symlinks

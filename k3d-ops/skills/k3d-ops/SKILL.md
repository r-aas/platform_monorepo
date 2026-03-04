---
name: k3d-ops
description: k3d cluster conventions, namespace layout, GitLab CI/CD integration, and deployment patterns for R's shared mewtwo cluster. Use when working with k3d, Kubernetes, deploying to the local cluster, creating k8s manifests, debugging pod issues, or referencing cluster URLs.
version: 1.0.0
---

# k3d Cluster Operations

## Shared Cluster: mewtwo

One shared k3d cluster named **mewtwo** (the workstation hostname) serves all projects. Never create per-project clusters.

- Config: `~/work/k3d-mewtwo.yaml`
- PV storage: `~/work/data/k3d/mewtwo/` bind-mounted to `/var/lib/rancher/k3s/storage`
- Ingress: ingress-nginx (Traefik disabled)
- Ports: 80 and 443 mapped to loadbalancer

### Namespaces

| Namespace | Purpose |
|-----------|---------|
| dev | Development workloads, GitLab Runner executes CI jobs here |
| stage | Staging / pre-prod |
| prod | Production (deploy requires explicit guard) |
| platform | Shared infrastructure — GitLab CE, monitoring |

### Cluster Lifecycle

From `~/work`:

```bash
task k3d:cluster-up     # create cluster + install ingress-nginx + init namespaces
task k3d:cluster-down   # delete cluster (PV data preserved on host)
task k3d:status         # full cluster overview
```

## DNS & URL Pattern

Uses nip.io wildcard DNS — no /etc/hosts needed.

Pattern: `http://{app}.{namespace}.127.0.0.1.nip.io`

Examples:
- `http://myapp.dev.127.0.0.1.nip.io`
- `http://gitlab.mewtwo.127.0.0.1.nip.io` (GitLab, platform namespace uses cluster name)
- `http://registry.mewtwo.127.0.0.1.nip.io` (container registry)

## GitLab CE (Platform Namespace)

GitLab CE runs in the `platform` namespace for local CI/CD.

- Manifests: `~/work/platform/gitlab-ce.yaml`, `~/work/platform/gitlab-runner.yaml`
- Deploy: `task gitlab:deploy` (from ~/work)
- Root password: `task gitlab:password`
- Registry: built-in, at `http://registry.mewtwo.127.0.0.1.nip.io`
- CI builds: Kaniko (no Docker-in-Docker, no privileged containers)

## Deployment Conventions

### Per-repo k8s manifests

Live in `k8s/` directory within each project. Deploy with:

```bash
task deploy        # or task k8s:apply
```

### Ingress template

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: APP_NAME
spec:
  ingressClassName: nginx
  rules:
    - host: APP_NAME.NAMESPACE.127.0.0.1.nip.io
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: APP_NAME
                port:
                  number: 80
```

### Container images

Push to the local GitLab registry:

```
registry.mewtwo.127.0.0.1.nip.io/{project-path}:{tag}
```

Use `--insecure` and `--skip-tls-verify` flags with Kaniko (no TLS locally).

## Ollama Access from Pods

Pods reach the host Ollama via `host.docker.internal`:

```yaml
env:
  - name: OPENAI_BASE_URL
    value: "http://host.docker.internal:11434/v1"
  - name: OPENAI_API_KEY
    value: "ollama"
```

Never containerize Ollama — it must run natively on macOS for GPU (Metal) access.

## Safety Rules

1. **Never deploy to prod without explicit confirmation** from R
2. **Never create per-project clusters** — always use the shared mewtwo cluster
3. **Never containerize Ollama** — GPU workloads run native on Mac
4. **Always use ingress-nginx** — Traefik is disabled
5. **PVCs survive cluster recreation** because storage is bind-mounted from host

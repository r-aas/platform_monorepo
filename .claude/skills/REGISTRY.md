# Platform Skills Registry

Skills in this repo address the recurring pain points of operating the platform monorepo:
k3d cluster lifecycle, Helm chart authoring, ArgoCD GitOps, GitLab CI, and networking.

Each skill includes an `evals.yml` for autoresearch-based optimization.

## Skills

| Skill | Pain Point | Status | Pass Rate |
|-------|-----------|--------|-----------|
| [platform-helm-authoring](skills/platform-helm-authoring/) | ARM64 gotchas, Bitnami deprecations, values layering | draft | — |
| [platform-k3d-networking](skills/platform-k3d-networking/) | nip.io in containers, registry access, DNS after restart | draft | — |
| [platform-argocd](skills/platform-argocd/) | ApplicationSet patterns, sync debugging, bootstrap | draft | — |
| [platform-gitlab-ci](skills/platform-gitlab-ci/) | Runner config, Kaniko builds, CI networking | draft | — |
| [platform-bootstrap](skills/platform-bootstrap/) | Full cluster lifecycle from zero to all services healthy | draft | — |

## Also Active (from k3d-ops plugin)

| Skill | Location | Notes |
|-------|----------|-------|
| k3d-ops | `k3d-ops/skills/k3d-ops/` | General k3d conventions — superseded by platform-* for specific domains |

## Optimization History

Track autoresearch optimization runs here. Updated by `/skill-optimize`.

| Skill | Baseline | Current | Iterations | Last Run |
|-------|----------|---------|------------|----------|
| — | — | — | — | — |

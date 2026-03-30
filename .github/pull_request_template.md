## Summary

<!-- What changed and why? 1-3 bullets. -->

## What layer does this change?

- [ ] Helm chart (`charts/`)
- [ ] Workflow (`n8n-data/workflows/`)
- [ ] Agent (`agents/`)
- [ ] MCP server (`images/mcp-*`)
- [ ] Script (`scripts/`)
- [ ] Infrastructure (helmfile, taskfiles, manifests)
- [ ] Documentation

## Checklist

- [ ] `helm lint` passes on changed charts
- [ ] `task smoke` passes after deploying
- [ ] No secrets in committed files
- [ ] Images build on ARM64 (Apple Silicon)

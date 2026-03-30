# Contributing

## Adding a new service

1. Create a Helm chart in `charts/genai-{name}/`
2. Use `existingSecret` for credentials — never inline secrets in values.yaml
3. Set resource requests and limits (check `docs/architecture.md` for conventions)
4. Ensure the image is ARM64-compatible (Apple Silicon)
5. ArgoCD auto-discovers charts from the `charts/` directory — no manual registration needed
6. Add the service URL to the README services table

## Adding a new n8n workflow

1. Export the workflow JSON from n8n
2. Save to `n8n-data/workflows/{name}.json`
3. The workflow promotion Helm hook patches docker-compose URLs to k8s DNS automatically
4. Webhook paths are set in the workflow JSON — no separate routing config
5. Document the webhook endpoint in the README workflows table

## Adding a new MCP server

1. Create `images/mcp-{name}/Dockerfile` — use `node:22-alpine` or `python:3.12-slim` as base
2. Create `charts/genai-mcp-{name}/` with deployment, service, and resource limits
3. Add the server to the agentgateway config (`charts/genai-agentgateway/`)
4. Add to `scripts/build-images.sh` image registry
5. If the image cross-compiles on GitHub Actions, add to `.github/workflows/build-images.yml`
6. Run `task smoke` to verify the tool appears in the federated gateway

## Adding a new agent

1. Create `agents/{name}/agent.yaml` with the kagent Agent CRD spec
2. Define: name, description, schedule (cron), LLM config, skills, guardrails
3. Agent must list `toolNames` explicitly — omitting causes crash
4. Memory config: pgvector backend with TTL and categories
5. Test locally: `kubectl apply -f agents/{name}/agent.yaml -n genai`

## Development workflow

```bash
# Make changes
vim charts/genai-{name}/values.yaml

# Lint
helm lint charts/genai-{name}/

# Deploy to local cluster
task up                    # if cluster isn't running
git add . && git commit    # commit changes
git push gitlab main       # push to in-cluster GitLab
# ArgoCD auto-syncs within 3 minutes, or force:
kubectl annotate app genai-{name} -n argocd argocd.argoproj.io/refresh=hard --overwrite

# Verify
task smoke
```

## Conventions

- **Image pull policy**: `IfNotPresent` for all custom images
- **Service DNS**: `genai-{name}.genai.svc.cluster.local`
- **Ingress host**: `{name}.platform.127.0.0.1.nip.io`
- **Secrets**: via `existingSecret` referencing k8s secrets created by `task seed-secrets`
- **Resources**: always set requests and limits
- **ARM64**: all images must build natively on Apple Silicon

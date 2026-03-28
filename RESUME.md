# Platform Monorepo — Session Resume

## Session: 2026-03-28 — Plane CE Project Setup + MinIO Fix

### What Was Built

**Plane CE — Fully Operational with File Uploads**
- Project "Platform Monorepo" (PLAT) created in workspace `r-aas`
- Fixed `USE_MINIO=0` → `USE_MINIO=1` in doc-store secret (required for S3-compatible storage)
- Created `plane-uploads` bucket on shared MinIO
- Added ingress path `/plane-uploads` → `genai-minio:9000` for browser-reachable presigned URLs
- Set `aws_s3_endpoint_url` to external URL (`http://plane.genai.127.0.0.1.nip.io`) so presigned upload URLs work from browser
- Set `minio.local_setup: true` in Helm values to ensure `USE_MINIO=1` persists through ArgoCD syncs
- Admin: `r@appliedaisystems.com` / `Plane-k3d-Dev!2026`
- Workspace: `r-aas` at `http://plane.genai.127.0.0.1.nip.io/r-aas/`

**Claude Code Agent Runtime — End-to-End Working** (previous session)
- `agent-claude` Docker image: Node 22 + Claude Code CLI, non-root agent user
- OAuth credentials from macOS Keychain → k8s secret (`claude-credentials`)
- `ClaudeCodeAdapter` fixed: no longer injects `{{llm_base_url}}` template vars as `ANTHROPIC_BASE_URL`
- Entrypoint: credentials mount at `/secrets/claude/`, HOME export, nullglob for skills
- `scripts/refresh-claude-credentials.sh`: syncs OAuth token to k8s secret
- `launchd` plist at `~/Library/LaunchAgents/com.r.claude-credentials-refresh.plist` (runs every 30min)
- CronJob + schedule router conditionally mount `claude-credentials` secret for `claude-code` runtime

**Previous Sessions** (still deployed):
- n8n: 13 workflows imported, 10 active
- Sandbox: pre-warmed pool, PVC, artifacts, listing, cleanup
- RuntimeAdapter layer: ClaudeCodeAdapter, SandboxAdapter, N8nAdapter, HttpAdapter
- ClaudeCodeRuntime: k8s Job execution with ConfigMap workspace
- Scheduled agent jobs: CronJob CRUD + manual trigger

### Verified Working

- Plane CE project creation via API ✓
- Plane project list page shows "Platform Monorepo" (PLAT) ✓
- MinIO bucket `plane-uploads` exists ✓
- Ingress routes `/plane-uploads` to MinIO ✓
- `POST /schedule/jobs` — creates CronJob with `runtime: claude-code` ✓
- `POST /schedule/jobs/{name}/trigger` — runs Claude Code agent in k8s ✓
- All Plane pods Running ✓
- All previous endpoints still working (health, chat, sandbox, schedule) ✓

### Known Issues

1. **Plane cover image upload** — presigned URL flow works now but the chart deploys an unused local MinIO pod (harmless, `minio.local_setup: true` was needed to get `USE_MINIO=1`)
2. **ArgoCD OutOfSync** — `genai-plane` app shows OutOfSync due to manual secret patches + ingress patch. Will resync once Helm values are committed and pushed.
3. **OAuth token refresh from launchd** — `CLAUDE_CODE_OAUTH_TOKEN` only available inside Claude Desktop sessions. Best approach: call refresh script from Claude Code hook or at session start.
4. **Token refresh rate limiting** — Anthropic's OAuth endpoint has aggressive rate limits.
5. **qwen2.5:14b responds in Thai/Chinese** — LLM hallucination with many tools.
6. **openAiApi credential broken in n8n** — LangChain sub-nodes can't use openAiApi.

### Key Technical Details

**Plane MinIO fix:**
- `USE_MINIO=1` required in `genai-plane-doc-store-secrets` for S3-compatible storage
- Chart ties `USE_MINIO` to `minio.local_setup` — must be `true` even with external MinIO
- `AWS_S3_ENDPOINT_URL` must be browser-reachable (not internal k8s URL) for presigned uploads
- Ingress needs `/plane-uploads` path routing to MinIO service for browser PUT/POST

**OAuth credential flow:**
```
macOS Keychain "Claude Code-credentials"
    → scripts/refresh-claude-credentials.sh
    → k8s secret "claude-credentials" (genai namespace)
    → mounted at /secrets/claude/credentials.json in agent-claude pods
    → entrypoint copies to ~/.claude/.credentials.json
    → Claude Code CLI authenticates via OAuth
```

### Next

1. **Unified Agent Gateway** — merge agent-registry into agent-gateway (see plan: polymorphic-watching-tarjan.md)
2. **Plane GitLab integration** — configure GitLab CE integration in Plane settings
3. **Plane API as MCP server** — make Plane REST API accessible to agents
4. **Claude Code hook for credential refresh** — run refresh script at session start
5. **Canary traffic routing** — integrate canary_weight into chat endpoint routing logic
6. **Agent eval framework** — automated shadow vs primary comparison scoring
7. **Runtime benchmarking** — same task + same spec + different runtime = comparable metrics

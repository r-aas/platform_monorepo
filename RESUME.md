# Platform Monorepo — Session Resume

## Session: 2026-03-27 (continued) — Runtime Adapter + Plane + Sandbox Improvements

### What Was Built

**n8n Workflow Import** — 13 workflows imported to k3d.
- All URLs patched for k3d (MLflow, LiteLLM, n8n, Ollama)
- 10 active (webhook-bearing), 3 inactive (sub-workflows)
- Ollama credential created and patched into chat-v1
- Both paths verified: simple chat + MCP agent mode

**Sandbox Improvements** — pre-warmed pool, PVC, artifacts, listing.
- Pre-warmed pod pool: standby Deployment with claimable pods for near-instant start
- Optional workspace PVC for persistent storage across sandbox iterations
- Artifact collection: `GET /sandbox/jobs/{name}/artifacts` lists workspace files
- Artifact read: `GET /sandbox/jobs/{name}/artifacts/{path}` reads file content
- Job listing: `GET /sandbox/jobs` lists all sandbox jobs with status
- Cleanup: `POST /sandbox/cleanup` removes expired completed jobs
- Pool management: `POST /sandbox/pool` creates/resizes warm pool
- Config: `sandbox_warm_pool_size`, `sandbox_workspace_size` settings

**RuntimeAdapter Layer** — converts agent specs to runtime workspaces.
- `RuntimeAdapter` ABC with `from_config(AgentRunConfig) -> RuntimeWorkspace`
- `ClaudeCodeAdapter`: generates CLAUDE.md, .claude/skills/, .claude/settings.json
- `SandboxAdapter`, `N8nAdapter`, `HttpAdapter` for existing runtimes
- `RuntimeWorkspace` dataclass: files dict, env dict, command list
- Adapter registry: `get_adapter(runtime_name)`

**ClaudeCodeRuntime** — Claude Code as a k8s Job runtime.
- Converts AgentRunConfig → Claude Code workspace via ClaudeCodeAdapter
- CLAUDE.md from system_prompt + prompt_fragments + MCP docs
- Skills from skill catalog prompt_fragment fields
- MCP settings from registered MCP servers
- k8s Job with agent-claude image, ConfigMap workspace mount
- Registered as `claude-code` runtime in gateway

**agent-claude Docker Image** — Claude Code CLI in a container.
- Node 22 + `@anthropic-ai/claude-code` CLI
- Entrypoint: reads ConfigMap, writes CLAUDE.md/skills/MCP, runs `claude --print`
- Git init (Claude Code requirement), non-root agent user
- Located at `images/agent-claude/`

**Scheduled Agent Jobs** — k8s CronJobs from registry specs.
- `POST /schedule/jobs` — create CronJob from agent name + cron schedule + message
- Resolves agent + skills + MCP from registry at creation time
- Converts to runtime workspace via RuntimeAdapter
- `GET /schedule/jobs` — list all scheduled jobs
- `POST /schedule/jobs/{name}/trigger` — manual trigger (creates one-off Job)
- `PUT /schedule/jobs/{name}/suspend` — suspend/resume
- `DELETE /schedule/jobs/{name}` — delete CronJob + ConfigMap
- RBAC: sandbox-manager Role updated with CronJob, exec, PVC, Deployment perms

**Plane CE** — project management (deploying).
- `genai-pg-plane` chart (Bitnami PostgreSQL for Plane)
- Plane CE v1.4.1 via ArgoCD helmWorkloads (external Helm repo)
- Shared infra: PostgreSQL, Redis (langfuse), MinIO
- RabbitMQ local (no shared instance)
- ARM64 images from Docker Hub (makeplane/*)
- Ingress: plane.genai.127.0.0.1.nip.io
- MinIO bucket: plane-uploads
- local-path provisioner switched to overlay FS (supports chown)

### Verified Working

- `GET /health` — healthy
- `POST /webhook/chat` (n8n) — simple + MCP agent modes work
- `POST /v1/chat/completions` (gateway) — end-to-end streaming works
- `GET /sandbox/jobs` — lists sandbox jobs
- `POST /sandbox/jobs` — creates jobs, result extraction works
- `GET /schedule/jobs` — empty list (no errors)
- `POST /schedule/jobs` — creates CronJob from registry agent spec
- `POST /schedule/jobs/{name}/trigger` — manual trigger creates one-off Job
- Plane frontend pods: web, space, admin, rabbitmq all Running
- 10/13 n8n workflows active, webhooks responding

### Known Issues

1. **Plane backends CrashLooping** — waiting for genai-pg-plane PostgreSQL image to finish pulling. Once PG is up, backends will auto-recover (DNS error → healthy).
2. **Bitnami CDN timeout from k3d** — ArgoCD repo-server can't reach charts.bitnami.com within 90s. Fixed by committing chart .tgz. May need this for other new Bitnami chart dependencies.
3. **qwen2.5:14b responds in Thai/Chinese** — LLM hallucination with many tools or certain prompts. Workaround: use simpler prompts or more capable model.
4. **openAiApi credential broken in n8n** — LangChain sub-nodes can't use openAiApi. Workaround: ollamaApi.

### Commits Pushed

- `f59b353` fix: commit pg-plane chart dependency
- `c93441f` feat: Claude Code runtime + RuntimeAdapter + scheduled agent jobs
- `890ffb1` fix: plane rabbitmq storageClass for k3d sshfs compat
- `a48e3aa` fix: plane image tags — chart appends planeVersion automatically
- `5e20fb4` feat: sandbox improvements + Plane CE project management

### Next

1. **Build agent-claude image** — `docker build -t agent-claude:latest images/agent-claude/` + k3d import, then test end-to-end with `runtime: claude-code`
2. **Plane setup** — once PG is up, access plane.genai.127.0.0.1.nip.io, create workspace, configure GitLab integration
3. **Plane API agent** — register Plane REST API as MCP server or n8n integration for agent access
4. **Canary traffic routing** — integrate canary_weight into chat endpoint routing logic
5. **DataHub ingestion** — ingest k8s resources, GitLab repos, MLflow experiments
6. **Agent eval framework** — automated shadow vs primary comparison scoring
7. **Runtime benchmarking** — same task + same spec + different runtime = comparable metrics

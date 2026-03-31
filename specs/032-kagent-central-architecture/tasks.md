<!-- status: planned -->
# 032 Tasks — kagent Central Architecture

## Current State (as of 2026-03-31)

- 8 agents running (all Ready)
- 4/9 MCPServers Ready (kubernetes, datahub, mlflow, ollama)
- 5 MCPServers need dedicated secrets (langfuse, minio, plane, gitlab, n8n)
- 9 old `charts/genai-mcp-*` dirs still exist
- Transpiler `scripts/agentspec-to-kagent.py` still exists
- `agents/_shared/` and `agents/envs/` still exist
- No `genai-dev` or `genai-stage` namespaces
- OTEL disabled in kagent values
- 1 ModelConfig exists (`default-model-config`)

---

## Task 1: Create MCP Server Secrets

**Agent type**: general-purpose
**Isolation**: none (needs kubectl)
**Estimated time**: 10 min

**Objective**: Create the 5 dedicated k8s secrets so all 9 MCPServer CRDs reach Ready.

**Instructions**:
1. Read `~/work/envs/secrets.env` to find the values for:
   - `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` → secret `mcp-langfuse-env`
   - `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` → secret `mcp-minio-env`
   - `PLANE_API_TOKEN` → secret `mcp-plane-env` (key: `PLANE_API_KEY`)
   - `GITLAB_PAT` → secret `mcp-gitlab-env` (key: `GITLAB_PERSONAL_ACCESS_TOKEN`)
   - `N8N_API_KEY` → secret `mcp-n8n-env` (key: `N8N_API_KEY`)
2. Create each secret in `genai` namespace using `kubectl create secret generic`
3. Add secret creation to `scripts/seed-secrets.sh` so they survive cluster recreation
4. Verify: `kubectl get mcpservers -n genai` — all 9 should show Ready=True

**Verification**:
```bash
kubectl get mcpservers -n genai --no-headers | grep -c True  # expect 9
```

---

## Task 2: Create Embedding ModelConfig + Update Chat ModelConfig

**Agent type**: general-purpose
**Isolation**: none (needs kubectl)
**Estimated time**: 10 min

**Objective**: Ensure both chat and embedding ModelConfig CRDs exist for agent memory support.

**Instructions**:
1. Read `charts/genai-kagent/values.yaml` — check current provider config
2. Read `~/.claude/skills/kagent-agents/SKILL.md` for ModelConfig CRD schema
3. Create a Helm template `charts/genai-kagent/templates/modelconfigs.yaml` with:
   - `litellm-config` — provider: OpenAI, model: glm-4.7-flash, baseUrl: LiteLLM, secret: kagent-litellm
   - `embedding-config` — provider: OpenAI, model: nomic-embed-text, baseUrl: LiteLLM, secret: kagent-litellm
4. Ensure the `kagent-litellm` secret exists (check `scripts/seed-secrets.sh`)

**Verification**:
```bash
kubectl get modelconfigs -n genai --no-headers | wc -l  # expect 3 (default + 2 new)
```

---

## Task 3: Enable kagent OTEL → Langfuse

**Agent type**: general-purpose
**Isolation**: worktree
**Estimated time**: 30 min

**Objective**: Enable kagent's OpenTelemetry tracing and route traces to Langfuse.

**Instructions**:
1. Read `charts/genai-kagent/values.yaml` — find the `otel:` section (currently disabled)
2. Read kagent OTEL docs at `~/work/clones/kagent/kagent/python/packages/kagent-core/src/kagent/core/tracing/`
3. Research Langfuse OTEL ingestion endpoint format (web search if needed)
4. Update `charts/genai-kagent/values.yaml`:
   - Set `otel.tracing.enabled: true`
   - Set appropriate OTEL exporter endpoint for Langfuse
5. If Langfuse needs an OTEL collector sidecar, add it to the kagent chart
6. Create or update `langfuse-api-keys` secret if needed for OTEL auth
7. Do NOT modify any other sections of the chart

**Verification**:
```bash
# After ArgoCD sync:
kubectl logs -l app.kubernetes.io/name=kagent -n genai --tail=20 | grep -i otel
# Should show OTEL initialization, not errors
# Check Langfuse UI for traces from kagent
```

---

## Task 4: Create Promotion Namespaces + ArgoCD Apps

**Agent type**: general-purpose
**Isolation**: worktree
**Estimated time**: 30 min

**Objective**: Create genai-dev and genai-stage namespaces with ArgoCD ApplicationSets for the promotion pipeline.

**Instructions**:
1. Read `charts/genai-kagent/values.yaml` — note `watchNamespaces` config
2. Read `charts/argocd/` or `manifests/` for existing ArgoCD config patterns
3. Create namespace manifests for `genai-dev` and `genai-stage`
4. Update kagent `watchNamespaces` to include all three: `[genai, genai-dev, genai-stage]`
5. Create ArgoCD Application or ApplicationSet that deploys kagent agents to:
   - `genai-dev` from feature branches
   - `genai-stage` from main branch
   - `genai` from release tags (or main with manual sync)
6. Ensure MCP servers are accessible from all three namespaces (they live in `genai`, agents in dev/stage reference them cross-namespace)
7. Add RBAC: kagent service account needs permissions in all three namespaces

**Verification**:
```bash
kubectl get ns genai-dev genai-stage  # both exist
kubectl get agents.kagent.dev -n genai-dev  # empty but queryable (no permission error)
```

---

## Task 5: Delete Old MCP Charts + Clean Up Transpiler

**Agent type**: general-purpose
**Isolation**: worktree
**Estimated time**: 20 min

**Objective**: Delete the 9 old genai-mcp-* Helm chart directories and the transpiler script. Clean up related files.

**Prerequisites**: Task 1 complete (all 9 MCPServers Ready).

**Instructions**:
1. Verify all 9 MCPServer CRDs are Ready: `kubectl get mcpservers -n genai`
2. If any are NOT Ready, STOP and report which ones failed
3. Delete these directories:
   - `charts/genai-mcp-kubernetes/`
   - `charts/genai-mcp-gitlab/`
   - `charts/genai-mcp-n8n/`
   - `charts/genai-mcp-datahub/`
   - `charts/genai-mcp-plane/`
   - `charts/genai-mcp-mlflow/`
   - `charts/genai-mcp-langfuse/`
   - `charts/genai-mcp-minio/`
   - `charts/genai-mcp-ollama/`
4. Delete `scripts/agentspec-to-kagent.py`
5. Delete `agents/_shared/` directory
6. Delete `agents/envs/` directory
7. Update any Taskfile references to the transpiler (check `taskfiles/agents.yml`)
8. Update ArgoCD: ensure it doesn't try to sync deleted charts (check for Application resources targeting these charts)
9. Do NOT delete anything else

**Verification**:
```bash
ls charts/genai-mcp-* 2>/dev/null  # should error "No such file"
ls scripts/agentspec-to-kagent.py 2>/dev/null  # should error
ls agents/_shared/ 2>/dev/null  # should error
kubectl get mcpservers -n genai --no-headers | grep -c True  # still 9
```

---

## Task 6: Rewrite Agent CRDs (Direct v1alpha2)

**Agent type**: general-purpose
**Isolation**: worktree
**Estimated time**: 45 min

**Objective**: Rewrite all 6 custom agent definitions as direct kagent v1alpha2 CRDs in a Helm template, referencing ModelConfig and RemoteMCPServer resources by name.

**Instructions**:
1. Read each agent spec in `agents/*/agent.yaml` (6 agents: platform-admin, project-coordinator, data-engineer, mlops, developer, qa-eval)
2. Read `~/.claude/skills/kagent-agents/SKILL.md` for the v1alpha2 Agent CRD schema
3. Read existing `charts/genai-kagent/templates/` to see what's already there
4. For each agent, create a kagent v1alpha2 Agent CRD with:
   - `spec.type: Declarative`
   - `spec.declarative.runtime: python`
   - `spec.declarative.modelConfig: litellm-config`
   - `spec.declarative.systemMessage:` (copy from agent.yaml system_prompt)
   - `spec.declarative.tools:` — list each MCP server with EXPLICIT toolNames (REQUIRED or pods crash)
   - `spec.declarative.memory.modelConfig: embedding-config` with appropriate ttlDays
   - `spec.declarative.a2aConfig.skills:` — list agent skills
   - Version labels: `app.kubernetes.io/version`, `agentops.dev/promoted-from`
5. Write all 6 CRDs into `charts/genai-kagent/templates/agents.yaml`
6. Cross-reference toolNames against RemoteMCPServer resources: `kubectl get remotemcpservers -n genai -o jsonpath='{range .items[*]}{.metadata.name}: {.status.discoveredTools[*].name}{"\n"}{end}'`
7. Do NOT modify existing built-in agents (helm-agent, k8s-agent)

**Verification**:
```bash
helm template genai-kagent charts/genai-kagent/ | grep "kind: Agent" | wc -l  # expect 6+
# After deploy:
kubectl get agents.kagent.dev -n genai --no-headers | wc -l  # expect 8
kubectl logs -l kagent.dev/agent=platform-admin-agent -n genai --tail=5  # no ValidationError
```

---

## Task 7: Update CronJob Schedules for A2A

**Agent type**: general-purpose
**Isolation**: worktree
**Estimated time**: 20 min

**Objective**: Ensure CronJob schedule chart references correct kagent A2A endpoints and doesn't depend on transpiler.

**Instructions**:
1. Read `charts/genai-agent-schedules/` — values.yaml and templates/
2. Verify CronJobs POST to kagent A2A endpoint format: `http://{agent-name}.genai.svc.cluster.local:8080/`
3. Verify the JSON-RPC payload format matches kagent A2A spec
4. Ensure values.yaml has correct agent names and schedules:
   - platform-admin-agent: `*/15 * * * *`
   - project-coordinator-agent: `0 * * * *`
   - data-engineer-agent: `0 */2 * * *`
   - mlops-agent: `0 */4 * * *`
   - developer-agent: `0 */6 * * *`
   - qa-eval-agent: `0 2 * * *`
5. Remove any references to transpiler output or custom agent spec format
6. Add a namespace-aware template so CronJobs can target dev/stage/prod

**Verification**:
```bash
kubectl get cronjobs -n genai --no-headers | wc -l  # expect 6
kubectl get cronjob platform-admin-agent-schedule -n genai -o jsonpath='{.spec.schedule}'  # */15 * * * *
```

---

## Task 8: Write GitLab CI Pipeline (.gitlab-ci.yml)

**Agent type**: general-purpose
**Isolation**: worktree
**Estimated time**: 45 min

**Objective**: Rewrite `.gitlab-ci.yml` with the full 8-stage AgentOps pipeline with enforced quality gates.

**Instructions**:
1. Read current `.gitlab-ci.yml` to understand existing stages
2. Read spec 032 sections 6 and 7 for the pipeline design
3. Read `scripts/eval-triad.py` to understand the eval interface
4. Read `data/benchmarks/` to see available test datasets
5. Rewrite `.gitlab-ci.yml` with these stages:
   - **lint**: agent YAML schema validation, prompt quality lint, helm lint, ruff
   - **validate**: CRD dry-run apply, helm template render, gitleaks, hadolint
   - **eval-candidate**: run eval-triad.py against MLflow baseline, fail if regression > 5%
   - **deploy-staging**: ArgoCD sync to genai-stage namespace
   - **integration-test**: A2A invoke each agent, MCP tool call, OTEL trace check
   - **deploy-prod**: ArgoCD sync to genai (manual gate)
   - **post-deploy-eval**: smoke test + regression check after production deploy
   - **feedback**: auto-create GitLab issue if regression detected, auto-revert MR if critical
6. Gate 1 (lint + validate + eval-candidate) MUST be `allow_failure: false` for agent changes
7. Gate 2 (deploy-staging + integration-test) MUST pass before deploy-prod is available
8. Use rules to only trigger agent-specific jobs when `agents/**/*` changes
9. Write a companion `scripts/agent-lint.py` for the lint stage

**Verification**:
```bash
# Dry-run the pipeline locally:
gitlab-ci-lint .gitlab-ci.yml 2>/dev/null || python3 -c "import yaml; yaml.safe_load(open('.gitlab-ci.yml'))"
# Should parse without errors
grep -c "allow_failure: false" .gitlab-ci.yml  # expect ≥ 3 (blocking gates)
grep -c "stage:" .gitlab-ci.yml  # expect ≥ 12 jobs across 8 stages
```

---

## Task 9: Create agent-lint.py Quality Script

**Agent type**: general-purpose
**Isolation**: worktree
**Estimated time**: 20 min

**Objective**: Create a script that validates agent CRDs against quality standards, enforced in CI.

**Instructions**:
1. Create `scripts/agent-lint.py` that checks ALL agent CRDs in the repo:
   - YAML parses correctly
   - Required fields present: `apiVersion`, `kind: Agent`, `metadata.name`, `spec.declarative.systemMessage`, `spec.declarative.tools`
   - systemMessage > 100 characters
   - Every `mcpServer` tool ref has explicit `toolNames` (CRITICAL — pods crash without this)
   - `modelConfig` references a known ModelConfig name
   - Labels include `app.kubernetes.io/version`
   - No hardcoded URLs in systemMessage (should use tool calls instead)
   - No TODO/FIXME in systemMessage
2. Accept `--strict` flag for CI (exit 1 on any warning)
3. Accept `--fix` flag to auto-add missing labels
4. Output: JSON report with per-agent pass/fail and reasons
5. Use only stdlib + pyyaml (no heavy deps)

**Verification**:
```bash
python3 scripts/agent-lint.py --strict
# Should pass for all current agents or report specific failures
```

---

## Task 10: Seed Secrets Script Update

**Agent type**: general-purpose
**Isolation**: worktree
**Estimated time**: 15 min

**Objective**: Update `scripts/seed-secrets.sh` to create all MCP server secrets and kagent secrets.

**Instructions**:
1. Read current `scripts/seed-secrets.sh`
2. Add creation of these secrets (reading from `~/work/envs/secrets.env`):
   - `mcp-langfuse-env` (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)
   - `mcp-minio-env` (MINIO_ROOT_USER, MINIO_ROOT_PASSWORD)
   - `mcp-plane-env` (PLANE_API_KEY from PLANE_API_TOKEN)
   - `mcp-gitlab-env` (GITLAB_PERSONAL_ACCESS_TOKEN from GITLAB_PAT)
   - `mcp-n8n-env` (N8N_API_KEY)
   - `kagent-litellm` (OPENAI_API_KEY=sk-litellm-mewtoo-local) if not already present
   - `langfuse-api-keys` (public-key, secret-key) for OTEL auth if needed
3. Support `--force` flag to recreate existing secrets
4. Support `--namespace` flag (default: genai) for multi-namespace deployment
5. Idempotent: running twice should not error

**Verification**:
```bash
bash scripts/seed-secrets.sh --force
kubectl get secrets -n genai | grep -E 'mcp-|kagent-|langfuse-'  # all present
```

---

## Task Dependencies

```
Task 1  (MCP secrets)     ──┐
Task 2  (ModelConfigs)     ──┼── Task 5 (Delete old charts)
Task 10 (Seed script)     ──┘         │
                                       ├── Task 6 (Rewrite agents)
Task 3  (OTEL→Langfuse)              │         │
                                       │         ├── Task 7 (CronJobs)
Task 4  (Namespaces)      ────────────┘         │
                                                  ├── Task 8 (GitLab CI)
Task 9  (agent-lint.py)   ──────────────────────┘
```

**Parallel group 1** (no deps): Tasks 1, 2, 3, 4, 9, 10
**Parallel group 2** (after group 1): Tasks 5, 6
**Parallel group 3** (after group 2): Tasks 7, 8

---

## Completion Checklist

After all tasks complete, run the full regression checklist from spec 032 section 11:

```bash
# All MCPServers Ready
kubectl get mcpservers -n genai --no-headers | grep -c True  # 9

# All Agents Ready
kubectl get agents.kagent.dev -n genai --no-headers | wc -l  # 8

# MCP federation
curl -s gateway.platform.127.0.0.1.nip.io/mcp/all -X POST \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq '.result.tools | length'  # 243

# A2A invoke
curl -s -X POST gateway.platform.127.0.0.1.nip.io/api/a2a/genai/k8s-agent \
  -H 'Content-Type: application/json' \
  -d '{"message":{"role":"user","parts":[{"text":"what is 2+2?"}]}}'  # responds

# CronJobs
kubectl get cronjobs -n genai --no-headers | wc -l  # 6

# Old charts gone
ls charts/genai-mcp-* 2>/dev/null && echo FAIL || echo PASS

# Transpiler gone
ls scripts/agentspec-to-kagent.py 2>/dev/null && echo FAIL || echo PASS

# Namespaces exist
kubectl get ns genai-dev genai-stage  # both present

# CI pipeline valid
python3 -c "import yaml; yaml.safe_load(open('.gitlab-ci.yml'))"  # no errors
```

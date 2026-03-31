#!/usr/bin/env bash
# Seed agentregistry with platform agents, MCP servers, and skills.
# Uses the agentregistry v0 REST API.
#
# Usage: ./scripts/seed-registry.sh [URL]
#   Default: http://localhost:12121 (via port-forward)
#   k3d:     REGISTRY_URL=http://genai-agentregistry.genai.svc.cluster.local:12121

set -euo pipefail

API="${REGISTRY_URL:-${1:-http://localhost:12121}}/v0"

echo "=== Seeding agentregistry at ${API} ==="

# Health check
if ! curl -sf "${API}/health" > /dev/null 2>&1; then
  echo "ERROR: Registry not reachable at ${API}"
  echo "Hint: kubectl port-forward -n genai svc/genai-agentregistry 12121:12121"
  exit 1
fi

# ── Helper ──────────────────────────────────────────────
post() {
  local endpoint="$1"
  local data="$2"
  local name
  name=$(echo "$data" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name','?'))" 2>/dev/null)
  local resp
  resp=$(curl -s -w "\n%{http_code}" -X POST "${API}${endpoint}" \
    -H "Content-Type: application/json" -d "$data" 2>/dev/null)
  local code
  code=$(echo "$resp" | tail -1)
  if [ "$code" = "200" ] || [ "$code" = "201" ] || [ "$code" = "400" ] || [ "$code" = "409" ]; then
    echo "  ✓ ${name} (${code})"
  else
    echo "  ✗ ${name} (${code})"
  fi
}

# ── Agents ──────────────────────────────────────────────
echo ""
echo "--- Agents (6) ---"

# MCP URL helper
MCP="http://genai-mcp-{}.genai.svc.cluster.local:3000/mcp"
mcp() { echo "{\"type\":\"url\",\"name\":\"mcp-$1\",\"url\":\"http://genai-mcp-$1.genai.svc.cluster.local:3000/mcp\"}"; }
kagent_mcp() { echo "{\"type\":\"url\",\"name\":\"kagent-tools\",\"url\":\"http://genai-kagent-tools.genai.svc.cluster.local:8084/mcp\"}"; }

post /agents "{
  \"name\": \"raas.mlops\",
  \"version\": \"0.1.0\",
  \"title\": \"MLOps Agent\",
  \"description\": \"MLOps engineer — experiment tracking, model lifecycle, monitoring\",
  \"framework\": \"kagent\",
  \"image\": \"ghcr.io/kagent-dev/kagent:v0.8.0\",
  \"language\": \"python\",
  \"modelProvider\": \"ollama\",
  \"modelName\": \"qwen2.5:14b\",
  \"mcpServers\": [$(mcp kubernetes),$(mcp mlflow),$(mcp langfuse),$(mcp minio),$(mcp ollama)]
}"

post /agents "{
  \"name\": \"raas.developer\",
  \"version\": \"0.1.0\",
  \"title\": \"Developer Agent\",
  \"description\": \"Software developer — code generation, review, security scanning, CI/CD\",
  \"framework\": \"kagent\",
  \"image\": \"ghcr.io/kagent-dev/kagent:v0.8.0\",
  \"language\": \"python\",
  \"modelProvider\": \"ollama\",
  \"modelName\": \"qwen2.5:14b\",
  \"mcpServers\": [$(mcp kubernetes),$(mcp gitlab)]
}"

post /agents "{
  \"name\": \"raas.platform-admin\",
  \"version\": \"0.1.0\",
  \"title\": \"Platform Admin Agent\",
  \"description\": \"Infrastructure watchdog — k8s health, incident response, capacity management\",
  \"framework\": \"kagent\",
  \"image\": \"ghcr.io/kagent-dev/kagent:v0.8.0\",
  \"language\": \"python\",
  \"modelProvider\": \"ollama\",
  \"modelName\": \"qwen2.5:14b\",
  \"mcpServers\": [$(mcp kubernetes),$(mcp gitlab),$(mcp ollama)]
}"

post /agents "{
  \"name\": \"raas.data-engineer\",
  \"version\": \"0.1.0\",
  \"title\": \"Data Engineer Agent\",
  \"description\": \"Data catalog, lineage, quality checks, ingestion pipelines\",
  \"framework\": \"kagent\",
  \"image\": \"ghcr.io/kagent-dev/kagent:v0.8.0\",
  \"language\": \"python\",
  \"modelProvider\": \"ollama\",
  \"modelName\": \"qwen2.5:14b\",
  \"mcpServers\": [$(mcp kubernetes),$(mcp minio),$(mcp mlflow)]
}"

post /agents "{
  \"name\": \"raas.project-coordinator\",
  \"version\": \"0.1.0\",
  \"title\": \"Project Coordinator Agent\",
  \"description\": \"Backlog triage, sprint management, status reporting, issue tracking\",
  \"framework\": \"kagent\",
  \"image\": \"ghcr.io/kagent-dev/kagent:v0.8.0\",
  \"language\": \"python\",
  \"modelProvider\": \"ollama\",
  \"modelName\": \"qwen2.5:14b\",
  \"mcpServers\": [$(mcp kubernetes),$(mcp plane),$(mcp gitlab)]
}"

post /agents "{
  \"name\": \"raas.qa-eval\",
  \"version\": \"0.1.0\",
  \"title\": \"QA & Eval Agent\",
  \"description\": \"Benchmarks, regression detection, prompt evaluation, quality gates\",
  \"framework\": \"kagent\",
  \"image\": \"ghcr.io/kagent-dev/kagent:v0.8.0\",
  \"language\": \"python\",
  \"modelProvider\": \"ollama\",
  \"modelName\": \"qwen2.5:14b\",
  \"mcpServers\": [$(mcp kubernetes),$(mcp mlflow),$(mcp langfuse)]
}"

# ── MCP Servers ─────────────────────────────────────────
echo ""
echo "--- MCP Servers (9) ---"

for server in \
  "mcp-kubernetes|Kubernetes MCP Server|kubectl operations, pod logs, exec, resource management" \
  "mcp-gitlab|GitLab MCP Server|GitLab repos, merge requests, pipelines, issues" \
  "mcp-mlflow|MLflow MCP Server|Experiment tracking, runs, metrics, model registry" \
  "mcp-langfuse|Langfuse MCP Server|LLM observability — traces, scores, usage, cost" \
  "mcp-minio|MinIO MCP Server|S3-compatible object storage — buckets, objects, artifacts" \
  "mcp-ollama|Ollama MCP Server|Model management — pull, delete, VRAM info, inference" \
  "mcp-plane|Plane MCP Server|Project management — issues, labels, cycles, sprints" \
  "mcp-n8n|n8n MCP Server|Workflow automation — workflow CRUD, execution, node docs" \
  "mcp-odd-platform|ODD Platform MCP Server|Data catalog — search, lineage, quality, schema"; do

  IFS='|' read -r name title desc <<< "$server"

  post /servers "{
    \"\$schema\": \"2025-10-17\",
    \"name\": \"raas/${name}\",
    \"version\": \"0.1.0\",
    \"title\": \"${title}\",
    \"description\": \"${desc}\"
  }"
done

# ── Skills ──────────────────────────────────────────────
echo ""
echo "--- Skills (21) ---"

for skill in \
  "kubernetes-ops|Kubernetes Operations" \
  "mlflow-tracking|MLflow Tracking" \
  "langfuse-ops|Langfuse Operations" \
  "artifact-ops|Artifact Operations" \
  "model-management|Model Management" \
  "n8n-workflow-ops|n8n Workflow Operations" \
  "code-generation|Code Generation" \
  "documentation|Documentation" \
  "security-audit|Security Audit" \
  "benchmark-runner|Benchmark Runner" \
  "data-ingestion|Data Ingestion" \
  "prompt-engineering|Prompt Engineering" \
  "agent-management|Agent Management" \
  "skill-management|Skill Management" \
  "vector-store-ops|Vector Store Operations" \
  "dev-sandbox|Dev Sandbox" \
  "gitlab-pipeline-ops|GitLab Pipeline Operations" \
  "issue-triage|Issue Triage" \
  "sprint-management|Sprint Management" \
  "test-generation|Test Generation"; do

  IFS='|' read -r name title <<< "$skill"

  post /skills "{
    \"name\": \"${name}\",
    \"version\": \"0.1.0\",
    \"title\": \"${title}\",
    \"description\": \"Platform skill: ${title}\",
    \"category\": \"platform\"
  }"
done

# ── Summary ─────────────────────────────────────────────
echo ""
echo "=== Registry seeded ==="
curl -s "${API}/agents" 2>/dev/null | python3 -c "import sys,json; print(f'  Agents:  {json.load(sys.stdin)[\"metadata\"][\"count\"]}')" 2>/dev/null
curl -s "${API}/servers" 2>/dev/null | python3 -c "import sys,json; print(f'  Servers: {json.load(sys.stdin)[\"metadata\"][\"count\"]}')" 2>/dev/null
curl -s "${API}/skills" 2>/dev/null | python3 -c "import sys,json; print(f'  Skills:  {json.load(sys.stdin)[\"metadata\"][\"count\"]}')" 2>/dev/null

#!/usr/bin/env bash
# datahub-ingest.sh — Register DataHub ingestion sources for k3d platform
#
# Creates PostgreSQL ingestion sources for:
#   1. n8n — workflow execution metadata
#   2. MLflow — experiment tracking metadata
#   3. Langfuse — observability metadata
#
# Uses DataHub GMS GraphQL API. Safe to re-run (creates new sources).

set -euo pipefail

GMS_URL="${DATAHUB_GMS_URL:-http://datahub-gms.genai.127.0.0.1.nip.io}"
GMS_INTERNAL="http://genai-datahub-datahub-gms.genai.svc.cluster.local:8080"

echo "DataHub Ingestion Setup"
echo "  GMS URL: ${GMS_URL}"
echo ""

# Wait for GMS
echo "Waiting for DataHub GMS..."
for i in $(seq 1 20); do
  HTTP=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 3 "${GMS_URL}/config" 2>/dev/null || echo "000")
  [ "$HTTP" = "200" ] && break
  sleep 3
done

if [ "$HTTP" != "200" ]; then
  echo "ERROR: DataHub GMS not reachable at ${GMS_URL}"
  exit 1
fi
echo "  ✓ GMS is healthy."
echo ""

# Check if sources already exist
EXISTING=$(curl -sf -X POST "${GMS_URL}/api/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ listIngestionSources(input: {start: 0, count: 20}) { ingestionSources { name } } }"}' 2>/dev/null \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(s['name'] for s in d.get('data',{}).get('listIngestionSources',{}).get('ingestionSources',[])))" 2>/dev/null || echo "")

create_source() {
  local name="$1"
  local host_port="$2"
  local database="$3"
  local username="$4"
  local password="$5"

  if echo "${EXISTING}" | grep -qw "${name}"; then
    echo "  ⊘ ${name} already exists — skipping"
    return
  fi

  local recipe="source:\\n  type: postgres\\n  config:\\n    host_port: ${host_port}\\n    database: ${database}\\n    username: ${username}\\n    password: ${password}\\n    database_alias: ${database}\\n    platform_instance: k3d-mewtwo\\nsink:\\n  type: datahub-rest\\n  config:\\n    server: ${GMS_INTERNAL}"

  local resp
  resp=$(curl -sf -X POST "${GMS_URL}/api/graphql" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"mutation createIngestionSource(\$input: UpdateIngestionSourceInput!) { createIngestionSource(input: \$input) }\", \"variables\": {\"input\": {\"name\": \"${name}\", \"type\": \"postgres\", \"config\": {\"recipe\": \"${recipe}\", \"executorId\": \"default\"}, \"schedule\": {\"interval\": \"0 */6 * * *\", \"timezone\": \"UTC\"}}}}" 2>&1) || true

  if echo "${resp}" | grep -q 'createIngestionSource'; then
    echo "  ✓ ${name}"
  else
    echo "  ✗ ${name} — ${resp:0:200}"
  fi
}

echo "Registering ingestion sources..."
create_source "postgres-n8n"      "genai-pg-n8n.genai.svc.cluster.local:5432"            "n8n"      "n8n"      "n8n"
create_source "postgres-mlflow"   "genai-pg-mlflow.genai.svc.cluster.local:5432"         "mlflow"   "mlflow"   "mlflow"
create_source "postgres-langfuse" "genai-langfuse-postgresql.genai.svc.cluster.local:5432" "langfuse" "langfuse" "langfuse"
echo ""
echo "Done. View at: http://datahub.genai.127.0.0.1.nip.io/ingestion"

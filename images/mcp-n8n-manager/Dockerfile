###############################################################################
# n8n-mcp-server (manager) — Workflow CRUD, execution, webhooks
#
# Runs @leonardsellem/n8n-mcp-server in stdio mode. The MCP gateway manages
# container lifecycle, transport (SSE/streaming), and health monitoring.
#
# Tools: list_workflows, get_workflow, create_workflow, update_workflow,
#        delete_workflow, activate/deactivate_workflow, list_executions,
#        get_execution, run_webhook
#
# Requires env: N8N_API_URL, N8N_API_KEY
#
# Build: docker build -t genai-mcp-n8n-manager -f n8n-manager.Dockerfile .
###############################################################################
# node:22-alpine
FROM node:25-alpine@sha256:cf38e1f3c28ac9d81cdc0c51d8220320b3b618780e44ef96a39f76f7dbfef023

RUN npm install -g @leonardsellem/n8n-mcp-server@1.0.9

RUN adduser -D -u 1001 appuser
USER 1001

CMD ["n8n-mcp-server"]

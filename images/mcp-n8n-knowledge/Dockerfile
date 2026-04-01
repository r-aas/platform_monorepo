###############################################################################
# n8n-mcp (knowledge) — Node reference, template search, validation
#
# Runs n8n-mcp in stdio mode. The MCP gateway manages container lifecycle,
# transport (SSE/streaming), and health monitoring.
#
# Tools: search_nodes, get_node, validate_node, search_templates, get_template,
#        validate_workflow, n8n_create_workflow, n8n_list_workflows, etc.
#
# Build: docker build -t genai-mcp-n8n-knowledge -f n8n-knowledge.Dockerfile .
###############################################################################
# node:22-alpine
FROM node:25-alpine@sha256:cf38e1f3c28ac9d81cdc0c51d8220320b3b618780e44ef96a39f76f7dbfef023

RUN npm install -g n8n-mcp@0.1.3

RUN adduser -D -u 1001 appuser
USER 1001

CMD ["n8n-mcp"]

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
FROM node:22-alpine

RUN npm install -g n8n-mcp@latest

CMD ["n8n-mcp"]

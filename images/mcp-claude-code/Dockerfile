###############################################################################
# Claude Code MCP Server — file ops, bash execution, code search
#
# Runs claude mcp serve in stdio mode. The MCP gateway manages container
# lifecycle, transport (SSE/streaming), and health monitoring.
#
# Tools: Bash, Read, Write, Edit, LS, GrepTool, GlobTool, Replace
#
# Requires env: ANTHROPIC_API_KEY
#
# Build: docker build -t genai-mcp-claude-code -f claude-code.Dockerfile .
###############################################################################
FROM node:22-alpine

RUN apk add --no-cache bash git \
    && npm install -g @anthropic-ai/claude-code

CMD ["claude", "mcp", "serve"]

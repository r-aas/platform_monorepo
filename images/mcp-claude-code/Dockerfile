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
# node:22-alpine
FROM node:22-alpine@sha256:4d64b49e6c891c8fc821007cb1cdc6c0db7773110ac2c34bf2e6960adef62ed3

RUN apk add --no-cache bash git \
    && npm install -g @anthropic-ai/claude-code@1.0.33

RUN adduser -D -u 1001 appuser
USER 1001

CMD ["claude", "mcp", "serve"]

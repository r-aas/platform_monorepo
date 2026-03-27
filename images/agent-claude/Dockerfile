# Agent Claude — Claude Code CLI in a container for k8s Job execution.
#
# The entrypoint:
# 1. Reads workspace config from /workspace/.claude-config/
# 2. Writes CLAUDE.md, skills, MCP settings to working directory
# 3. Runs `claude --print` with the task message
# 4. Outputs result as JSON on last line of stdout
#
# Build: docker build -t agent-claude:latest images/agent-claude/
FROM node:22-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl jq python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Non-root user with writable workspace
RUN useradd -m -s /bin/bash agent \
    && mkdir -p /home/agent/workspace /home/agent/.claude \
    && chown -R agent:agent /home/agent

WORKDIR /home/agent/workspace

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER agent

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

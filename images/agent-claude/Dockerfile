# Agent Claude — Claude Code CLI in a container for k8s Job execution.
#
# The entrypoint:
# 1. Reads workspace config from /workspace/.claude-config/
# 2. Writes CLAUDE.md, skills, MCP settings to working directory
# 3. Runs `claude --print` with the task message
# 4. Outputs result as JSON on last line of stdout
#
# Build: docker build -t agent-claude:latest images/agent-claude/
# node:22-slim
FROM node:22-slim@sha256:80fdb3f57c815e1b638d221f30a826823467c4a56c8f6a8d7aa091cd9b1675ea

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl jq python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code@1.0.33

# Non-root user with writable workspace
RUN useradd -m -s /bin/bash agent \
    && mkdir -p /home/agent/workspace /home/agent/.claude \
    && chown -R agent:agent /home/agent

WORKDIR /home/agent/workspace

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER agent

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

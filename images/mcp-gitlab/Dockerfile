###############################################################################
# GitLab MCP Server — project management, file ops, merge requests
#
# Runs @modelcontextprotocol/server-gitlab in stdio mode. The MCP gateway
# manages container lifecycle, transport (SSE/streaming), and health monitoring.
#
# Tools: create_branch, create_issue, create_merge_request,
#        create_or_update_file, create_repository, fork_repository,
#        get_file_contents, push_files, search_repositories
#
# Requires env: GITLAB_PERSONAL_ACCESS_TOKEN, GITLAB_API_URL
# Optional env: GITLAB_HOST (hostname for /etc/hosts → host-gateway)
#
# Build: docker build -t genai-mcp-gitlab -f gitlab.Dockerfile .
###############################################################################
FROM node:22-alpine

RUN npm install -g @modelcontextprotocol/server-gitlab

# Entrypoint script: if GITLAB_HOST is set, add /etc/hosts entry
# pointing it to the Docker host gateway (host.docker.internal resolution).
# This fixes nip.io domains that resolve to 127.0.0.1 from inside containers.
COPY <<'ENTRY' /entrypoint.sh
#!/bin/sh
if [ -n "$GITLAB_HOST" ]; then
  # Resolve host.docker.internal to get the Docker host IP.
  # Alpine lacks getent — use ping which is always available in busybox.
  HOST_IP=$(ping -c1 -W1 host.docker.internal 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  if [ -n "$HOST_IP" ]; then
    echo "$HOST_IP $GITLAB_HOST" >> /etc/hosts
  fi
fi
exec mcp-server-gitlab "$@"
ENTRY

RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

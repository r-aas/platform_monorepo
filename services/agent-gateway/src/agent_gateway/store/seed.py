"""Seed default MCP servers for k3d cluster."""

from __future__ import annotations

import logging

from agent_gateway.store.mcp_servers import list_mcp_servers, upsert_mcp_server

logger = logging.getLogger(__name__)

DEFAULT_SERVERS = [
    {
        "name": "kubernetes",
        "url": "http://genai-mcp-kubernetes.genai.svc.cluster.local:3000/mcp",
        "transport": "streamable-http",
        "namespace": "platform",
        "description": "Kubernetes cluster management — kubectl operations, pod logs, exec",
    },
    {
        "name": "gitlab",
        "url": "http://genai-mcp-gitlab.genai.svc.cluster.local:3000/mcp",
        "transport": "streamable-http",
        "namespace": "platform",
        "description": "GitLab repository, MR, and pipeline management",
    },
    {
        "name": "n8n",
        "url": "http://genai-mcp-n8n.genai.svc.cluster.local:3000/mcp",
        "transport": "streamable-http",
        "namespace": "orchestration",
        "description": "n8n workflow management and execution",
        "auth_token": "n8n-mcp-k3d-token",
    },
    {
        "name": "datahub",
        "url": "http://genai-mcp-datahub.genai.svc.cluster.local:8000/mcp",
        "transport": "streamable-http",
        "namespace": "data",
        "description": "DataHub metadata catalog — datasets, pipelines, lineage",
    },
    {
        "name": "plane",
        "url": "http://genai-mcp-plane.genai.svc.cluster.local:3000/mcp",
        "transport": "streamable-http",
        "namespace": "project-management",
        "description": "Plane CE project management — issues, labels, cycles, sprints",
    },
]


async def seed_default_servers() -> int:
    """Seed/update default MCP servers. Upserts are idempotent."""
    count = 0
    for srv in DEFAULT_SERVERS:
        try:
            await upsert_mcp_server(**srv)
            count += 1
            logger.info("Seeded MCP server: %s → %s", srv["name"], srv["url"])
        except Exception as e:
            logger.warning("Failed to seed MCP server %s: %s", srv["name"], e)
    return count

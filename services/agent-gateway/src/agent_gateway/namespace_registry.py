"""MetaMCP namespace registry — generic MCP server registration from YAML config.

C.04: Register data pipeline MCP servers into the MetaMCP "data" namespace.

Pattern mirrors metamcp_client.py (gateway registration) but is driven by
a declarative YAML config rather than hardcoded settings. Any namespace can
be seeded by dropping a YAML file and calling register_namespace_servers().

YAML format (namespaces/{name}.yaml):
  namespace: data
  servers:
    - name: postgres-mcp
      description: "PostgreSQL operations"
      url: "http://genai-postgres-mcp.genai.svc.cluster.local:8080/mcp"
      type: streamable-http   # optional, default: streamable-http
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from agent_gateway.config import settings


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class NamespaceMCPServer:
    name: str
    description: str
    url: str
    type: str = "streamable-http"


# ---------------------------------------------------------------------------
# Config loader (pure — file I/O only)
# ---------------------------------------------------------------------------


def load_namespace_config(config_path: Path) -> list[NamespaceMCPServer]:
    """Load MCP server definitions from a namespace YAML config file.

    Returns empty list if file not found or invalid — never raises.
    """
    try:
        raw = config_path.read_text()
        data = yaml.safe_load(raw)
        servers = data.get("servers", [])
        return [
            NamespaceMCPServer(
                name=s["name"],
                description=s.get("description", ""),
                url=s["url"],
                type=s.get("type", "streamable-http"),
            )
            for s in servers
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# MetaMCP registration (async — tRPC I/O)
# ---------------------------------------------------------------------------


async def register_namespace_servers(
    namespace: str,
    servers: list[NamespaceMCPServer],
) -> bool:
    """Register MCP servers into a MetaMCP namespace.

    For each server: create if new, update if exists, then assign to namespace.
    Returns True on success, False if not configured or on any error.
    Never raises — failures are non-fatal for gateway startup.
    """
    if not settings.metamcp_user_email or not settings.metamcp_user_password:
        return False

    if not servers:
        return True  # Nothing to register is a no-op success

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Authenticate
            resp = await client.post(
                f"{settings.metamcp_admin_url}/api/auth/sign-in/email",
                json={"email": settings.metamcp_user_email, "password": settings.metamcp_user_password},
            )
            resp.raise_for_status()
            cookie_header = resp.headers.get("set-cookie", "")
            token = next(
                (p.split("=", 1)[1] for p in cookie_header.split(";") if "better-auth.session_token=" in p),
                "",
            )
            cookie = f"better-auth.session_token={token}"

            # List existing servers
            srv_resp = await client.get(
                f"{settings.metamcp_admin_url}/trpc/frontend/frontend.mcpServers.list",
                headers={"Cookie": cookie},
            )
            srv_resp.raise_for_status()
            existing = {s["name"]: s["uuid"] for s in srv_resp.json()["result"]["data"]["data"]}

            # Upsert each server, collect UUIDs
            registered_uuids: list[str] = []
            for srv in servers:
                payload = {
                    "name": srv.name,
                    "description": srv.description,
                    "url": srv.url,
                    "type": srv.type,
                }
                if srv.name in existing:
                    uuid = existing[srv.name]
                    await client.post(
                        f"{settings.metamcp_admin_url}/trpc/frontend/frontend.mcpServers.update",
                        json={**payload, "uuid": uuid},
                        headers={"Cookie": cookie},
                    )
                else:
                    create_resp = await client.post(
                        f"{settings.metamcp_admin_url}/trpc/frontend/frontend.mcpServers.create",
                        json=payload,
                        headers={"Cookie": cookie},
                    )
                    create_resp.raise_for_status()
                    uuid = create_resp.json()["result"]["data"]["data"]["uuid"]
                registered_uuids.append(uuid)

            # Assign to namespace (preserving existing assignments)
            ns_resp = await client.get(
                f"{settings.metamcp_admin_url}/trpc/frontend/frontend.namespaces.list",
                headers={"Cookie": cookie},
            )
            ns_resp.raise_for_status()
            ns_by_name = {ns["name"]: ns for ns in ns_resp.json()["result"]["data"]["data"]}

            if namespace in ns_by_name:
                ns = ns_by_name[namespace]
                current_uuids = [s["uuid"] for s in ns.get("mcpServers", [])]
                new_uuids = current_uuids + [u for u in registered_uuids if u not in current_uuids]
                await client.post(
                    f"{settings.metamcp_admin_url}/trpc/frontend/frontend.namespaces.update",
                    json={"uuid": ns["uuid"], "name": namespace, "mcpServerUuids": new_uuids},
                    headers={"Cookie": cookie},
                )

        return True

    except Exception:
        return False

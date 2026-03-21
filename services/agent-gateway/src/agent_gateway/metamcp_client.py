"""MetaMCP tRPC client — registers the gateway as an MCP server.

Uses the same tRPC API pattern as the genai-metamcp Helm chart's seed job.
Endpoint: http://{metamcp_admin_url}/trpc/frontend/{procedure}

Registration flow:
  1. Sign in → session cookie
  2. List existing MCP servers → create or update gateway entry
  3. List namespaces → assign gateway server to target namespace
"""

from __future__ import annotations

import httpx

from agent_gateway.config import settings


async def _sign_in(client: httpx.AsyncClient) -> str:
    """Authenticate to MetaMCP backend. Returns session cookie string."""
    resp = await client.post(
        f"{settings.metamcp_admin_url}/api/auth/sign-in/email",
        json={"email": settings.metamcp_user_email, "password": settings.metamcp_user_password},
    )
    resp.raise_for_status()
    cookie_header = resp.headers.get("set-cookie", "")
    token = next(
        (part.split("=", 1)[1] for part in cookie_header.split(";") if "better-auth.session_token=" in part),
        "",
    )
    return f"better-auth.session_token={token}"


async def _trpc_get(client: httpx.AsyncClient, procedure: str, cookie: str) -> dict:
    resp = await client.get(
        f"{settings.metamcp_admin_url}/trpc/frontend/{procedure}",
        headers={"Cookie": cookie},
    )
    resp.raise_for_status()
    return resp.json()


async def _trpc_post(client: httpx.AsyncClient, procedure: str, data: dict, cookie: str) -> dict:
    resp = await client.post(
        f"{settings.metamcp_admin_url}/trpc/frontend/{procedure}",
        json=data,
        headers={"Cookie": cookie},
    )
    resp.raise_for_status()
    return resp.json()


async def register_gateway_server() -> bool:
    """Register the gateway MCP server in MetaMCP genai namespace.

    Returns True on success, False if not configured or on any error.
    Never raises — failures are non-fatal for gateway startup.
    """
    if not settings.metamcp_user_email or not settings.metamcp_user_password:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            cookie = await _sign_in(client)

            # Upsert the gateway MCP server
            srv_resp = await _trpc_get(client, "frontend.mcpServers.list", cookie)
            existing = {s["name"]: s["uuid"] for s in srv_resp["result"]["data"]["data"]}

            server_payload = {
                "name": settings.gateway_mcp_name,
                "description": "Agent Gateway — manage agents and skills via MCP",
                "url": settings.gateway_mcp_url,
                "type": "streamable-http",
            }

            if settings.gateway_mcp_name in existing:
                server_uuid = existing[settings.gateway_mcp_name]
                await _trpc_post(client, "frontend.mcpServers.update", {**server_payload, "uuid": server_uuid}, cookie)
            else:
                resp = await _trpc_post(client, "frontend.mcpServers.create", server_payload, cookie)
                server_uuid = resp["result"]["data"]["data"]["uuid"]

            # Assign to target namespace (preserving existing server assignments)
            ns_resp = await _trpc_get(client, "frontend.namespaces.list", cookie)
            ns_by_name = {ns["name"]: ns for ns in ns_resp["result"]["data"]["data"]}

            if settings.metamcp_namespace in ns_by_name:
                ns = ns_by_name[settings.metamcp_namespace]
                current_uuids = [s["uuid"] for s in ns.get("mcpServers", [])]
                if server_uuid not in current_uuids:
                    await _trpc_post(
                        client,
                        "frontend.namespaces.update",
                        {"uuid": ns["uuid"], "name": settings.metamcp_namespace, "mcpServerUuids": current_uuids + [server_uuid]},
                        cookie,
                    )
                else:
                    # Already assigned — still call update to keep namespace in sync
                    await _trpc_post(
                        client,
                        "frontend.namespaces.update",
                        {"uuid": ns["uuid"], "name": settings.metamcp_namespace, "mcpServerUuids": current_uuids},
                        cookie,
                    )

        return True

    except Exception:
        return False

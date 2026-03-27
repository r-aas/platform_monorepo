"""MCP server registry CRUD operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from agent_gateway.store.db import McpServerRow, async_session


async def list_mcp_servers() -> list[McpServerRow]:
    async with async_session() as session:
        result = await session.execute(select(McpServerRow))
        return list(result.scalars().all())


async def get_mcp_server(name: str) -> McpServerRow:
    async with async_session() as session:
        row = (await session.execute(
            select(McpServerRow).where(McpServerRow.name == name)
        )).scalar_one_or_none()
    if not row:
        raise KeyError(f"MCP server '{name}' not found")
    return row


async def upsert_mcp_server(*, name: str, url: str, transport: str = "streamable-http",
                            namespace: str = "default", description: str = "",
                            auth_token: str = "") -> McpServerRow:
    async with async_session() as session:
        existing = (await session.execute(
            select(McpServerRow).where(McpServerRow.name == name)
        )).scalar_one_or_none()
        if existing:
            existing.url = url
            existing.transport = transport
            existing.namespace = namespace
            existing.description = description
            existing.auth_token = auth_token
            existing.updated_at = datetime.utcnow()
            row = existing
        else:
            row = McpServerRow(
                id=str(uuid.uuid4()),
                name=name,
                url=url,
                transport=transport,
                namespace=namespace,
                description=description,
                auth_token=auth_token,
            )
            session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def delete_mcp_server(name: str) -> None:
    async with async_session() as session:
        row = (await session.execute(
            select(McpServerRow).where(McpServerRow.name == name)
        )).scalar_one_or_none()
        if not row:
            raise KeyError(f"MCP server '{name}' not found")
        await session.delete(row)
        await session.commit()


async def update_server_health(name: str, status: str, tools: list[dict] | None = None) -> None:
    async with async_session() as session:
        row = (await session.execute(
            select(McpServerRow).where(McpServerRow.name == name)
        )).scalar_one_or_none()
        if row:
            row.health_status = status
            row.last_health_check = datetime.utcnow()
            if tools is not None:
                row.tools_cache = tools
            await session.commit()

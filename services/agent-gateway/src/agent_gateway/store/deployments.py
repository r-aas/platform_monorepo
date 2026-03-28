"""Deployment heartbeat CRUD operations."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from agent_gateway.store.db import DeploymentRow, EvalRunRow, async_session


async def list_deployments(env: str | None = None) -> list[DeploymentRow]:
    async with async_session() as session:
        q = select(DeploymentRow)
        if env:
            q = q.where(DeploymentRow.environment == env)
        result = await session.execute(q)
        return list(result.scalars().all())


async def upsert_deployment(*, agent_name: str, environment: str, gateway_url: str,
                            agent_version: str = "", status: str = "unknown",
                            last_heartbeat=None, error_count_1h: int = 0) -> DeploymentRow:
    async with async_session() as session:
        existing = (await session.execute(
            select(DeploymentRow).where(
                DeploymentRow.agent_name == agent_name,
                DeploymentRow.environment == environment,
                DeploymentRow.gateway_url == gateway_url,
            )
        )).scalar_one_or_none()
        if existing:
            existing.status = status
            existing.agent_version = agent_version
            existing.last_heartbeat = last_heartbeat
            existing.error_count_1h = error_count_1h
            row = existing
        else:
            row = DeploymentRow(
                id=str(uuid.uuid4()),
                agent_name=agent_name,
                environment=environment,
                gateway_url=gateway_url,
                agent_version=agent_version,
                status=status,
                last_heartbeat=last_heartbeat,
                error_count_1h=error_count_1h,
            )
            session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def list_eval_runs(agent_name: str, limit: int = 20) -> list[EvalRunRow]:
    async with async_session() as session:
        result = await session.execute(
            select(EvalRunRow)
            .where(EvalRunRow.agent_name == agent_name)
            .order_by(EvalRunRow.run_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


async def insert_eval_run(
    *,
    agent_name: str,
    agent_version: str,
    environment: str,
    model: str,
    skill: str = "",
    task: str = "",
    pass_rate: float = 0.0,
    avg_latency_ms: float = 0.0,
    results: dict | None = None,
) -> EvalRunRow:
    """Persist a benchmark eval run to the database."""
    row = EvalRunRow(
        id=str(uuid.uuid4()),
        agent_name=agent_name,
        agent_version=agent_version,
        environment=environment,
        model=model,
        skill=skill,
        task=task,
        pass_rate=pass_rate,
        avg_latency_ms=avg_latency_ms,
        results=results or {},
    )
    async with async_session() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row

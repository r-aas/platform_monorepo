"""Agent promotion workflow — shadow → canary → primary.

Stages:
  shadow  — runs in parallel with primary, results discarded (evaluation)
  canary  — receives canary_weight% of traffic (default 10%)
  primary — default traffic target (100% minus canary)

Promotion flow:
  POST /agents/{name}/promote       — advance to next stage
  POST /agents/{name}/rollback      — revert to previous stage
  GET  /agents/{name}/promotion     — current promotion status
  PUT  /agents/{name}/canary-weight — set canary traffic percentage
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from agent_gateway.store.db import AgentRow, async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["promotions"])

STAGES = ["shadow", "canary", "primary"]


@router.get("/{name}/promotion")
async def get_promotion(name: str):
    """Get current promotion status for an agent."""
    async with async_session() as session:
        row = (await session.execute(
            select(AgentRow).where(AgentRow.name == name)
        )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, f"Agent '{name}' not found")
    return {
        "agent": name,
        "version": row.version,
        "stage": row.promotion_stage or "primary",
        "canary_weight": row.canary_weight or 0,
        "stages": STAGES,
    }


@router.post("/{name}/promote")
async def promote_agent(name: str):
    """Advance agent to next promotion stage.

    shadow → canary (10% traffic)
    canary → primary (100% traffic)
    primary → already at final stage
    """
    async with async_session() as session:
        row = (await session.execute(
            select(AgentRow).where(AgentRow.name == name)
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Agent '{name}' not found")

        current = row.promotion_stage or "primary"
        idx = STAGES.index(current) if current in STAGES else len(STAGES) - 1

        if idx >= len(STAGES) - 1:
            raise HTTPException(409, f"Agent '{name}' is already at '{current}' (final stage)")

        new_stage = STAGES[idx + 1]
        row.promotion_stage = new_stage

        if new_stage == "canary" and (row.canary_weight or 0) == 0:
            row.canary_weight = 10  # Default canary weight

        if new_stage == "primary":
            row.canary_weight = 0  # Primary gets all traffic

        await session.commit()
        await session.refresh(row)

    logger.info("Promoted agent '%s' from %s → %s", name, current, new_stage)
    return {
        "agent": name,
        "previous_stage": current,
        "stage": new_stage,
        "canary_weight": row.canary_weight or 0,
    }


@router.post("/{name}/rollback")
async def rollback_agent(name: str):
    """Revert agent to previous promotion stage.

    primary → canary
    canary → shadow
    shadow → already at first stage
    """
    async with async_session() as session:
        row = (await session.execute(
            select(AgentRow).where(AgentRow.name == name)
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Agent '{name}' not found")

        current = row.promotion_stage or "primary"
        idx = STAGES.index(current) if current in STAGES else 0

        if idx <= 0:
            raise HTTPException(409, f"Agent '{name}' is already at '{current}' (first stage)")

        new_stage = STAGES[idx - 1]
        row.promotion_stage = new_stage

        if new_stage == "shadow":
            row.canary_weight = 0

        await session.commit()
        await session.refresh(row)

    logger.info("Rolled back agent '%s' from %s → %s", name, current, new_stage)
    return {
        "agent": name,
        "previous_stage": current,
        "stage": new_stage,
        "canary_weight": row.canary_weight or 0,
    }


@router.put("/{name}/canary-weight")
async def set_canary_weight(name: str, data: dict[str, Any]):
    """Set the canary traffic weight (0-100)."""
    weight = data.get("weight", 0)
    if not isinstance(weight, int) or weight < 0 or weight > 100:
        raise HTTPException(400, "weight must be an integer 0-100")

    async with async_session() as session:
        row = (await session.execute(
            select(AgentRow).where(AgentRow.name == name)
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Agent '{name}' not found")

        if (row.promotion_stage or "primary") != "canary":
            raise HTTPException(409, f"Agent '{name}' is at '{row.promotion_stage}', not 'canary'")

        row.canary_weight = weight
        await session.commit()
        await session.refresh(row)

    return {"agent": name, "stage": "canary", "canary_weight": weight}

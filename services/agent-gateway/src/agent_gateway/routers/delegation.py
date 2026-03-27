"""Agent-to-agent delegation protocol."""

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent_gateway.composer import compose
from agent_gateway.registry import get_agent
from agent_gateway.runtimes import get_runtime
from agent_gateway.skills_registry import get_skill

logger = logging.getLogger(__name__)

router = APIRouter()


class DelegationRequest(BaseModel):
    """Request to delegate a task from one agent to another."""

    from_agent: str
    task: str
    params: dict[str, Any] = {}


class DelegationResult(BaseModel):
    """Result of an agent-to-agent delegation."""

    from_agent: str
    to_agent: str
    task: str
    result: str
    success: bool
    error: str | None = None


@router.post("/v1/agents/{to_agent}/delegate", response_model=DelegationResult)
async def delegate_to_agent(to_agent: str, body: DelegationRequest):
    """Delegate a task to a named agent and return its result synchronously."""
    try:
        agent = await get_agent(to_agent)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "message": f"Agent '{to_agent}' not found",
                    "type": "invalid_request_error",
                    "code": "agent_not_found",
                }
            },
        )

    # Resolve skills — skip missing ones gracefully
    resolved_skills = []
    for skill_name in agent.skills:
        try:
            resolved_skills.append(await get_skill(skill_name))
        except (KeyError, Exception):
            logger.warning(
                "Skill '%s' not found for delegated agent '%s' — skipping",
                skill_name,
                to_agent,
            )

    run_config = compose(
        agent=agent,
        skills=resolved_skills,
        message=body.task,
        params=body.params,
    )

    try:
        runtime = get_runtime(agent.runtime)
    except ValueError:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": f"Runtime '{agent.runtime}' unavailable for agent '{to_agent}'",
                    "type": "server_error",
                    "code": "runtime_unavailable",
                }
            },
        )

    try:
        result = await runtime.invoke_sync(run_config)
    except Exception as exc:
        logger.exception("Delegation to '%s' failed: %s", to_agent, exc)
        return JSONResponse(
            status_code=200,
            content=DelegationResult(
                from_agent=body.from_agent,
                to_agent=to_agent,
                task=body.task,
                result="",
                success=False,
                error=str(exc),
            ).model_dump(),
        )

    return DelegationResult(
        from_agent=body.from_agent,
        to_agent=to_agent,
        task=body.task,
        result=result,
        success=True,
        error=None,
    )

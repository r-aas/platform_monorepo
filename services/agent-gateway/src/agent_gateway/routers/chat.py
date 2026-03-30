"""OpenAI-compatible chat completions router with canary + shadow support."""

import asyncio
import time
import uuid

import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent_gateway.composer import compose
from agent_gateway.config import settings
from agent_gateway.agent_lookup import get_agent
from agent_gateway.runtimes import get_runtime
from agent_gateway.skill_lookup import get_skill

logger = logging.getLogger(__name__)

router = APIRouter()


async def _run_shadow(agent_name: str, body: dict) -> None:
    """Fire-and-forget: invoke shadow agent variant, log result, discard.

    Shadow agents ('{name}-shadow' with promotion_stage='shadow') run in parallel
    with the primary. Their output is logged for comparison but never returned.
    """
    from agent_gateway.agent_lookup import _db_get_agent, _row_to_agent
    from agent_gateway.store.deployments import insert_eval_run

    shadow_name = f"{agent_name}-shadow"
    try:
        row = await _db_get_agent(shadow_name)
    except KeyError:
        return  # No shadow variant — nothing to do

    if (getattr(row, "promotion_stage", "") or "") != "shadow":
        return

    shadow_agent = _row_to_agent(row)
    t0 = time.monotonic()
    try:
        runtime = get_runtime(shadow_agent.runtime)
        run_config = compose(
            agent=shadow_agent,
            skills=[],
            message=body.get("messages", [{}])[-1].get("content", ""),
            params=body.get("agent_params", {}),
            session_id=body.get("session_id", ""),
        )
        content = await runtime.invoke_sync(run_config)
        latency = time.monotonic() - t0
        logger.info("Shadow %s completed in %.1fs", shadow_name, latency)

        # Record shadow result for later comparison
        await insert_eval_run(
            agent_name=shadow_name,
            agent_version=row.version or "latest",
            environment="k3d-mewtwo",
            model=f"agent:{shadow_name}",
            skill="shadow-compare",
            task="chat",
            pass_rate=1.0,  # Shadow always "passes" — we're collecting data
            avg_latency_ms=latency * 1000,
            results={"output": content[:2000], "primary_agent": agent_name},
        )
    except Exception:
        logger.warning("Shadow execution failed for %s", shadow_name, exc_info=True)


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "")
    stream = body.get("stream", True)

    # Agent routing
    if model.startswith("agent:"):
        agent_name = model.removeprefix("agent:")
        try:
            agent = await get_agent(agent_name)
        except KeyError:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "message": f"Agent '{agent_name}' not found",
                        "type": "invalid_request_error",
                        "code": "model_not_found",
                    }
                },
            )

        # Fire shadow execution in background (non-blocking)
        asyncio.create_task(_run_shadow(agent_name, body))

        messages = body.get("messages", [])
        user_message = messages[-1]["content"] if messages else ""
        agent_params = body.get("agent_params", {})

        # Resolve skills from registry — skip any that are missing
        resolved_skills = []
        for skill_name in agent.skills:
            try:
                resolved_skills.append(await get_skill(skill_name))
            except (KeyError, Exception):
                logger.warning("Skill '%s' not found for agent '%s' — skipping", skill_name, agent_name)

        run_config = compose(
            agent=agent,
            skills=resolved_skills,
            message=user_message,
            params=agent_params,
            session_id=body.get("session_id", ""),
        )

        try:
            runtime = get_runtime(agent.runtime)
        except ValueError:
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "message": f"Runtime '{agent.runtime}' unavailable for agent '{agent_name}'",
                        "type": "server_error",
                        "code": "runtime_unavailable",
                    }
                },
            )

        # Track which variant handled the request (canary observability)
        variant_headers = {
            "X-Agent-Variant": agent.name,
            "X-Agent-Stage": agent.promotion_stage or "primary",
        }

        if stream:
            return StreamingResponse(
                runtime.invoke(run_config),
                media_type="text/event-stream",
                headers=variant_headers,
            )
        else:
            content = await runtime.invoke_sync(run_config)
            return JSONResponse(
                {
                    "id": f"agw-{uuid.uuid4().hex[:12]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "system_fingerprint": f"agent:{agent_name}@v1",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                },
                headers=variant_headers,
            )

    # LiteLLM fallback (backward compat FR-006)
    return await _proxy_to_litellm(body)


async def _proxy_to_litellm(body: dict) -> JSONResponse:
    """Forward non-agent requests to LiteLLM unchanged."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.litellm_base_url}/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {settings.litellm_api_key}"} if settings.litellm_api_key else {},
        )
        return JSONResponse(status_code=resp.status_code, content=resp.json())

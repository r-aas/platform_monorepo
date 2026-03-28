"""OpenAI-compatible chat completions router."""

import time
import uuid

import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent_gateway.composer import compose
from agent_gateway.config import settings
from agent_gateway.registry import get_agent
from agent_gateway.runtimes import get_runtime
from agent_gateway.skills_registry import get_skill

logger = logging.getLogger(__name__)

router = APIRouter()


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

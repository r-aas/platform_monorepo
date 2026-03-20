"""n8n webhook runtime — forwards to n8n chat workflow."""

import json
from collections.abc import AsyncIterator

import httpx

from agent_gateway.config import settings
from agent_gateway.models import AgentRunConfig
from agent_gateway.runtimes.base import Runtime


class N8nRuntime(Runtime):
    """Execute agents via n8n webhook."""

    async def invoke(self, config: AgentRunConfig) -> AsyncIterator[str]:
        """Stream from n8n webhook, yield OpenAI SSE chunks."""
        url = f"{settings.n8n_base_url}/webhook/{config.workflow}"
        body = {"chatInput": config.message, "sessionId": config.session_id}

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=body) as resp:
                resp.raise_for_status()
                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    # n8n streams plain text or SSE — convert to OpenAI SSE format
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        # Strip SSE prefix if present
                        content = line.removeprefix("data: ").strip()
                        if content == "[DONE]":
                            yield "data: [DONE]\n\n"
                            return
                        yield _openai_chunk(config.agent_name, content)

                # Flush remaining
                if buffer.strip():
                    content = buffer.strip().removeprefix("data: ")
                    if content != "[DONE]":
                        yield _openai_chunk(config.agent_name, content)
                yield _openai_done_chunk()

    async def invoke_sync(self, config: AgentRunConfig) -> str:
        """Non-streaming invocation via n8n webhook."""
        url = f"{settings.n8n_base_url}/webhook/{config.workflow}"
        body = {"chatInput": config.message, "sessionId": config.session_id}

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            # n8n returns {"output": "..."} or plain text
            if isinstance(data, dict):
                return data.get("output", data.get("text", json.dumps(data)))
            return str(data)


def _openai_chunk(agent_name: str, content: str) -> str:
    chunk = {
        "object": "chat.completion.chunk",
        "model": f"agent:{agent_name}",
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def _openai_done_chunk() -> str:
    return "data: [DONE]\n\n"

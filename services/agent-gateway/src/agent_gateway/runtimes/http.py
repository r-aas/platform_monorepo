"""HTTP runtime — headless LLM client using OpenAI-compatible API."""

import logging
from collections.abc import AsyncIterator

import httpx

from agent_gateway.models import AgentRunConfig
from agent_gateway.runtimes.base import Runtime

logger = logging.getLogger(__name__)


class HttpRuntime(Runtime):
    """Execute agents via a direct OpenAI-compatible HTTP endpoint.

    Useful when no n8n workflow exists — calls the LLM specified in
    llm_config.url directly using the chat/completions API format.
    Claude Code uses this to invoke gateway agents without a workflow layer.
    """

    async def invoke(self, config: AgentRunConfig) -> AsyncIterator[str]:
        """Stream from LLM, yield OpenAI SSE chunks."""
        url, headers, body = self._build_request(config, stream=True)

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    if line.startswith("data: "):
                        payload = line[6:]
                    else:
                        payload = line
                    if payload == "[DONE]":
                        yield "data: [DONE]\n\n"
                        return
                    # Re-emit as OpenAI SSE
                    yield f"data: {payload}\n\n"
        yield "data: [DONE]\n\n"

    async def invoke_sync(self, config: AgentRunConfig) -> str:
        """Non-streaming call to LLM, return assistant content."""
        url, headers, body = self._build_request(config, stream=False)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    def _build_request(
        self, config: AgentRunConfig, stream: bool
    ) -> tuple[str, dict, dict]:
        if not config.llm_config.url:
            raise ValueError("HttpRuntime requires llm_config.url to be set")

        base_url = config.llm_config.url.rstrip("/")
        url = f"{base_url}/chat/completions"

        headers: dict[str, str] = {}
        if config.llm_config.api_key:
            headers["Authorization"] = f"Bearer {config.llm_config.api_key}"

        messages = []
        if config.system_prompt:
            messages.append({"role": "system", "content": config.system_prompt})
        if config.message:
            messages.append({"role": "user", "content": config.message})

        body = {
            "model": config.llm_config.model_id or "qwen2.5:14b",
            "messages": messages,
            "stream": stream,
        }
        return url, headers, body

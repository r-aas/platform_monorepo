from __future__ import annotations

import logging

import httpx

from bridge.config import settings
from bridge.models import N8nExecutionEvent

logger = logging.getLogger(__name__)


async def emit_execution_event(event: N8nExecutionEvent) -> dict:
    """Emit DataHub MCPs for an n8n execution event via REST."""
    mcps = event.to_mcps()
    results = {"emitted": 0, "errors": 0}

    async with httpx.AsyncClient(timeout=10.0) as client:
        headers = {}
        if settings.datahub_token:
            headers["Authorization"] = f"Bearer {settings.datahub_token}"

        for mcp in mcps:
            try:
                resp = await client.post(
                    f"{settings.datahub_gms_url}/aspects?action=ingestProposal",
                    json={"proposal": mcp},
                    headers=headers,
                )
                if resp.status_code < 300:
                    results["emitted"] += 1
                else:
                    logger.warning("GMS rejected MCP: %s %s", resp.status_code, resp.text[:200])
                    results["errors"] += 1
            except httpx.HTTPError as e:
                logger.error("Failed to emit MCP: %s", e)
                results["errors"] += 1

    return results

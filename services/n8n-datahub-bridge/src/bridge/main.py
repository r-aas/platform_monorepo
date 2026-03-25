from __future__ import annotations

import logging

from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse

from bridge.emitter import emit_execution_event
from bridge.models import N8nExecutionEvent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="n8n-DataHub Bridge", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/n8n")
async def receive_n8n_event(event: N8nExecutionEvent, background_tasks: BackgroundTasks):
    """Receive n8n execution webhook and emit DataHub lineage (non-blocking)."""
    logger.info("Received n8n event: workflow=%s execution=%s status=%s", event.workflow_name, event.execution_id, event.status)

    async def _emit():
        try:
            result = await emit_execution_event(event)
            logger.info("Emitted %d MCPs (%d errors) for execution %s", result["emitted"], result["errors"], event.execution_id)
        except Exception:
            logger.exception("Failed to emit MCPs for execution %s", event.execution_id)

    background_tasks.add_task(_emit)
    return JSONResponse({"accepted": True, "execution_id": event.execution_id}, status_code=202)

from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agent_gateway.config import settings
from agent_gateway.routers.agents import router as agents_router
from agent_gateway.routers.chat import router as chat_router
from agent_gateway.routers.delegation import router as delegation_router
from agent_gateway.routers.factory import router as factory_router
from agent_gateway.routers.promotions import router as promotions_router
from agent_gateway.routers.sandbox import router as sandbox_router
from agent_gateway.routers.schedule import router as schedule_router
from agent_gateway.routers.skills import router as skills_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize PostgreSQL tables
    from agent_gateway.store import init_db
    await init_db()
    logger.info("PostgreSQL store initialized")

    # Parallel startup: legacy tool discovery + MLflow init
    async def _legacy_discovery():
        from agent_gateway.mcp_discovery import index_all_tools
        await index_all_tools()

    async def _mlflow_init():
        import mlflow
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)

    startup_tasks = [_legacy_discovery(), _mlflow_init()]
    results = await asyncio.gather(*startup_tasks, return_exceptions=True)
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Startup task %d failed (non-fatal): %s", i, result)

    yield


app = FastAPI(title="Agent Gateway", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(delegation_router)
app.include_router(skills_router)
app.include_router(factory_router)
app.include_router(sandbox_router)
app.include_router(schedule_router)
app.include_router(promotions_router)


@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy"})


def cli():
    import uvicorn

    uvicorn.run("agent_gateway.main:app", host="0.0.0.0", port=settings.gateway_port, reload=True)

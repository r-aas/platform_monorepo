from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agent_gateway.config import settings
from agent_gateway.mcp_server import router as gateway_mcp_router
from agent_gateway.routers.agents import router as agents_router
from agent_gateway.routers.chat import router as chat_router
from agent_gateway.routers.delegation import router as delegation_router
from agent_gateway.routers.factory import router as factory_router
from agent_gateway.routers.mcp import router as mcp_router
from agent_gateway.routers.mcp_proxy import router as mcp_proxy_router
from agent_gateway.routers.promotions import router as promotions_router
from agent_gateway.routers.registry import router as registry_router
from agent_gateway.routers.sandbox import router as sandbox_router
from agent_gateway.routers.skills import router as skills_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize PostgreSQL tables
    from agent_gateway.store import init_db
    await init_db()
    logger.info("PostgreSQL store initialized")

    # Seed default MCP servers on first boot (must complete before tool refresh)
    try:
        from agent_gateway.store.seed import seed_default_servers
        count = await seed_default_servers()
        if count:
            logger.info("Seeded %d default MCP servers", count)
    except Exception as e:
        logger.warning("MCP server seeding failed (non-fatal): %s", e)

    # Parallel startup: refresh MCP tools + legacy discovery + MLflow init
    async def _refresh_mcp():
        from agent_gateway.mcp_proxy import refresh_tools
        tool_count = await refresh_tools(force=True)
        logger.info("MCP proxy initialized with %d tools", tool_count)

    async def _legacy_discovery():
        from agent_gateway.mcp_discovery import index_all_tools
        await index_all_tools()

    async def _mlflow_init():
        import mlflow
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)

    startup_tasks = [_refresh_mcp(), _legacy_discovery(), _mlflow_init()]
    results = await asyncio.gather(*startup_tasks, return_exceptions=True)
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Startup task %d failed (non-fatal): %s", i, result)

    yield

    # Shutdown: close persistent HTTP client
    try:
        from agent_gateway.mcp_proxy import close_http_client
        await close_http_client()
    except Exception:
        pass


app = FastAPI(title="Agent Gateway", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(delegation_router)
app.include_router(skills_router)
app.include_router(mcp_router)
app.include_router(gateway_mcp_router)
app.include_router(factory_router)
app.include_router(registry_router)
app.include_router(sandbox_router)
app.include_router(promotions_router)
app.include_router(mcp_proxy_router)


@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy"})


def cli():
    import uvicorn

    uvicorn.run("agent_gateway.main:app", host="0.0.0.0", port=settings.gateway_port, reload=True)

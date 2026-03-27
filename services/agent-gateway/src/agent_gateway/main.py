from contextlib import asynccontextmanager
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
from agent_gateway.routers.registry import router as registry_router
from agent_gateway.routers.skills import router as skills_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize PostgreSQL tables
    from agent_gateway.store import init_db
    await init_db()
    logger.info("PostgreSQL store initialized")

    # Seed default MCP servers on first boot
    try:
        from agent_gateway.store.seed import seed_default_servers
        count = await seed_default_servers()
        if count:
            logger.info("Seeded %d default MCP servers", count)
    except Exception as e:
        logger.warning("MCP server seeding failed (non-fatal): %s", e)

    # Refresh MCP proxy tool cache
    try:
        from agent_gateway.mcp_proxy import refresh_tools
        tool_count = await refresh_tools(force=True)
        logger.info("MCP proxy initialized with %d tools", tool_count)
    except Exception as e:
        logger.warning("MCP proxy refresh failed (non-fatal): %s", e)

    # Auto-discover MCP tools from LiteLLM (legacy, non-fatal)
    try:
        from agent_gateway.mcp_discovery import index_all_tools
        await index_all_tools()
    except Exception:
        pass

    # MLflow for factory/benchmark evals
    try:
        import mlflow
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    except Exception:
        pass

    yield


app = FastAPI(title="Agent Gateway", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(delegation_router)
app.include_router(skills_router)
app.include_router(mcp_router)
app.include_router(gateway_mcp_router)
app.include_router(factory_router)
app.include_router(registry_router)
app.include_router(mcp_proxy_router)


@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy"})


def cli():
    import uvicorn

    uvicorn.run("agent_gateway.main:app", host="0.0.0.0", port=settings.gateway_port, reload=True)

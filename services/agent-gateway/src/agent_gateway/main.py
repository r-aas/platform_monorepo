from contextlib import asynccontextmanager

import mlflow
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agent_gateway.config import settings
from agent_gateway.mcp_server import router as gateway_mcp_router
from agent_gateway.routers.agents import router as agents_router
from agent_gateway.routers.chat import router as chat_router
from agent_gateway.routers.mcp import router as mcp_router
from agent_gateway.routers.skills import router as skills_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    # Register gateway as MCP server in MetaMCP (non-fatal if unreachable)
    try:
        from agent_gateway.metamcp_client import register_gateway_server
        await register_gateway_server()
    except Exception:
        pass
    # Auto-discover and index all MCP tools from MetaMCP namespaces (non-fatal)
    try:
        from agent_gateway.mcp_discovery import index_all_tools
        await index_all_tools()
    except Exception:
        pass
    yield


app = FastAPI(title="Agent Gateway", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(skills_router)
app.include_router(mcp_router)
app.include_router(gateway_mcp_router)


@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy"})


@app.get("/health/detail")
async def health_detail():
    import asyncio

    def _check():
        mlflow_status = "disconnected"
        agents_loaded = 0
        try:
            client = mlflow.MlflowClient()
            prompts = client.search_prompts(filter_string="name LIKE 'agent:%'")
            agents_loaded = len(prompts)
            mlflow_status = "connected"
        except Exception:
            pass
        return {"status": "healthy", "mlflow": mlflow_status, "agents_loaded": agents_loaded}

    result = await asyncio.to_thread(_check)
    return JSONResponse(result)


def cli():
    import uvicorn

    uvicorn.run("agent_gateway.main:app", host="0.0.0.0", port=settings.gateway_port, reload=True)

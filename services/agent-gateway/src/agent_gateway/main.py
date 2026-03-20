from contextlib import asynccontextmanager

import mlflow
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agent_gateway.config import settings
from agent_gateway.routers.agents import router as agents_router
from agent_gateway.routers.chat import router as chat_router
from agent_gateway.routers.mcp import router as mcp_router
from agent_gateway.routers.skills import router as skills_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    yield


app = FastAPI(title="Agent Gateway", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(skills_router)
app.include_router(mcp_router)


@app.get("/health")
async def health():
    mlflow_status = "disconnected"
    agents_loaded = 0
    try:
        client = mlflow.MlflowClient()
        prompts = client.search_prompts(filter_string="name LIKE 'agent:%'")
        agents_loaded = len(prompts)
        mlflow_status = "connected"
    except Exception:
        pass
    return JSONResponse({"status": "healthy", "mlflow": mlflow_status, "agents_loaded": agents_loaded})


def cli():
    import uvicorn

    uvicorn.run("agent_gateway.main:app", host="0.0.0.0", port=settings.gateway_port, reload=True)

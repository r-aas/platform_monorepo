"""MCP server for Ollama — local LLM model management.

Exposes Ollama's management API as MCP tools so agents can:
- List/pull/delete models
- Check running models and VRAM usage
- Get model details and parameters
- Monitor inference load

Requires: OLLAMA_HOST
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://192.168.65.254:11434")

mcp = FastMCP("Ollama Model Management", host="0.0.0.0", port=3000)


async def _get(path: str) -> Any:
    async with httpx.AsyncClient(base_url=OLLAMA_HOST, timeout=60) as c:
        r = await c.get(path)
        r.raise_for_status()
        return r.json()


async def _post(path: str, data: dict | None = None) -> Any:
    async with httpx.AsyncClient(base_url=OLLAMA_HOST, timeout=300) as c:
        r = await c.post(path, json=data or {})
        r.raise_for_status()
        return r.json()


async def _delete(path: str, data: dict) -> Any:
    async with httpx.AsyncClient(base_url=OLLAMA_HOST, timeout=60) as c:
        r = await c.request("DELETE", path, json=data)
        r.raise_for_status()
        return r.json()


# ── Models ──


@mcp.tool()
async def list_models() -> list[dict]:
    """List all locally available models with size and modification date."""
    data = await _get("/api/tags")
    return [
        {
            "name": m["name"],
            "size_gb": round(m.get("size", 0) / 1_073_741_824, 2),
            "parameter_size": m.get("details", {}).get("parameter_size", ""),
            "quantization": m.get("details", {}).get("quantization_level", ""),
            "family": m.get("details", {}).get("family", ""),
            "modified_at": m.get("modified_at", ""),
        }
        for m in data.get("models", [])
    ]


@mcp.tool()
async def show_model(name: str) -> dict:
    """Get detailed information about a model.

    Args:
        name: Model name (e.g. "qwen2.5:14b", "nomic-embed-text")
    """
    data = await _post("/api/show", {"name": name})
    return {
        "name": name,
        "modelfile": data.get("modelfile", "")[:500],
        "parameters": data.get("parameters", ""),
        "template": data.get("template", "")[:300],
        "details": data.get("details", {}),
        "model_info": {
            k: v for k, v in data.get("model_info", {}).items()
            if k in [
                "general.architecture", "general.parameter_count",
                "general.quantization_version", "general.file_type",
            ]
        },
    }


@mcp.tool()
async def running_models() -> list[dict]:
    """List models currently loaded in memory with VRAM usage."""
    data = await _get("/api/ps")
    return [
        {
            "name": m["name"],
            "size_gb": round(m.get("size", 0) / 1_073_741_824, 2),
            "vram_gb": round(m.get("size_vram", 0) / 1_073_741_824, 2),
            "processor": m.get("details", {}).get("processor", ""),
            "expires_at": m.get("expires_at", ""),
        }
        for m in data.get("models", [])
    ]


@mcp.tool()
async def pull_model(name: str) -> dict:
    """Pull (download) a model from the Ollama registry.

    This may take several minutes for large models. The response indicates
    whether the pull was initiated successfully.

    Args:
        name: Model name to pull (e.g. "qwen2.5:14b", "llama3.2:3b")
    """
    async with httpx.AsyncClient(base_url=OLLAMA_HOST, timeout=600) as c:
        r = await c.post("/api/pull", json={"name": name, "stream": False})
        r.raise_for_status()
        return {"name": name, "status": r.json().get("status", "success")}


@mcp.tool()
async def delete_model(name: str) -> dict:
    """Delete a model from local storage.

    Args:
        name: Model name to delete
    """
    await _delete("/api/delete", {"name": name})
    return {"name": name, "deleted": True}


@mcp.tool()
async def copy_model(source: str, destination: str) -> dict:
    """Copy a model to a new name (for creating variants).

    Args:
        source: Source model name
        destination: New model name
    """
    await _post("/api/copy", {"source": source, "destination": destination})
    return {"source": source, "destination": destination, "copied": True}


# ── Health & Status ──


@mcp.tool()
async def ollama_status() -> dict:
    """Check Ollama server status, loaded models, and resource usage."""
    try:
        models = await _get("/api/tags")
        running = await _get("/api/ps")
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}

    total_size = sum(m.get("size", 0) for m in models.get("models", []))
    loaded_vram = sum(m.get("size_vram", 0) for m in running.get("models", []))

    return {
        "status": "healthy",
        "total_models": len(models.get("models", [])),
        "total_storage_gb": round(total_size / 1_073_741_824, 2),
        "loaded_models": len(running.get("models", [])),
        "loaded_vram_gb": round(loaded_vram / 1_073_741_824, 2),
        "models_loaded": [m["name"] for m in running.get("models", [])],
    }


@mcp.tool()
async def generate_test(name: str, prompt: str = "Say hello in one word.") -> dict:
    """Send a quick test prompt to verify a model works.

    Args:
        name: Model name to test
        prompt: Short test prompt (default: "Say hello in one word.")
    """
    import time

    start = time.time()
    async with httpx.AsyncClient(base_url=OLLAMA_HOST, timeout=120) as c:
        r = await c.post(
            "/api/generate",
            json={"model": name, "prompt": prompt, "stream": False},
        )
        r.raise_for_status()
        data = r.json()
    elapsed = time.time() - start

    return {
        "model": name,
        "response": data.get("response", "")[:200],
        "total_duration_ms": round(data.get("total_duration", 0) / 1_000_000, 1),
        "eval_count": data.get("eval_count", 0),
        "wall_time_s": round(elapsed, 2),
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

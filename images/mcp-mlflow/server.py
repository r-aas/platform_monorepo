"""MCP server for MLflow — experiment tracking and model registry tools.

Exposes MLflow's REST API as MCP tools so agents can:
- Search/create experiments
- Search/inspect runs, log metrics and params
- Manage registered models and versions
- Compare runs side-by-side

Requires: MLFLOW_TRACKING_URI
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")

mcp = FastMCP("MLflow Experiment Tracking", host="0.0.0.0", port=3000)


async def _get(path: str, params: dict | None = None) -> Any:
    async with httpx.AsyncClient(base_url=MLFLOW_URI, timeout=30) as c:
        r = await c.get(path, params=params)
        r.raise_for_status()
        return r.json()


async def _post(path: str, data: dict) -> Any:
    async with httpx.AsyncClient(base_url=MLFLOW_URI, timeout=30) as c:
        r = await c.post(path, json=data)
        r.raise_for_status()
        return r.json()


# ── Experiments ──


@mcp.tool()
async def list_experiments(max_results: int = 100) -> list[dict]:
    """List all MLflow experiments.

    Args:
        max_results: Maximum number of experiments to return (default 100)
    """
    data = await _get("/api/2.0/mlflow/experiments/search", {"max_results": max_results})
    return [
        {
            "experiment_id": e["experiment_id"],
            "name": e["name"],
            "lifecycle_stage": e.get("lifecycle_stage", ""),
            "artifact_location": e.get("artifact_location", ""),
        }
        for e in data.get("experiments", [])
    ]


@mcp.tool()
async def get_experiment(experiment_id: str) -> dict:
    """Get experiment details by ID.

    Args:
        experiment_id: MLflow experiment ID
    """
    data = await _get("/api/2.0/mlflow/experiments/get", {"experiment_id": experiment_id})
    return data.get("experiment", data)


@mcp.tool()
async def create_experiment(name: str, artifact_location: str = "") -> dict:
    """Create a new experiment.

    Args:
        name: Experiment name (must be unique)
        artifact_location: Optional S3/local path for artifacts
    """
    payload: dict[str, Any] = {"name": name}
    if artifact_location:
        payload["artifact_location"] = artifact_location
    return await _post("/api/2.0/mlflow/experiments/create", payload)


# ── Runs ──


@mcp.tool()
async def search_runs(
    experiment_ids: list[str],
    filter_string: str = "",
    max_results: int = 50,
    order_by: str = "start_time DESC",
) -> list[dict]:
    """Search runs across experiments with optional filters.

    Args:
        experiment_ids: List of experiment IDs to search
        filter_string: MLflow filter expression (e.g. "metrics.rmse < 0.5")
        max_results: Max runs to return (default 50)
        order_by: Sort order (default "start_time DESC")
    """
    payload: dict[str, Any] = {
        "experiment_ids": experiment_ids,
        "max_results": max_results,
        "order_by": [order_by],
    }
    if filter_string:
        payload["filter"] = filter_string
    data = await _post("/api/2.0/mlflow/runs/search", payload)
    return [
        {
            "run_id": r["info"]["run_id"],
            "experiment_id": r["info"]["experiment_id"],
            "status": r["info"]["status"],
            "start_time": r["info"].get("start_time"),
            "end_time": r["info"].get("end_time"),
            "metrics": {m["key"]: m["value"] for m in r["data"].get("metrics", [])},
            "params": {p["key"]: p["value"] for p in r["data"].get("params", [])},
            "tags": {t["key"]: t["value"] for t in r["data"].get("tags", [])},
        }
        for r in data.get("runs", [])
    ]


@mcp.tool()
async def get_run(run_id: str) -> dict:
    """Get full details of a specific run.

    Args:
        run_id: MLflow run ID
    """
    data = await _get("/api/2.0/mlflow/runs/get", {"run_id": run_id})
    return data.get("run", data)


@mcp.tool()
async def create_run(experiment_id: str, run_name: str = "", tags: dict[str, str] | None = None) -> dict:
    """Start a new run in an experiment.

    Args:
        experiment_id: Experiment to create run in
        run_name: Optional human-readable name
        tags: Optional key-value tags
    """
    payload: dict[str, Any] = {"experiment_id": experiment_id}
    tag_list = []
    if run_name:
        tag_list.append({"key": "mlflow.runName", "value": run_name})
    if tags:
        tag_list.extend({"key": k, "value": v} for k, v in tags.items())
    if tag_list:
        payload["tags"] = tag_list
    data = await _post("/api/2.0/mlflow/runs/create", payload)
    return data.get("run", data)


@mcp.tool()
async def log_metric(run_id: str, key: str, value: float, step: int = 0) -> dict:
    """Log a metric value for a run.

    Args:
        run_id: Run ID to log metric to
        key: Metric name (e.g. "accuracy", "latency_p99")
        value: Metric value
        step: Step number (default 0)
    """
    return await _post(
        "/api/2.0/mlflow/runs/log-metric",
        {"run_id": run_id, "key": key, "value": value, "step": step},
    )


@mcp.tool()
async def log_param(run_id: str, key: str, value: str) -> dict:
    """Log a parameter for a run.

    Args:
        run_id: Run ID to log param to
        key: Parameter name
        value: Parameter value (string)
    """
    return await _post(
        "/api/2.0/mlflow/runs/log-parameter",
        {"run_id": run_id, "key": key, "value": value},
    )


@mcp.tool()
async def log_batch(
    run_id: str,
    metrics: list[dict] | None = None,
    params: list[dict] | None = None,
) -> dict:
    """Log multiple metrics and params in a single call.

    Args:
        run_id: Run ID
        metrics: List of {"key": str, "value": float, "step": int}
        params: List of {"key": str, "value": str}
    """
    payload: dict[str, Any] = {"run_id": run_id}
    if metrics:
        payload["metrics"] = metrics
    if params:
        payload["params"] = params
    return await _post("/api/2.0/mlflow/runs/log-batch", payload)


@mcp.tool()
async def end_run(run_id: str, status: str = "FINISHED") -> dict:
    """End a run with a final status.

    Args:
        run_id: Run ID to end
        status: Final status — FINISHED, FAILED, or KILLED
    """
    return await _post(
        "/api/2.0/mlflow/runs/update",
        {"run_id": run_id, "status": status, "end_time": int(__import__("time").time() * 1000)},
    )


# ── Registered Models ──


@mcp.tool()
async def list_registered_models(max_results: int = 100) -> list[dict]:
    """List all registered models in the model registry.

    Args:
        max_results: Max models to return
    """
    data = await _get(
        "/api/2.0/mlflow/registered-models/search",
        {"max_results": max_results},
    )
    return [
        {
            "name": m["name"],
            "description": m.get("description", ""),
            "latest_versions": [
                {"version": v["version"], "stage": v.get("current_stage", ""), "status": v.get("status", "")}
                for v in m.get("latest_versions", [])
            ],
        }
        for m in data.get("registered_models", [])
    ]


@mcp.tool()
async def get_model_version(name: str, version: str) -> dict:
    """Get details of a specific model version.

    Args:
        name: Registered model name
        version: Version number
    """
    data = await _get(
        "/api/2.0/mlflow/model-versions/get",
        {"name": name, "version": version},
    )
    return data.get("model_version", data)


@mcp.tool()
async def compare_runs(run_ids: list[str]) -> list[dict]:
    """Compare metrics and params across multiple runs.

    Args:
        run_ids: List of run IDs to compare (2-10)
    """
    results = []
    for rid in run_ids[:10]:
        data = await _get("/api/2.0/mlflow/runs/get", {"run_id": rid})
        run = data.get("run", {})
        results.append({
            "run_id": rid,
            "status": run.get("info", {}).get("status", ""),
            "metrics": {m["key"]: m["value"] for m in run.get("data", {}).get("metrics", [])},
            "params": {p["key"]: p["value"] for p in run.get("data", {}).get("params", [])},
        })
    return results


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

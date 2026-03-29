"""MCP server for Langfuse — LLM observability and trace analysis.

Exposes Langfuse's API as MCP tools so agents can:
- Query traces, observations, and scores
- Analyze token usage and costs
- Review session histories
- Check generation quality metrics

Requires: LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

LANGFUSE_URL = os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000")
LANGFUSE_PK = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SK = os.environ.get("LANGFUSE_SECRET_KEY", "")

mcp = FastMCP("Langfuse Observability", host="0.0.0.0", port=3000)


def _auth_headers() -> dict[str, str]:
    creds = base64.b64encode(f"{LANGFUSE_PK}:{LANGFUSE_SK}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}


async def _get(path: str, params: dict | None = None) -> Any:
    async with httpx.AsyncClient(base_url=LANGFUSE_URL, timeout=30) as c:
        r = await c.get(path, headers=_auth_headers(), params=params)
        r.raise_for_status()
        return r.json()


# ── Traces ──


@mcp.tool()
async def list_traces(
    limit: int = 50,
    name: str = "",
    user_id: str = "",
    session_id: str = "",
    order_by: str = "timestamp.desc",
) -> list[dict]:
    """List recent traces with optional filters.

    Args:
        limit: Max traces to return (default 50)
        name: Filter by trace name
        user_id: Filter by user ID
        session_id: Filter by session ID
        order_by: Sort order (default "timestamp.desc")
    """
    params: dict[str, Any] = {"limit": limit, "orderBy": order_by}
    if name:
        params["name"] = name
    if user_id:
        params["userId"] = user_id
    if session_id:
        params["sessionId"] = session_id
    data = await _get("/api/public/traces", params)
    return [
        {
            "id": t["id"],
            "name": t.get("name", ""),
            "session_id": t.get("sessionId"),
            "user_id": t.get("userId"),
            "timestamp": t.get("timestamp"),
            "latency_ms": t.get("latency"),
            "input_tokens": t.get("usage", {}).get("input", 0) if t.get("usage") else 0,
            "output_tokens": t.get("usage", {}).get("output", 0) if t.get("usage") else 0,
            "total_cost": t.get("calculatedTotalCost"),
            "tags": t.get("tags", []),
        }
        for t in data.get("data", [])
    ]


@mcp.tool()
async def get_trace(trace_id: str) -> dict:
    """Get full trace details including all observations.

    Args:
        trace_id: Langfuse trace ID
    """
    return await _get(f"/api/public/traces/{trace_id}")


# ── Observations ──


@mcp.tool()
async def list_observations(
    trace_id: str = "",
    name: str = "",
    type: str = "",
    limit: int = 50,
) -> list[dict]:
    """List observations (spans, generations, events).

    Args:
        trace_id: Filter by parent trace ID
        name: Filter by observation name
        type: Filter by type — GENERATION, SPAN, or EVENT
        limit: Max results (default 50)
    """
    params: dict[str, Any] = {"limit": limit}
    if trace_id:
        params["traceId"] = trace_id
    if name:
        params["name"] = name
    if type:
        params["type"] = type
    data = await _get("/api/public/observations", params)
    return [
        {
            "id": o["id"],
            "trace_id": o.get("traceId"),
            "name": o.get("name", ""),
            "type": o.get("type", ""),
            "model": o.get("model"),
            "start_time": o.get("startTime"),
            "end_time": o.get("endTime"),
            "input_tokens": o.get("usage", {}).get("input", 0) if o.get("usage") else 0,
            "output_tokens": o.get("usage", {}).get("output", 0) if o.get("usage") else 0,
            "total_cost": o.get("calculatedTotalCost"),
            "status": o.get("statusMessage"),
        }
        for o in data.get("data", [])
    ]


@mcp.tool()
async def get_observation(observation_id: str) -> dict:
    """Get full observation details including input/output.

    Args:
        observation_id: Langfuse observation ID
    """
    return await _get(f"/api/public/observations/{observation_id}")


# ── Scores ──


@mcp.tool()
async def list_scores(
    trace_id: str = "",
    name: str = "",
    limit: int = 50,
) -> list[dict]:
    """List scores (quality ratings, evaluations).

    Args:
        trace_id: Filter by trace ID
        name: Filter by score name (e.g. "quality", "helpfulness")
        limit: Max results (default 50)
    """
    params: dict[str, Any] = {"limit": limit}
    if trace_id:
        params["traceId"] = trace_id
    if name:
        params["name"] = name
    data = await _get("/api/public/scores", params)
    return [
        {
            "id": s["id"],
            "trace_id": s.get("traceId"),
            "observation_id": s.get("observationId"),
            "name": s.get("name", ""),
            "value": s.get("value"),
            "comment": s.get("comment"),
            "timestamp": s.get("timestamp"),
        }
        for s in data.get("data", [])
    ]


# ── Sessions ──


@mcp.tool()
async def list_sessions(limit: int = 50) -> list[dict]:
    """List conversation sessions.

    Args:
        limit: Max sessions to return (default 50)
    """
    data = await _get("/api/public/sessions", {"limit": limit})
    return [
        {
            "id": s["id"],
            "created_at": s.get("createdAt"),
            "traces_count": s.get("countTraces", 0),
        }
        for s in data.get("data", [])
    ]


@mcp.tool()
async def get_session(session_id: str) -> dict:
    """Get session details with all traces.

    Args:
        session_id: Langfuse session ID
    """
    return await _get(f"/api/public/sessions/{session_id}")


# ── Aggregations ──


@mcp.tool()
async def usage_summary(
    trace_name: str = "",
    last_n_hours: int = 24,
) -> dict:
    """Get token usage and cost summary for recent traces.

    Args:
        trace_name: Filter by trace name (empty = all)
        last_n_hours: Look back period in hours (default 24)
    """
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(hours=last_n_hours)).isoformat()
    params: dict[str, Any] = {"limit": 500, "fromTimestamp": since}
    if trace_name:
        params["name"] = trace_name
    data = await _get("/api/public/traces", params)
    traces = data.get("data", [])

    total_input = 0
    total_output = 0
    total_cost = 0.0
    models: dict[str, int] = {}

    for t in traces:
        usage = t.get("usage") or {}
        total_input += usage.get("input", 0) or 0
        total_output += usage.get("output", 0) or 0
        total_cost += t.get("calculatedTotalCost") or 0.0

    return {
        "period_hours": last_n_hours,
        "trace_count": len(traces),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_cost_usd": round(total_cost, 6),
    }


@mcp.tool()
async def error_traces(last_n_hours: int = 24, limit: int = 20) -> list[dict]:
    """Find traces with errors or low scores in the recent period.

    Args:
        last_n_hours: Look back period (default 24)
        limit: Max results (default 20)
    """
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(hours=last_n_hours)).isoformat()
    params: dict[str, Any] = {"limit": limit, "fromTimestamp": since}
    data = await _get("/api/public/traces", params)

    errors = []
    for t in data.get("data", []):
        tags = t.get("tags", [])
        if "error" in tags or t.get("level") == "ERROR":
            errors.append({
                "id": t["id"],
                "name": t.get("name", ""),
                "timestamp": t.get("timestamp"),
                "tags": tags,
            })
    return errors


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

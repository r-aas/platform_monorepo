"""MCP server for Plane CE — project management tools for AI agents.

Exposes Plane's REST API as MCP tools so agents can:
- List/create/update issues
- Manage labels, states, cycles
- Search and filter work items
- Add comments

Requires: PLANE_API_URL, PLANE_API_TOKEN, PLANE_WORKSPACE_SLUG
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# Config
PLANE_API_URL = os.environ.get("PLANE_API_URL", "http://plane.genai.127.0.0.1.nip.io")
PLANE_API_TOKEN = os.environ.get("PLANE_API_TOKEN", "")
PLANE_WORKSPACE = os.environ.get("PLANE_WORKSPACE_SLUG", "r-aas")

mcp = FastMCP("Plane Project Management", host="0.0.0.0", port=3000)

# --- HTTP client ---


def _headers() -> dict[str, str]:
    return {
        "x-api-key": PLANE_API_TOKEN,
        "Content-Type": "application/json",
    }


def _base(project_id: str | None = None) -> str:
    base = f"{PLANE_API_URL}/api/v1/workspaces/{PLANE_WORKSPACE}"
    if project_id:
        base += f"/projects/{project_id}"
    return base


async def _get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(path, headers=_headers())
        r.raise_for_status()
        return r.json()


async def _post(path: str, data: dict) -> Any:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(path, headers=_headers(), json=data)
        r.raise_for_status()
        return r.json()


async def _patch(path: str, data: dict) -> Any:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.patch(path, headers=_headers(), json=data)
        r.raise_for_status()
        return r.json()


async def _delete(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.delete(path, headers=_headers())
        r.raise_for_status()
        return {"deleted": True}


# --- Projects ---


@mcp.tool()
async def list_projects() -> list[dict]:
    """List all projects in the workspace.

    Returns project id, name, identifier, description, and member count.
    """
    data = await _get(f"{_base()}/projects/")
    results = data.get("results", data) if isinstance(data, dict) else data
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "identifier": p["identifier"],
            "description": p.get("description_text", ""),
            "members": p.get("total_members", 0),
        }
        for p in results
    ]


@mcp.tool()
async def get_project(project_id: str) -> dict:
    """Get project details by ID.

    Args:
        project_id: UUID of the project
    """
    return await _get(f"{_base()}/projects/{project_id}/")


# --- States ---


@mcp.tool()
async def list_states(project_id: str) -> list[dict]:
    """List workflow states for a project (Backlog, Todo, In Progress, Done, Cancelled).

    Args:
        project_id: UUID of the project
    """
    data = await _get(f"{_base(project_id)}/states/")
    results = data.get("results", data) if isinstance(data, dict) else data
    return [
        {"id": s["id"], "name": s["name"], "group": s.get("group", ""), "color": s.get("color", "")}
        for s in results
    ]


# --- Labels ---


@mcp.tool()
async def list_labels(project_id: str) -> list[dict]:
    """List issue labels for a project.

    Args:
        project_id: UUID of the project
    """
    data = await _get(f"{_base(project_id)}/labels/")
    results = data.get("results", data) if isinstance(data, dict) else data
    return [{"id": l["id"], "name": l["name"], "color": l.get("color", "")} for l in results]


@mcp.tool()
async def create_label(project_id: str, name: str, color: str = "#6366f1") -> dict:
    """Create a new issue label.

    Args:
        project_id: UUID of the project
        name: Label name (e.g. "bug", "feature", "infra")
        color: Hex color code (default: indigo)
    """
    return await _post(f"{_base(project_id)}/labels/", {"name": name, "color": color})


# --- Issues ---


@mcp.tool()
async def list_issues(
    project_id: str,
    state_group: str = "",
    label_id: str = "",
    assignee_id: str = "",
    priority: str = "",
) -> list[dict]:
    """List issues in a project with optional filters.

    Args:
        project_id: UUID of the project
        state_group: Filter by state group: backlog, unstarted, started, completed, cancelled
        label_id: Filter by label UUID
        assignee_id: Filter by assignee UUID
        priority: Filter by priority: urgent, high, medium, low, none
    """
    url = f"{_base(project_id)}/issues/"
    params = {}
    if state_group:
        params["state__group"] = state_group
    if label_id:
        params["label"] = label_id
    if assignee_id:
        params["assignee"] = assignee_id
    if priority:
        params["priority"] = priority

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers=_headers(), params=params)
        r.raise_for_status()
        data = r.json()

    results = data.get("results", data) if isinstance(data, dict) else data
    return [
        {
            "id": i["id"],
            "sequence_id": i.get("sequence_id"),
            "name": i.get("name", ""),
            "state_id": i.get("state"),
            "priority": i.get("priority"),
            "assignees": i.get("assignees", []),
            "labels": i.get("labels", []),
            "created_at": i.get("created_at", ""),
        }
        for i in results
    ]


@mcp.tool()
async def get_issue(project_id: str, issue_id: str) -> dict:
    """Get full issue details including description.

    Args:
        project_id: UUID of the project
        issue_id: UUID of the issue
    """
    return await _get(f"{_base(project_id)}/issues/{issue_id}/")


@mcp.tool()
async def create_issue(
    project_id: str,
    name: str,
    description_text: str = "",
    state_id: str = "",
    priority: str = "medium",
    label_ids: list[str] | None = None,
    assignee_ids: list[str] | None = None,
) -> dict:
    """Create a new issue in a project.

    Args:
        project_id: UUID of the project
        name: Issue title
        description_text: Plain text description
        state_id: UUID of the state (use list_states to find IDs)
        priority: urgent, high, medium, low, or none
        label_ids: List of label UUIDs to attach
        assignee_ids: List of user UUIDs to assign
    """
    payload: dict[str, Any] = {
        "name": name,
        "priority": priority,
    }
    if description_text:
        payload["description_text"] = description_text
    if state_id:
        payload["state"] = state_id
    if label_ids:
        payload["labels"] = label_ids
    if assignee_ids:
        payload["assignees"] = assignee_ids
    return await _post(f"{_base(project_id)}/issues/", payload)


@mcp.tool()
async def update_issue(
    project_id: str,
    issue_id: str,
    name: str = "",
    description_text: str = "",
    state_id: str = "",
    priority: str = "",
    label_ids: list[str] | None = None,
    assignee_ids: list[str] | None = None,
) -> dict:
    """Update an existing issue. Only provided fields are changed.

    Args:
        project_id: UUID of the project
        issue_id: UUID of the issue
        name: New title (optional)
        description_text: New description (optional)
        state_id: New state UUID (optional)
        priority: New priority (optional)
        label_ids: New label UUIDs (replaces existing, optional)
        assignee_ids: New assignee UUIDs (replaces existing, optional)
    """
    payload: dict[str, Any] = {}
    if name:
        payload["name"] = name
    if description_text:
        payload["description_text"] = description_text
    if state_id:
        payload["state"] = state_id
    if priority:
        payload["priority"] = priority
    if label_ids is not None:
        payload["labels"] = label_ids
    if assignee_ids is not None:
        payload["assignees"] = assignee_ids
    if not payload:
        return {"error": "No fields to update"}
    return await _patch(f"{_base(project_id)}/issues/{issue_id}/", payload)


# --- Comments ---


@mcp.tool()
async def list_comments(project_id: str, issue_id: str) -> list[dict]:
    """List comments on an issue.

    Args:
        project_id: UUID of the project
        issue_id: UUID of the issue
    """
    data = await _get(f"{_base(project_id)}/issues/{issue_id}/comments/")
    results = data.get("results", data) if isinstance(data, dict) else data
    return [
        {
            "id": c["id"],
            "comment_stripped": c.get("comment_stripped", ""),
            "actor": c.get("actor_detail", {}).get("display_name", ""),
            "created_at": c.get("created_at", ""),
        }
        for c in results
    ]


@mcp.tool()
async def add_comment(project_id: str, issue_id: str, comment: str) -> dict:
    """Add a comment to an issue.

    Args:
        project_id: UUID of the project
        issue_id: UUID of the issue
        comment: Comment text
    """
    return await _post(
        f"{_base(project_id)}/issues/{issue_id}/comments/",
        {"comment_stripped": comment, "comment_html": f"<p>{comment}</p>"},
    )


# --- Cycles ---


@mcp.tool()
async def list_cycles(project_id: str) -> list[dict]:
    """List sprint cycles in a project.

    Args:
        project_id: UUID of the project
    """
    data = await _get(f"{_base(project_id)}/cycles/")
    results = data.get("results", data) if isinstance(data, dict) else data
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "start_date": c.get("start_date"),
            "end_date": c.get("end_date"),
            "status": c.get("status", ""),
        }
        for c in results
    ]


@mcp.tool()
async def add_issue_to_cycle(project_id: str, cycle_id: str, issue_ids: list[str]) -> dict:
    """Add issues to a sprint cycle.

    Args:
        project_id: UUID of the project
        cycle_id: UUID of the cycle
        issue_ids: List of issue UUIDs to add
    """
    return await _post(
        f"{_base(project_id)}/cycles/{cycle_id}/cycle-issues/",
        {"issues": issue_ids},
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

#!/usr/bin/env python3
"""Migrate agents and skills from MLflow to PostgreSQL.

Reads agent/skill definitions stored as MLflow registered models (tag-based encoding)
and inserts them into the agent-gateway's PostgreSQL database.

Idempotent — uses upsert (ON CONFLICT DO UPDATE).

Usage:
    # From inside k3d cluster (port-forward or kubectl exec):
    AGW_DATABASE_URL=postgresql+asyncpg://agw:agw@localhost:5432/agw \
    MLFLOW_TRACKING_URI=http://mlflow.platform.127.0.0.1.nip.io \
    python scripts/migrate-mlflow-to-pg.py

    # Or via task:
    task migrate-mlflow-to-pg
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.platform.127.0.0.1.nip.io")
DATABASE_URL = os.getenv("AGW_DATABASE_URL", "postgresql+asyncpg://agw:agw@genai-agent-gateway-pg.genai.svc.cluster.local:5432/agw")

# Agent-gateway REST API (easier than direct DB if running locally)
AGW_URL = os.getenv("AGW_URL", "http://gateway.platform.127.0.0.1.nip.io")

# ---------------------------------------------------------------------------
# MLflow read helpers
# ---------------------------------------------------------------------------


def fetch_mlflow_models(prefix: str) -> list[dict]:
    """Fetch registered models from MLflow with given prefix."""
    url = f"{MLFLOW_URI}/api/2.0/mlflow/registered-models/search"
    models = []
    page_token = None

    while True:
        params = {"max_results": "100", "filter": f"name LIKE '{prefix}%'"}
        if page_token:
            params["page_token"] = page_token

        resp = httpx.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for m in data.get("registered_models", []):
            tags = {t["key"]: t["value"] for t in m.get("tags", [])}
            models.append({"name": m["name"], "tags": tags, "description": m.get("description", "")})

        page_token = data.get("next_page_token")
        if not page_token:
            break

    return models


def parse_agent(model: dict) -> dict:
    """Parse MLflow registered model tags into agent dict."""
    tags = model["tags"]
    name = model["name"].removeprefix("agent:")
    return {
        "name": name,
        "description": tags.get("description", model.get("description", "")),
        "runtime": tags.get("runtime", "n8n"),
        "system_prompt": tags.get("system_prompt", ""),
        "skills": json.loads(tags.get("skills", "[]")),
        "capabilities": json.loads(tags.get("capabilities", "[]")),
        "metadata": json.loads(tags.get("metadata", "{}")),
    }


def parse_skill(model: dict) -> dict:
    """Parse MLflow registered model tags into skill dict."""
    tags = model["tags"]
    name = model["name"].removeprefix("skill:")
    return {
        "name": name,
        "description": tags.get("description", model.get("description", "")),
        "version": tags.get("version", "1.0.0"),
        "tags": json.loads(tags.get("tags", "[]")),
        "prompt_fragment": tags.get("prompt_fragment", ""),
        "mcp_servers": json.loads(tags.get("mcp_servers", "[]")),
        "tasks": json.loads(tags.get("tasks", "[]")),
    }


# ---------------------------------------------------------------------------
# Agent-gateway API upsert
# ---------------------------------------------------------------------------


async def upsert_agent(agent: dict) -> None:
    """Upsert agent via agent-gateway REST API."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{AGW_URL}/agents", json=agent)
        if resp.status_code in (200, 201):
            print(f"  agent: {agent['name']} ✓")
        else:
            print(f"  agent: {agent['name']} FAILED ({resp.status_code}: {resp.text[:200]})")


async def upsert_skill(skill: dict) -> None:
    """Upsert skill via agent-gateway REST API."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{AGW_URL}/skills", json=skill)
        if resp.status_code in (200, 201):
            print(f"  skill: {skill['name']} ✓")
        else:
            print(f"  skill: {skill['name']} FAILED ({resp.status_code}: {resp.text[:200]})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    print(f"MLflow: {MLFLOW_URI}")
    print(f"Agent Gateway: {AGW_URL}")
    print()

    # Fetch agents
    print("Fetching agents from MLflow...")
    agent_models = fetch_mlflow_models("agent:")
    print(f"  Found {len(agent_models)} agents")

    agents = [parse_agent(m) for m in agent_models]
    for a in agents:
        await upsert_agent(a)

    print()

    # Fetch skills
    print("Fetching skills from MLflow...")
    skill_models = fetch_mlflow_models("skill:")
    print(f"  Found {len(skill_models)} skills")

    skills = [parse_skill(m) for m in skill_models]
    for s in skills:
        await upsert_skill(s)

    print()
    print(f"Done. Migrated {len(agents)} agents and {len(skills)} skills.")


if __name__ == "__main__":
    asyncio.run(main())

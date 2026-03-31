"""MCP server for ODD Platform — data catalog, lineage, quality."""

import os
import httpx
from mcp.server.fastmcp import FastMCP

ODD_BASE_URL = os.environ.get("ODD_BASE_URL", "http://genai-odd-platform.genai.svc.cluster.local")
ODD_API_KEY = os.environ.get("ODD_API_KEY", "")

mcp = FastMCP("mcp-odd-platform", instructions="Data catalog operations via ODD Platform REST API")

_headers: dict[str, str] = {"Accept": "application/json"}
if ODD_API_KEY:
    _headers["X-API-Key"] = ODD_API_KEY


def _client() -> httpx.Client:
    return httpx.Client(base_url=ODD_BASE_URL, headers=_headers, timeout=30)


# ── Search ──────────────────────────────────────────────


@mcp.tool()
def search_catalog(query: str, limit: int = 20) -> dict:
    """Search the data catalog for entities matching a query string."""
    with _client() as c:
        r = c.get("/api/search", params={"query": query, "size": limit})
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_search_suggestions(query: str) -> dict:
    """Get autocomplete suggestions for a search query."""
    with _client() as c:
        r = c.get("/api/search/suggestion", params={"query": query})
        r.raise_for_status()
        return r.json()


# ── Data Entities ───────────────────────────────────────


@mcp.tool()
def get_entity(entity_id: int) -> dict:
    """Get detailed information about a specific data entity."""
    with _client() as c:
        r = c.get(f"/api/dataentities/{entity_id}")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_popular_entities(limit: int = 10) -> dict:
    """Get the most popular (frequently accessed) data entities."""
    with _client() as c:
        r = c.get("/api/dataentities/popular", params={"size": limit})
        r.raise_for_status()
        return r.json()


# ── Lineage ─────────────────────────────────────────────


@mcp.tool()
def get_upstream_lineage(entity_id: int, depth: int = 5) -> dict:
    """Get upstream lineage (data sources) for an entity."""
    with _client() as c:
        r = c.get(f"/api/dataentities/{entity_id}/lineage/upstream", params={"lineageDepth": depth})
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_downstream_lineage(entity_id: int, depth: int = 5) -> dict:
    """Get downstream lineage (consumers) for an entity."""
    with _client() as c:
        r = c.get(f"/api/dataentities/{entity_id}/lineage/downstream", params={"lineageDepth": depth})
        r.raise_for_status()
        return r.json()


# ── Schema ──────────────────────────────────────────────


@mcp.tool()
def get_schema(entity_id: int) -> dict:
    """Get the latest schema/structure of a dataset."""
    with _client() as c:
        r = c.get(f"/api/datasets/{entity_id}/structure/latest")
        r.raise_for_status()
        return r.json()


# ── Data Quality ────────────────────────────────────────


@mcp.tool()
def get_quality_tests(entity_id: int) -> dict:
    """Get data quality test results for an entity."""
    with _client() as c:
        r = c.get(f"/api/dataentities/{entity_id}/data_qa_tests")
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_quality_test_report(entity_id: int) -> dict:
    """Get aggregated data quality test report for a dataset."""
    with _client() as c:
        r = c.get(f"/api/datasets/{entity_id}/data_qa_tests/report")
        r.raise_for_status()
        return r.json()


# ── Tags & Terms ────────────────────────────────────────


@mcp.tool()
def list_tags(limit: int = 50) -> dict:
    """List popular tags in the data catalog."""
    with _client() as c:
        r = c.get("/api/tags", params={"size": limit})
        r.raise_for_status()
        return r.json()


@mcp.tool()
def search_terms(query: str, limit: int = 20) -> dict:
    """Search business glossary terms."""
    with _client() as c:
        r = c.get("/api/terms", params={"query": query, "size": limit})
        r.raise_for_status()
        return r.json()


# ── Namespaces & Data Sources ───────────────────────────


@mcp.tool()
def list_namespaces(limit: int = 50) -> dict:
    """List all namespaces in the catalog."""
    with _client() as c:
        r = c.get("/api/namespaces", params={"size": limit})
        r.raise_for_status()
        return r.json()


@mcp.tool()
def list_datasources(limit: int = 50) -> dict:
    """List registered data sources (PostgreSQL, S3, etc)."""
    with _client() as c:
        r = c.get("/api/datasources", params={"size": limit})
        r.raise_for_status()
        return r.json()


# ── Alerts ──────────────────────────────────────────────


@mcp.tool()
def list_alerts(limit: int = 20) -> dict:
    """List active alerts from the data catalog."""
    with _client() as c:
        r = c.get("/api/alerts", params={"size": limit})
        r.raise_for_status()
        return r.json()


# ── Activity ────────────────────────────────────────────


@mcp.tool()
def get_activity(limit: int = 20) -> dict:
    """Get recent activity feed from the catalog."""
    with _client() as c:
        r = c.get("/api/activities", params={"size": limit})
        r.raise_for_status()
        return r.json()


# ── Platform Info ───────────────────────────────────────


@mcp.tool()
def get_platform_info() -> dict:
    """Get ODD Platform version and configuration info."""
    with _client() as c:
        r = c.get("/api/appInfo")
        r.raise_for_status()
        return r.json()

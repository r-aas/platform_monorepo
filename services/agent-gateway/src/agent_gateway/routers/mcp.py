"""MCP server discovery and search router."""

import httpx
from fastapi import APIRouter, Query

from agent_gateway.embeddings import cosine_similarity, get_embedding, hybrid_score
from agent_gateway.mcp_discovery import get_tool_index
from agent_gateway.mcp_recommender import recommend_tools


router = APIRouter(prefix="/mcp", tags=["mcp"])


async def _fetch_mcp_tools_from_litellm() -> list[dict]:
    """Fetch available tools from LiteLLM's aggregated MCP gateway."""
    from agent_gateway.config import settings
    url = f"{settings.litellm_base_url}/mcp-rest/tools/list"
    headers = {"Authorization": f"Bearer {settings.litellm_api_key}"} if settings.litellm_api_key else {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            tools = data.get("tools", [])
            return [{"name": t["name"], "description": t.get("description", ""), "namespace": "litellm"} for t in tools]
    except Exception:
        return []


@router.get("/search")
async def search_mcp(q: str = Query(..., description="Search query for hybrid RAG over MCP tools")):
    """Hybrid search over MCP server tools from all MetaMCP namespaces."""
    # Use cached index when available; fall back to live fetch from static namespaces
    idx = get_tool_index()
    if idx is not None:
        all_tools = [{"name": t.name, "description": t.description, "namespace": t.namespace} for t in idx.tools]
    else:
        all_tools = await _fetch_mcp_tools_from_litellm()

    query_lower = q.lower()
    query_emb = await get_embedding(q)
    scored = []
    for tool in all_tools:
        kw_score = 0
        searchable = f"{tool['name']} {tool['description']}".lower()
        for term in query_lower.split():
            if term in searchable:
                kw_score += 1
            if term in tool["name"].lower():
                kw_score += 3

        emb_sim = None
        if query_emb is not None:
            tool_text = f"{tool['name']} {tool['description']}"
            tool_emb = await get_embedding(tool_text)
            if tool_emb is not None:
                emb_sim = cosine_similarity(query_emb, tool_emb)

        score = hybrid_score(kw_score, emb_sim)
        if score > 0:
            scored.append((score, tool))

    scored.sort(key=lambda x: x[0], reverse=True)

    return {
        "query": q,
        "results": [
            {"name": t["name"], "description": t["description"], "namespace": t["namespace"], "score": s}
            for s, t in scored
        ],
    }


@router.get("/recommend")
async def recommend_mcp_tools(
    task: str = Query(..., description="Natural language task description"),
    top_n: int = Query(5, ge=1, le=20, description="Maximum number of tools to recommend"),
    min_score: float = Query(0.5, ge=0.0, description="Minimum relevance score threshold"),
):
    """Recommend relevant MCP tools for a given task description.

    Uses the cached ToolIndex (populated at startup). Returns top-N tools
    above min_score with match hints explaining relevance.
    """
    idx = get_tool_index()
    tools = idx.tools if idx is not None else []
    recommendations = await recommend_tools(task, tools, top_n=top_n, min_score=min_score)
    return {
        "task": task,
        "recommendations": [
            {
                "name": r.name,
                "description": r.description,
                "namespace": r.namespace,
                "score": r.score,
                "match_hints": r.match_hints,
            }
            for r in recommendations
        ],
    }


@router.get("/namespaces")
async def list_namespaces():
    """List known MetaMCP namespaces and their tool counts."""
    idx = get_tool_index()
    if idx is not None:
        # Use indexed data — namespace list is dynamic from MetaMCP
        ns_tool_counts: dict[str, int] = {ns: 0 for ns in idx.namespaces}
        for t in idx.tools:
            if t.namespace in ns_tool_counts:
                ns_tool_counts[t.namespace] += 1
        return {"namespaces": [{"namespace": ns, "tool_count": count} for ns, count in ns_tool_counts.items()]}

    # Fallback: live fetch from LiteLLM
    tools = await _fetch_mcp_tools_from_litellm()
    return {"namespaces": [{"namespace": "litellm", "tool_count": len(tools)}]}

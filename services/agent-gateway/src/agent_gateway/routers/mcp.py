"""MCP server discovery and search router."""

import httpx
from fastapi import APIRouter, Query

from agent_gateway.embeddings import cosine_similarity, get_embedding, hybrid_score
from agent_gateway.mcp_discovery import get_tool_index


router = APIRouter(prefix="/mcp", tags=["mcp"])


async def _fetch_mcp_tools(namespace: str) -> list[dict]:
    """Fetch available tools from a MetaMCP namespace via tools/list."""
    url = f"http://genai-metamcp.genai.svc.cluster.local:12008/metamcp/{namespace}/mcp"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # MCP tools/list via Streamable HTTP
            resp = await client.post(url, json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})
            resp.raise_for_status()
            data = resp.json()
            tools = data.get("result", {}).get("tools", [])
            return [{"name": t["name"], "description": t.get("description", ""), "namespace": namespace} for t in tools]
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
        namespaces = ["genai", "platform"]
        all_tools = []
        for ns in namespaces:
            all_tools.extend(await _fetch_mcp_tools(ns))

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

    # Fallback: live fetch from static namespace list
    namespaces = ["genai", "platform"]
    result = []
    for ns in namespaces:
        tools = await _fetch_mcp_tools(ns)
        result.append({"namespace": ns, "tool_count": len(tools)})
    return {"namespaces": result}

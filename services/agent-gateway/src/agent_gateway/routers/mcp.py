"""MCP server discovery and search router."""

import httpx
from fastapi import APIRouter, Query


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
    # Fetch tools from known namespaces
    namespaces = ["genai", "platform"]
    all_tools = []
    for ns in namespaces:
        all_tools.extend(await _fetch_mcp_tools(ns))

    query_lower = q.lower()
    scored = []
    for tool in all_tools:
        score = 0
        searchable = f"{tool['name']} {tool['description']}".lower()
        for term in query_lower.split():
            if term in searchable:
                score += 1
            if term in tool["name"].lower():
                score += 3
        if score > 0:
            scored.append((score, tool))

    scored.sort(key=lambda x: x[0], reverse=True)

    # TODO: add embedding-based semantic similarity via Ollama /v1/embeddings

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
    namespaces = ["genai", "platform"]
    result = []
    for ns in namespaces:
        tools = await _fetch_mcp_tools(ns)
        result.append({"namespace": ns, "tool_count": len(tools)})
    return {"namespaces": result}

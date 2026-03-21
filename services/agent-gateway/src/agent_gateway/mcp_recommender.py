"""MCP tool recommendation engine.

C.03: Given a natural language task description, recommend relevant MCP tools.

Differs from search (/mcp/search) in that:
- Returns top-N results only (not all matching)
- Enforces min_score threshold (ignores irrelevant tools)
- Includes match_hints explaining why each tool was recommended
- No live HTTP fetch — requires a populated ToolIndex

Pure core (score_tools) is sync and testable without any I/O.
Async wrapper (recommend_tools) adds embedding computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_gateway.embeddings import hybrid_score
from agent_gateway.mcp_discovery import DiscoveredTool


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ToolRecommendation:
    name: str
    description: str
    namespace: str
    score: float
    match_hints: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure scoring function (sync — no I/O)
# ---------------------------------------------------------------------------


def score_tools(
    task: str,
    tools: list[DiscoveredTool],
    query_embedding: list[float] | None = None,
    top_n: int = 5,
    min_score: float = 0.5,
) -> list[ToolRecommendation]:
    """Score tools against a task description and return top recommendations.

    Args:
        task: Natural language task description.
        tools: Candidate tools from ToolIndex.
        query_embedding: Pre-computed embedding for task (None → keyword-only).
        top_n: Maximum results to return.
        min_score: Minimum score threshold; tools below this are excluded.

    Returns:
        Sorted list of ToolRecommendation, highest score first.
    """
    if not tools:
        return []

    task_lower = task.lower()
    terms = task_lower.split()
    results: list[ToolRecommendation] = []

    for tool in tools:
        name_lower = tool.name.lower()
        desc_lower = tool.description.lower()
        hints: list[str] = []
        kw_score = 0.0

        for term in terms:
            if term in name_lower:
                kw_score += 3.0
                hints.append(f"name matches '{term}'")
            if term in desc_lower:
                kw_score += 1.0
                hints.append(f"description mentions '{term}'")

        # Embedding similarity — reserved for future: tool embeddings computed async by caller
        emb_sim: float | None = None

        score = hybrid_score(kw_score, emb_sim)

        if score >= min_score:
            # Deduplicate hints while preserving order
            seen: set[str] = set()
            unique_hints: list[str] = []
            for h in hints:
                if h not in seen:
                    seen.add(h)
                    unique_hints.append(h)

            results.append(
                ToolRecommendation(
                    name=tool.name,
                    description=tool.description,
                    namespace=tool.namespace,
                    score=score,
                    match_hints=unique_hints,
                )
            )

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_n]


# ---------------------------------------------------------------------------
# Async wrapper (adds embedding computation)
# ---------------------------------------------------------------------------


async def recommend_tools(
    task: str,
    tools: list[DiscoveredTool],
    top_n: int = 5,
    min_score: float = 0.5,
) -> list[ToolRecommendation]:
    """Async recommendation entry point — computes task embedding then calls score_tools."""
    from agent_gateway.embeddings import get_embedding

    query_embedding = await get_embedding(task)
    return score_tools(task, tools, query_embedding=query_embedding, top_n=top_n, min_score=min_score)

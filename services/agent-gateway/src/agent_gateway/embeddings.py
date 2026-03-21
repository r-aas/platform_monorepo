"""Embedding utility — cosine similarity + Ollama /v1/embeddings integration."""

import math

import httpx

from agent_gateway.config import settings


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors. Returns 0.0 for zero vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def get_embedding(text: str) -> list[float] | None:
    """Compute embedding via Ollama /v1/embeddings. Returns None on failure (graceful fallback)."""
    url = f"{settings.ollama_base_url}/v1/embeddings"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json={"model": settings.ollama_embedding_model, "input": text})
            resp.raise_for_status()
            data = resp.json()
            # Ollama returns {"data": [{"embedding": [...]}]} for /v1/embeddings
            if "data" in data:
                return data["data"][0]["embedding"]
            # Fallback: direct {"embedding": [...]} shape
            return data.get("embedding")
    except Exception:
        return None


def hybrid_score(
    keyword: float,
    embedding_sim: float | None,
    keyword_weight: float = 0.7,
    embedding_weight: float = 0.3,
) -> float:
    """Combine keyword score and embedding similarity into a hybrid score.

    When embedding_sim is None (Ollama unreachable), returns keyword score unchanged.
    """
    if embedding_sim is None:
        return float(keyword)
    return keyword * keyword_weight + embedding_sim * embedding_weight

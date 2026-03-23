"""Embedding utility — cosine similarity + Ollama /v1/embeddings integration."""

import math
from collections import OrderedDict

import httpx

from agent_gateway.config import settings


class EmbeddingCache:
    """LRU cache for embedding vectors. Thread-safe via OrderedDict move_to_end."""

    def __init__(self, maxsize: int = 512) -> None:
        self._maxsize = maxsize
        self._store: OrderedDict[str, list[float]] = OrderedDict()

    def get(self, key: str) -> list[float] | None:
        """Return cached embedding or None. Moves key to end (most-recently-used)."""
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def set(self, key: str, value: list[float]) -> None:
        """Store embedding. Evicts least-recently-used entry when at capacity."""
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        if len(self._store) > self._maxsize:
            self._store.popitem(last=False)  # remove oldest (LRU)

    def clear(self) -> None:
        self._store.clear()

    def size(self) -> int:
        return len(self._store)


# Module-level singleton — shared across all callers
_cache = EmbeddingCache(maxsize=512)


def clear_embedding_cache() -> None:
    """Clear the module-level embedding cache. Useful for testing."""
    _cache.clear()


def embedding_cache_size() -> int:
    """Return number of entries in the module-level cache."""
    return _cache.size()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors. Returns 0.0 for zero vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def get_embedding(text: str) -> list[float] | None:
    """Compute embedding via Ollama /v1/embeddings. Returns None on failure (graceful fallback).

    Results are cached in the module-level LRU cache — repeated calls with the same text
    return the cached vector without re-hitting Ollama.
    """
    cached = _cache.get(text)
    if cached is not None:
        return cached

    url = f"{settings.ollama_base_url}/v1/embeddings"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json={"model": settings.ollama_embedding_model, "input": text})
            resp.raise_for_status()
            data = resp.json()
            # Ollama returns {"data": [{"embedding": [...]}]} for /v1/embeddings
            if "data" in data:
                vec = data["data"][0]["embedding"]
            else:
                # Fallback: direct {"embedding": [...]} shape
                vec = data.get("embedding")
            if vec is not None:
                _cache.set(text, vec)
            return vec
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

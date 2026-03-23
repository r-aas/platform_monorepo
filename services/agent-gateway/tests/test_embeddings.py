"""Tests for embedding utility functions."""

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_gateway.embeddings import (
    EmbeddingCache,
    clear_embedding_cache,
    cosine_similarity,
    embedding_cache_size,
    get_embedding,
    hybrid_score,
)


def test_cosine_similarity_identical():
    a = [1.0, 0.0, 0.0]
    assert math.isclose(cosine_similarity(a, a), 1.0, abs_tol=1e-6)


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert math.isclose(cosine_similarity(a, b), 0.0, abs_tol=1e-6)


def test_cosine_similarity_opposite():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert math.isclose(cosine_similarity(a, b), -1.0, abs_tol=1e-6)


def test_cosine_similarity_zero_vector():
    a = [0.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert cosine_similarity(a, b) == 0.0


@pytest.mark.asyncio
async def test_get_embedding_success():
    clear_embedding_cache()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = lambda: {"embedding": [0.1, 0.2, 0.3]}

    with patch("agent_gateway.embeddings.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await get_embedding("hello world")
        assert result == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_get_embedding_failure_returns_none():
    clear_embedding_cache()
    with patch("agent_gateway.embeddings.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

        result = await get_embedding("hello world")
        assert result is None


def test_hybrid_score_keyword_only():
    # When embedding similarity is None, returns keyword score unchanged
    score = hybrid_score(keyword=5, embedding_sim=None)
    assert score == 5.0


def test_hybrid_score_with_embedding():
    # Keyword contributes 70%, embedding 30%
    score = hybrid_score(keyword=10, embedding_sim=0.8, keyword_weight=0.7, embedding_weight=0.3)
    assert math.isclose(score, 10 * 0.7 + 0.8 * 0.3, abs_tol=1e-6)


def test_hybrid_score_zero_keyword():
    # If keyword=0 but embedding high, still surfaces
    score = hybrid_score(keyword=0, embedding_sim=0.9, keyword_weight=0.7, embedding_weight=0.3)
    assert math.isclose(score, 0.0 * 0.7 + 0.9 * 0.3, abs_tol=1e-6)
    assert score > 0


# --- EmbeddingCache unit tests ---


def test_embedding_cache_get_miss():
    cache = EmbeddingCache(maxsize=10)
    assert cache.get("missing") is None


def test_embedding_cache_set_and_get():
    cache = EmbeddingCache(maxsize=10)
    vec = [0.1, 0.2, 0.3]
    cache.set("hello", vec)
    assert cache.get("hello") == vec


def test_embedding_cache_evicts_lru_when_full():
    cache = EmbeddingCache(maxsize=3)
    cache.set("a", [1.0])
    cache.set("b", [2.0])
    cache.set("c", [3.0])
    # Access "a" to make it recently used
    cache.get("a")
    # Add "d" — should evict "b" (least recently used)
    cache.set("d", [4.0])
    assert cache.get("b") is None  # evicted
    assert cache.get("a") == [1.0]  # kept (recently accessed)
    assert cache.get("c") == [3.0]  # kept
    assert cache.get("d") == [4.0]  # kept


def test_embedding_cache_size():
    cache = EmbeddingCache(maxsize=10)
    assert cache.size() == 0
    cache.set("x", [1.0])
    assert cache.size() == 1


def test_embedding_cache_clear():
    cache = EmbeddingCache(maxsize=10)
    cache.set("x", [1.0])
    cache.clear()
    assert cache.size() == 0
    assert cache.get("x") is None


# --- Module-level cache helpers ---


@pytest.mark.asyncio
async def test_get_embedding_cached_second_call_skips_http():
    """Second call with same text should return cached result without HTTP."""
    clear_embedding_cache()

    vec = [0.5, 0.6, 0.7]
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = lambda: {"embedding": vec}

    with patch("agent_gateway.embeddings.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        result1 = await get_embedding("cached text")
        result2 = await get_embedding("cached text")  # should hit cache, not HTTP

        assert result1 == vec
        assert result2 == vec
        assert mock_client.post.call_count == 1  # only one HTTP call


@pytest.mark.asyncio
async def test_get_embedding_failure_not_cached():
    """Failed embeddings should NOT be stored in cache."""
    clear_embedding_cache()

    with patch("agent_gateway.embeddings.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("timeout"))

        await get_embedding("fail text")

    assert embedding_cache_size() == 0


def test_embedding_cache_size_helper():
    clear_embedding_cache()
    assert embedding_cache_size() == 0

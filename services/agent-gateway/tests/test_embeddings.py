"""Tests for embedding utility functions."""

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_gateway.embeddings import cosine_similarity, get_embedding, hybrid_score


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

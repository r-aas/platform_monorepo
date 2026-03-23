"""Tests for skill regression detection — F.02."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_gateway.benchmark.regression import detect_regression, get_run_scores


# ---------------------------------------------------------------------------
# Pure function: detect_regression
# ---------------------------------------------------------------------------


def test_detect_regression_empty_scores() -> None:
    assert detect_regression([]) is None


def test_detect_regression_single_run() -> None:
    assert detect_regression([0.8]) is None


def test_detect_regression_stable() -> None:
    result = detect_regression([0.9, 0.9, 0.9, 0.9])
    assert result is not None
    assert result.is_regressed is False
    assert abs(result.drop_amount) < 0.001


def test_detect_regression_detected() -> None:
    result = detect_regression([0.9, 0.9, 0.9, 0.5])
    assert result is not None
    assert result.is_regressed is True
    assert result.current_score == pytest.approx(0.5)
    assert result.baseline_score == pytest.approx(0.9)
    assert result.drop_amount == pytest.approx(-0.4)


def test_detect_regression_custom_threshold_not_triggered() -> None:
    # Drop of 0.1 below threshold=0.2 → not regressed
    result = detect_regression([0.9, 0.8], threshold=0.2)
    assert result is not None
    assert result.is_regressed is False


def test_detect_regression_run_count() -> None:
    result = detect_regression([0.8, 0.8, 0.8])
    assert result is not None
    assert result.run_count == 3


# ---------------------------------------------------------------------------
# get_run_scores: MLflow query
# ---------------------------------------------------------------------------


def test_get_run_scores_returns_scores() -> None:
    run1 = MagicMock()
    run1.data.metrics = {"pass_rate": 0.8}
    run2 = MagicMock()
    run2.data.metrics = {"pass_rate": 0.9}

    client = MagicMock()
    client.get_experiment_by_name.return_value = MagicMock(experiment_id="42")
    client.search_runs.return_value = [run1, run2]

    scores = get_run_scores(client, "eval:mlops:kubernetes-ops:deploy-model")
    assert scores == [0.8, 0.9]


def test_get_run_scores_missing_experiment_returns_empty() -> None:
    client = MagicMock()
    client.get_experiment_by_name.return_value = None

    scores = get_run_scores(client, "eval:mlops:nonexistent:task")
    assert scores == []


def test_get_run_scores_mlflow_exception_returns_empty() -> None:
    client = MagicMock()
    client.get_experiment_by_name.side_effect = Exception("mlflow down")

    scores = get_run_scores(client, "eval:mlops:kubernetes-ops:deploy-model")
    assert scores == []


# ---------------------------------------------------------------------------
# Endpoint test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_regression_endpoint_returns_report(client) -> None:
    mock_eval_datasets = {
        "kubernetes-ops": ["deploy-model"],
    }
    mock_scores = [0.9, 0.9, 0.5]  # regression present

    with (
        patch("agent_gateway.routers.factory._scan_eval_datasets", return_value=mock_eval_datasets),
        patch("agent_gateway.routers.factory.get_run_scores", return_value=mock_scores),
    ):
        response = await client.get("/factory/regression")

    assert response.status_code == 200
    body = response.json()
    assert "checks" in body
    assert "regressions_found" in body
    assert body["regressions_found"] >= 1
    check = body["checks"][0]
    assert check["skill"] == "kubernetes-ops"
    assert check["task"] == "deploy-model"
    assert check["is_regressed"] is True

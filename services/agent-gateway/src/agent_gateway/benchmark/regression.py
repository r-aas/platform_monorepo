"""Skill regression detection — F.02.

Detects when benchmark pass_rate drops significantly compared to historical runs.
Pure functions: no side effects, fully testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RegressionResult:
    skill: str
    task: str
    current_score: float
    baseline_score: float
    is_regressed: bool
    drop_amount: float  # current - baseline (negative = regression)
    run_count: int


def detect_regression(
    scores: list[float],
    threshold: float = 0.1,
    skill: str = "",
    task: str = "",
) -> RegressionResult | None:
    """Given ordered scores (oldest first, newest last), detect regression.

    Returns None if fewer than 2 data points — no baseline to compare against.
    """
    if len(scores) < 2:
        return None
    current = scores[-1]
    prior = scores[:-1]
    baseline = sum(prior) / len(prior)
    drop = current - baseline
    return RegressionResult(
        skill=skill,
        task=task,
        current_score=current,
        baseline_score=baseline,
        is_regressed=drop < -threshold,
        drop_amount=drop,
        run_count=len(scores),
    )


def get_run_scores(client, experiment_name: str, limit: int = 10) -> list[float]:
    """Fetch last N pass_rate metrics from an MLflow experiment.

    Returns scores ordered oldest-first. Returns [] if experiment not found or
    on any MLflow error (non-fatal).
    """
    try:
        exp = client.get_experiment_by_name(experiment_name)
        if not exp:
            return []
        runs = client.search_runs(
            experiment_ids=[exp.experiment_id],
            order_by=["start_time ASC"],
            max_results=limit,
        )
        return [r.data.metrics.get("pass_rate", 0.0) for r in runs]
    except Exception:
        return []

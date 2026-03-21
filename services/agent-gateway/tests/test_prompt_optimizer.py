"""Tests for prompt optimizer — coverage scoring + improvement suggestions [D.07]."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agent_gateway.benchmark.optimizer import (
    extract_uncovered_terms,
    optimize_skill_prompt,
    record_optimization_result,
    score_prompt_coverage,
    suggest_prompt_improvements,
)


# ---------------------------------------------------------------------------
# score_prompt_coverage — pure scoring function
# ---------------------------------------------------------------------------


def test_score_prompt_coverage_full():
    """All expected terms in prompt → 1.0."""
    cases = [
        {"expected_output_contains": ["kubectl_apply", "deployed"]},
        {"expected_output_contains": ["replicas", "running"]},
    ]
    prompt = "Use kubectl_apply to deploy. Check replicas are running after deployed."
    assert score_prompt_coverage(prompt, cases) == 1.0


def test_score_prompt_coverage_zero():
    """No expected terms in prompt → 0.0."""
    cases = [{"expected_output_contains": ["rollout", "HPA", "configmap"]}]
    prompt = "Follow standard operations."
    assert score_prompt_coverage(prompt, cases) == 0.0


def test_score_prompt_coverage_partial():
    """Half of expected terms covered → 0.5."""
    cases = [{"expected_output_contains": ["deployment", "pod", "service", "ingress"]}]
    # "deployment" and "pod" appear; "service" and "ingress" do not
    prompt = "Check that the deployment and pod are healthy."
    result = score_prompt_coverage(prompt, cases)
    assert result == pytest.approx(0.5)


def test_score_prompt_coverage_empty_cases():
    """No eval cases → 1.0 (nothing to fail)."""
    assert score_prompt_coverage("any prompt", []) == 1.0


# ---------------------------------------------------------------------------
# extract_uncovered_terms — find gaps
# ---------------------------------------------------------------------------


def test_extract_uncovered_terms_returns_missing():
    """Returns terms from expected_output_contains not present in prompt."""
    cases = [{"expected_output_contains": ["HPA", "replicas", "kubectl_apply"]}]
    prompt = "Always use kubectl_apply for deployments."
    uncovered = extract_uncovered_terms(prompt, cases)
    assert "HPA" in uncovered
    assert "replicas" in uncovered
    assert "kubectl_apply" not in uncovered


def test_extract_uncovered_terms_no_duplicates():
    """Same term in multiple cases appears only once in result."""
    cases = [
        {"expected_output_contains": ["deployed"]},
        {"expected_output_contains": ["deployed", "running"]},
    ]
    prompt = "All good."
    uncovered = extract_uncovered_terms(prompt, cases)
    assert uncovered.count("deployed") == 1
    assert "running" in uncovered


def test_extract_uncovered_terms_all_covered():
    """Returns empty list when prompt covers everything."""
    cases = [{"expected_output_contains": ["success"]}]
    prompt = "Operation success."
    assert extract_uncovered_terms(prompt, cases) == []


# ---------------------------------------------------------------------------
# suggest_prompt_improvements — generate better prompt
# ---------------------------------------------------------------------------


def test_suggest_prompt_improvements_no_uncovered():
    """Returns unchanged prompt when no uncovered terms."""
    original = "Use kubectl_apply."
    result = suggest_prompt_improvements(original, [])
    assert result == original


def test_suggest_prompt_improvements_adds_guidance():
    """Adds guidance bullets for uncovered terms."""
    original = "Use kubectl_apply for deployments."
    result = suggest_prompt_improvements(original, ["HPA", "rollout"])
    assert "HPA" in result
    assert "rollout" in result
    assert len(result) > len(original)


# ---------------------------------------------------------------------------
# optimize_skill_prompt — full cycle
# ---------------------------------------------------------------------------


def test_optimize_skill_prompt_full_cycle(tmp_path: Path):
    """optimize_skill_prompt scores, finds gaps, improves, returns result dict."""
    # Create a minimal skill YAML with one task + dataset reference
    dataset = {
        "skill": "test-skill",
        "task": "test-task",
        "cases": [
            {
                "id": "c1",
                "input": "Do the thing",
                "expected_output_contains": ["HPA", "replicas", "rollout"],
                "expected_tools_used": [],
            }
        ],
    }
    dataset_dir = tmp_path / "skills" / "eval" / "test-skill"
    dataset_dir.mkdir(parents=True)
    dataset_file = dataset_dir / "test-task.json"
    dataset_file.write_text(json.dumps(dataset))

    skill_data = {
        "name": "test-skill",
        "description": "A test skill",
        "prompt_fragment": "Perform operations carefully.",  # covers none of HPA/replicas/rollout
        "tasks": [
            {
                "name": "test-task",
                "description": "Run the test task",
                "evaluation": {"dataset": "skills/eval/test-skill/test-task.json"},
            }
        ],
    }
    skill_path = tmp_path / "skills" / "test-skill.yaml"
    (tmp_path / "skills").mkdir(exist_ok=True)
    skill_path.write_text(yaml.dump(skill_data))

    result = optimize_skill_prompt(skill_path, datasets_root=tmp_path)

    assert result["skill"] == "test-skill"
    assert result["before_score"] == pytest.approx(0.0)
    assert result["after_score"] > result["before_score"]
    assert len(result["uncovered_terms"]) > 0
    assert "improved_prompt" in result
    assert result["improvement"] > 0.0


def test_optimize_skill_prompt_no_datasets(tmp_path: Path):
    """Skill with no eval datasets returns zero improvement result."""
    skill_data = {
        "name": "no-eval-skill",
        "description": "Skill with no evals",
        "prompt_fragment": "Do the thing.",
        "tasks": [{"name": "task-a", "description": "Task without evaluation"}],
    }
    skill_path = tmp_path / "no-eval-skill.yaml"
    skill_path.write_text(yaml.dump(skill_data))

    result = optimize_skill_prompt(skill_path, datasets_root=tmp_path)

    assert result["skill"] == "no-eval-skill"
    assert result["before_score"] == 1.0  # no cases → full coverage
    assert result["uncovered_terms"] == []


# ---------------------------------------------------------------------------
# record_optimization_result — MLflow logging (mocked)
# ---------------------------------------------------------------------------


def test_record_optimization_result_logs_mlflow():
    """record_optimization_result logs before/after scores to MLflow."""
    optimization = {
        "skill": "kubernetes-ops",
        "before_score": 0.2,
        "after_score": 0.8,
        "uncovered_terms": ["HPA", "rollout"],
        "improved_prompt": "Use kubectl_apply. Include HPA and rollout info.",
        "improvement": 0.6,
    }

    mock_client = MagicMock()
    mock_client.create_experiment.return_value = "exp-opt-1"
    mock_client.create_run.return_value = MagicMock(info=MagicMock(run_id="run-opt-1"))

    with patch("agent_gateway.benchmark.optimizer.MlflowClient", return_value=mock_client):
        run_id = record_optimization_result(optimization, tracking_uri="http://mlflow:5000")

    assert run_id == "run-opt-1"
    log_calls = [str(c) for c in mock_client.log_metric.call_args_list]
    assert any("before_score" in c for c in log_calls)
    assert any("after_score" in c for c in log_calls)
    assert any("improvement" in c for c in log_calls)

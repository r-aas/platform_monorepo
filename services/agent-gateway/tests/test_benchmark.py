"""Tests for benchmark runner — eval dataset execution + MLflow result logging."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_gateway.benchmark.runner import BenchmarkResult, CaseResult, evaluate_case, load_dataset, run_benchmark_task


# ---------------------------------------------------------------------------
# evaluate_case — pure function, no I/O
# ---------------------------------------------------------------------------


def test_evaluate_case_all_pass():
    case = {
        "id": "deploy-basic",
        "input": "Deploy fraud-detection model",
        "expected_output_contains": ["deployment", "created", "fraud-detection"],
        "expected_tools_used": ["kubectl_apply"],
        "max_latency_seconds": 30,
    }
    result = evaluate_case(
        case=case,
        actual_output="Created deployment fraud-detection in genai namespace.",
        tools_used=["kubectl_apply"],
        latency_seconds=1.5,
    )
    assert result.passed is True
    assert result.failures == []
    assert result.id == "deploy-basic"
    assert result.latency == 1.5


def test_evaluate_case_missing_expected_string():
    case = {
        "id": "deploy-basic",
        "input": "Deploy fraud-detection model",
        "expected_output_contains": ["deployment", "created", "fraud-detection"],
        "expected_tools_used": [],
    }
    result = evaluate_case(
        case=case,
        actual_output="Error: model not found",
        tools_used=[],
        latency_seconds=0.5,
    )
    assert result.passed is False
    assert any("deployment" in f for f in result.failures)
    assert any("created" in f for f in result.failures)
    assert any("fraud-detection" in f for f in result.failures)


def test_evaluate_case_missing_tool():
    case = {
        "id": "deploy-basic",
        "input": "Deploy model",
        "expected_output_contains": [],
        "expected_tools_used": ["kubectl_apply", "kubectl_get"],
    }
    result = evaluate_case(
        case=case,
        actual_output="Done",
        tools_used=["kubectl_apply"],  # missing kubectl_get
        latency_seconds=1.0,
    )
    assert result.passed is False
    assert any("kubectl_get" in f for f in result.failures)


def test_evaluate_case_latency_exceeded():
    case = {
        "id": "slow-case",
        "input": "Do something",
        "expected_output_contains": [],
        "expected_tools_used": [],
        "max_latency_seconds": 5,
    }
    result = evaluate_case(
        case=case,
        actual_output="Done",
        tools_used=[],
        latency_seconds=10.0,
    )
    assert result.passed is False
    assert any("latency" in f.lower() for f in result.failures)


def test_evaluate_case_no_latency_limit():
    """Cases without max_latency_seconds don't fail on latency."""
    case = {
        "id": "no-latency-case",
        "input": "Do something",
        "expected_output_contains": [],
        "expected_tools_used": [],
    }
    result = evaluate_case(
        case=case,
        actual_output="Done",
        tools_used=[],
        latency_seconds=999.0,
    )
    assert result.passed is True
    assert result.failures == []


def test_evaluate_case_empty_expectations():
    """Cases with empty expectations always pass."""
    case = {
        "id": "trivial",
        "input": "Say hello",
        "expected_output_contains": [],
        "expected_tools_used": [],
    }
    result = evaluate_case(case=case, actual_output="Hello!", tools_used=[], latency_seconds=0.1)
    assert result.passed is True


# ---------------------------------------------------------------------------
# load_dataset — reads JSON from disk
# ---------------------------------------------------------------------------


def test_load_dataset(tmp_path: Path):
    dataset = {
        "task": "deploy-model",
        "skill": "kubernetes-ops",
        "cases": [
            {
                "id": "case-1",
                "input": "Deploy model",
                "expected_output_contains": ["deployed"],
                "expected_tools_used": ["kubectl_apply"],
            }
        ],
    }
    p = tmp_path / "deploy-model.json"
    p.write_text(json.dumps(dataset))

    loaded = load_dataset(p)
    assert loaded["task"] == "deploy-model"
    assert loaded["skill"] == "kubernetes-ops"
    assert len(loaded["cases"]) == 1
    assert loaded["cases"][0]["id"] == "case-1"


def test_load_dataset_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_dataset(tmp_path / "nonexistent.json")


# ---------------------------------------------------------------------------
# BenchmarkResult aggregation
# ---------------------------------------------------------------------------


def test_benchmark_result_pass_rate():
    results = BenchmarkResult(
        agent="mlops",
        skill="kubernetes-ops",
        task="deploy-model",
        cases=[
            CaseResult(id="c1", passed=True, failures=[], latency=1.0, actual_output="ok"),
            CaseResult(id="c2", passed=True, failures=[], latency=2.0, actual_output="ok"),
            CaseResult(id="c3", passed=False, failures=["missing: foo"], latency=3.0, actual_output="fail"),
            CaseResult(id="c4", passed=False, failures=["missing: bar"], latency=4.0, actual_output="fail"),
        ],
    )
    assert results.pass_rate == 0.5
    assert results.avg_latency == 2.5
    assert results.total_cases == 4


def test_benchmark_result_all_pass():
    results = BenchmarkResult(
        agent="mlops",
        skill="kubernetes-ops",
        task="deploy-model",
        cases=[
            CaseResult(id="c1", passed=True, failures=[], latency=1.0, actual_output="ok"),
        ],
    )
    assert results.pass_rate == 1.0


def test_benchmark_result_empty():
    results = BenchmarkResult(agent="mlops", skill="kubernetes-ops", task="deploy-model", cases=[])
    assert results.pass_rate == 0.0
    assert results.avg_latency == 0.0
    assert results.total_cases == 0


# ---------------------------------------------------------------------------
# record_results — MLflow logging (mocked)
# ---------------------------------------------------------------------------


def test_record_results_creates_experiment():
    from agent_gateway.benchmark.results import record_results

    results = BenchmarkResult(
        agent="mlops",
        skill="kubernetes-ops",
        task="deploy-model",
        cases=[CaseResult(id="c1", passed=True, failures=[], latency=1.2, actual_output="ok")],
    )

    mock_client = MagicMock()
    mock_client.create_experiment.return_value = "exp-123"
    mock_client.create_run.return_value = MagicMock(info=MagicMock(run_id="run-456"))

    with patch("agent_gateway.benchmark.results.MlflowClient", return_value=mock_client):
        run_id = record_results(results, tracking_uri="http://mlflow:5000")

    assert run_id == "run-456"
    # Experiment should be created with correct name
    mock_client.create_experiment.assert_called_once()
    call_args = mock_client.create_experiment.call_args
    assert "eval:mlops:kubernetes-ops:deploy-model" in str(call_args)


def test_record_results_logs_metrics():
    from agent_gateway.benchmark.results import record_results

    results = BenchmarkResult(
        agent="mlops",
        skill="kubernetes-ops",
        task="deploy-model",
        cases=[
            CaseResult(id="c1", passed=True, failures=[], latency=1.0, actual_output="ok"),
            CaseResult(id="c2", passed=False, failures=["x"], latency=2.0, actual_output="fail"),
        ],
    )

    mock_client = MagicMock()
    mock_client.create_experiment.return_value = "exp-123"
    mock_client.create_run.return_value = MagicMock(info=MagicMock(run_id="run-456"))

    with patch("agent_gateway.benchmark.results.MlflowClient", return_value=mock_client):
        record_results(results, tracking_uri="http://mlflow:5000")

    # Should log pass_rate, avg_latency, total_cases
    log_calls = [str(c) for c in mock_client.log_metric.call_args_list]
    assert any("pass_rate" in c for c in log_calls)
    assert any("avg_latency" in c for c in log_calls)
    assert any("total_cases" in c for c in log_calls)


# ---------------------------------------------------------------------------
# Benchmark API endpoint
# ---------------------------------------------------------------------------


@patch("agent_gateway.routers.skills.get_skill")
@patch("agent_gateway.routers.skills.run_benchmark_task")
async def test_benchmark_endpoint_accepted(mock_run, mock_get, client):
    """POST /skills/{name}/tasks/{task}/benchmark returns 202."""
    from agent_gateway.models import SkillDefinition, TaskDefinition, EvaluationRef

    skill = SkillDefinition(
        name="kubernetes-ops",
        tasks=[
            TaskDefinition(
                name="deploy-model",
                evaluation=EvaluationRef(dataset="skills/eval/kubernetes-ops/deploy-model.json"),
            )
        ],
    )
    mock_get.return_value = skill
    mock_run.return_value = "run-789"

    resp = await client.post(
        "/skills/kubernetes-ops/tasks/deploy-model/benchmark",
        params={"agent": "mlops"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["benchmark_id"] == "run-789"
    assert data["skill"] == "kubernetes-ops"
    assert data["task"] == "deploy-model"
    assert data["agent"] == "mlops"


@patch("agent_gateway.routers.skills.get_skill")
async def test_benchmark_endpoint_skill_not_found(mock_get, client):
    mock_get.side_effect = KeyError("kubernetes-ops")

    resp = await client.post(
        "/skills/kubernetes-ops/tasks/deploy-model/benchmark",
        params={"agent": "mlops"},
    )
    assert resp.status_code == 404


@patch("agent_gateway.routers.skills.get_skill")
async def test_benchmark_endpoint_task_not_found(mock_get, client):
    from agent_gateway.models import SkillDefinition

    mock_get.return_value = SkillDefinition(name="kubernetes-ops", tasks=[])

    resp = await client.post(
        "/skills/kubernetes-ops/tasks/nonexistent-task/benchmark",
        params={"agent": "mlops"},
    )
    assert resp.status_code == 404


@patch("agent_gateway.routers.skills.get_skill")
async def test_benchmark_endpoint_no_evaluation(mock_get, client):
    """Task exists but has no evaluation dataset → 422."""
    from agent_gateway.models import SkillDefinition, TaskDefinition

    skill = SkillDefinition(
        name="kubernetes-ops",
        tasks=[TaskDefinition(name="deploy-model")],  # no evaluation ref
    )
    mock_get.return_value = skill

    resp = await client.post(
        "/skills/kubernetes-ops/tasks/deploy-model/benchmark",
        params={"agent": "mlops"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# run_benchmark_task — end-to-end integration (D.05)
# ---------------------------------------------------------------------------


def test_run_benchmark_task_processes_all_cases(tmp_path: Path):
    """run_benchmark_task loads dataset, evaluates all cases, returns run_id."""
    dataset = {
        "task": "deploy-model",
        "skill": "kubernetes-ops",
        "cases": [
            {
                "id": "c1",
                "input": "Deploy fraud-detection",
                "expected_output_contains": ["deployed"],
                "expected_tools_used": [],
            },
            {
                "id": "c2",
                "input": "Deploy sentiment-analysis",
                "expected_output_contains": ["deployed"],
                "expected_tools_used": [],
            },
        ],
    }
    dataset_path = tmp_path / "deploy-model.json"
    dataset_path.write_text(json.dumps(dataset))

    mock_client = MagicMock()
    mock_client.create_experiment.return_value = "exp-111"
    mock_client.create_run.return_value = MagicMock(info=MagicMock(run_id="run-e2e-1"))

    with patch("agent_gateway.benchmark.results.MlflowClient", return_value=mock_client):
        run_id = run_benchmark_task(
            skill_name="kubernetes-ops",
            task_name="deploy-model",
            agent_name="mlops",
            dataset_path=str(dataset_path),
            tracking_uri="http://mlflow:5000",
        )

    assert run_id == "run-e2e-1"
    # Both cases should have been evaluated (stub mode → empty output → fail, but counted)
    log_metric_calls = {str(c) for c in mock_client.log_metric.call_args_list}
    assert any("total_cases" in c and "2" in c for c in log_metric_calls)


def test_run_benchmark_task_stub_mode_all_fail(tmp_path: Path):
    """In stub mode (no live gateway), all cases with expectations fail."""
    dataset = {
        "task": "deploy-model",
        "skill": "kubernetes-ops",
        "cases": [
            {
                "id": "c1",
                "input": "Deploy model",
                "expected_output_contains": ["deployed"],
                "expected_tools_used": ["kubectl_apply"],
            },
        ],
    }
    dataset_path = tmp_path / "deploy-model.json"
    dataset_path.write_text(json.dumps(dataset))

    mock_client = MagicMock()
    mock_client.create_experiment.return_value = "exp-222"
    mock_client.create_run.return_value = MagicMock(info=MagicMock(run_id="run-e2e-2"))

    with patch("agent_gateway.benchmark.results.MlflowClient", return_value=mock_client):
        run_id = run_benchmark_task(
            skill_name="kubernetes-ops",
            task_name="deploy-model",
            agent_name="mlops",
            dataset_path=str(dataset_path),
            tracking_uri="http://mlflow:5000",
        )

    assert run_id == "run-e2e-2"
    # pass_rate should be 0.0 (stub always produces empty output)
    log_metric_calls = {str(c) for c in mock_client.log_metric.call_args_list}
    assert any("pass_rate" in c and "0.0" in c for c in log_metric_calls)


def test_run_benchmark_task_missing_dataset(tmp_path: Path):
    """run_benchmark_task raises FileNotFoundError when dataset path is wrong."""
    with pytest.raises(FileNotFoundError):
        run_benchmark_task(
            skill_name="kubernetes-ops",
            task_name="deploy-model",
            agent_name="mlops",
            dataset_path=str(tmp_path / "nonexistent.json"),
            tracking_uri="http://mlflow:5000",
        )


def test_run_benchmark_task_real_dataset():
    """run_benchmark_task works with the real kubernetes-ops eval dataset on disk."""
    from pathlib import Path as P

    # 4 parents up from tests/ to platform_monorepo root
    monorepo_root = P(__file__).parents[3]
    dataset_path = monorepo_root / "skills" / "eval" / "kubernetes-ops" / "deploy-model.json"

    if not dataset_path.exists():
        pytest.skip("Real eval dataset not present")

    mock_client = MagicMock()
    mock_client.create_experiment.return_value = "exp-real"
    mock_client.create_run.return_value = MagicMock(info=MagicMock(run_id="run-real"))

    with patch("agent_gateway.benchmark.results.MlflowClient", return_value=mock_client):
        run_id = run_benchmark_task(
            skill_name="kubernetes-ops",
            task_name="deploy-model",
            agent_name="mlops",
            dataset_path=str(dataset_path),
            tracking_uri="http://mlflow:5000",
        )

    assert run_id == "run-real"
    # Real dataset has 10+ cases after D.06 expansion
    log_metric_calls = {str(c) for c in mock_client.log_metric.call_args_list}
    total_cases_calls = [c for c in log_metric_calls if "total_cases" in c]
    assert total_cases_calls, "expected total_cases metric to be logged"

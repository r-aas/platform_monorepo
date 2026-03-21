"""Benchmark result recorder — log eval runs to MLflow experiments."""

from __future__ import annotations

import json

from mlflow import MlflowClient

from agent_gateway.benchmark.runner import BenchmarkResult


def record_results(results: BenchmarkResult, tracking_uri: str) -> str:
    """Create/update MLflow experiment and log a benchmark run. Returns run_id."""
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment_name = f"eval:{results.agent}:{results.skill}:{results.task}"

    # Create experiment if it doesn't exist
    try:
        experiment_id = client.create_experiment(experiment_name)
    except Exception:
        experiment = client.get_experiment_by_name(experiment_name)
        experiment_id = experiment.experiment_id if experiment else "0"

    run = client.create_run(experiment_id=experiment_id)
    run_id = run.info.run_id

    # Log aggregate metrics
    client.log_metric(run_id, "pass_rate", results.pass_rate)
    client.log_metric(run_id, "avg_latency", results.avg_latency)
    client.log_metric(run_id, "total_cases", results.total_cases)
    client.log_metric(run_id, "passed_cases", sum(1 for c in results.cases if c.passed))

    # Log params
    client.log_param(run_id, "agent", results.agent)
    client.log_param(run_id, "skill", results.skill)
    client.log_param(run_id, "task", results.task)

    # Attach per-case detail as artifact
    case_data = [
        {
            "id": c.id,
            "passed": c.passed,
            "failures": c.failures,
            "latency": c.latency,
        }
        for c in results.cases
    ]
    client.log_text(run_id, json.dumps(case_data, indent=2), "cases.json")

    client.set_terminated(run_id, status="FINISHED")
    return run_id

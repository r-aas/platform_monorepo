"""Benchmark result recorder — log eval runs to MLflow and PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import logging

from mlflow import MlflowClient

from agent_gateway.benchmark.runner import BenchmarkResult

logger = logging.getLogger(__name__)


def record_results(results: BenchmarkResult, tracking_uri: str) -> str:
    """Create/update MLflow experiment, log a benchmark run, persist to DB. Returns run_id."""
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

    # Persist to PostgreSQL (fire-and-forget in running event loop, or sync)
    _persist_eval_run(results, run_id)

    return run_id


def _persist_eval_run(results: BenchmarkResult, mlflow_run_id: str) -> None:
    """Write eval results to EvalRunRow in PostgreSQL."""
    try:
        from agent_gateway.store.deployments import insert_eval_run

        case_summary = [
            {"id": c.id, "passed": c.passed, "failures": c.failures, "latency": c.latency}
            for c in results.cases
        ]

        # This runs in a thread (from asyncio.to_thread), so use asyncio.run for the DB call
        try:
            loop = asyncio.get_running_loop()
            # Already in an async context — schedule as a task
            loop.create_task(insert_eval_run(
                agent_name=results.agent,
                agent_version="latest",
                environment="k3d-mewtwo",
                model=f"agent:{results.agent}",
                skill=results.skill,
                task=results.task,
                pass_rate=results.pass_rate,
                avg_latency_ms=results.avg_latency * 1000,
                results={"mlflow_run_id": mlflow_run_id, "cases": case_summary},
            ))
        except RuntimeError:
            # No event loop — run synchronously (e.g., from CLI or test)
            asyncio.run(insert_eval_run(
                agent_name=results.agent,
                agent_version="latest",
                environment="k3d-mewtoo",
                model=f"agent:{results.agent}",
                skill=results.skill,
                task=results.task,
                pass_rate=results.pass_rate,
                avg_latency_ms=results.avg_latency * 1000,
                results={"mlflow_run_id": mlflow_run_id, "cases": case_summary},
            ))
    except Exception:
        logger.warning("Failed to persist eval run to DB", exc_info=True)

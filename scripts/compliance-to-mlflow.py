#!/usr/bin/env python3
"""Log compliance check results to MLflow for dashboard/audit trail.

Reads JSON output from agentops-policy.py and logs each agent's results
as an MLflow run in the __agentops_compliance experiment.

Usage:
    uv run scripts/agentops-policy.py --json | uv run scripts/compliance-to-mlflow.py
    uv run scripts/compliance-to-mlflow.py --results compliance-results.json
    uv run scripts/compliance-to-mlflow.py --results compliance-results.json --experiment __agentops_compliance
"""
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28"]
# ///

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.platform.127.0.0.1.nip.io")
API = f"{MLFLOW_URL}/api/2.0/mlflow"
TIMEOUT = 30


def ensure_experiment(name: str) -> str:
    resp = httpx.get(f"{API}/experiments/get-by-name", params={"experiment_name": name}, timeout=TIMEOUT)
    if resp.status_code == 200:
        return resp.json()["experiment"]["experiment_id"]
    resp = httpx.post(f"{API}/experiments/create", json={"name": name}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["experiment_id"]


def log_run(exp_id: str, agent: str, results: list[dict]) -> str:
    """Log one MLflow run per agent with policy pass/fail metrics."""
    now_ms = int(time.time() * 1000)

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    skipped = sum(1 for r in results if r.get("skipped"))
    pass_rate = passed / max(total - skipped, 1)

    run_name = f"compliance-{agent}-{int(time.time())}"
    resp = httpx.post(f"{API}/runs/create", json={
        "experiment_id": exp_id,
        "run_name": run_name,
        "start_time": now_ms,
        "tags": [
            {"key": "agent", "value": agent},
            {"key": "check_type", "value": "compliance"},
            {"key": "mlflow.runName", "value": run_name},
        ],
    }, timeout=TIMEOUT)
    resp.raise_for_status()
    run_id = resp.json()["run"]["info"]["run_id"]

    # Log aggregate metrics
    metrics = [
        {"key": "total_policies", "value": float(total), "timestamp": now_ms},
        {"key": "passed", "value": float(passed), "timestamp": now_ms},
        {"key": "failed", "value": float(failed), "timestamp": now_ms},
        {"key": "skipped", "value": float(skipped), "timestamp": now_ms},
        {"key": "pass_rate", "value": pass_rate, "timestamp": now_ms},
    ]

    # Log per-policy pass/fail as metrics (1.0 = pass, 0.0 = fail)
    for r in results:
        policy_name = r.get("policy", "unknown").replace("-", "_")
        val = 1.0 if r.get("passed") else (0.5 if r.get("skipped") else 0.0)
        metrics.append({"key": f"policy_{policy_name}", "value": val, "timestamp": now_ms})

    for m in metrics:
        httpx.post(f"{API}/runs/log-metric", json={"run_id": run_id, **m}, timeout=TIMEOUT)

    # Log params
    params = [
        {"key": "agent", "value": agent},
        {"key": "timestamp", "value": str(int(time.time()))},
    ]
    for p in params:
        httpx.post(f"{API}/runs/log-parameter", json={"run_id": run_id, **p}, timeout=TIMEOUT)

    # End run
    httpx.post(f"{API}/runs/update", json={
        "run_id": run_id, "status": "FINISHED", "end_time": int(time.time() * 1000),
    }, timeout=TIMEOUT)

    return run_id


def main():
    parser = argparse.ArgumentParser(description="Log compliance results to MLflow")
    parser.add_argument("--results", help="Path to JSON results file (or read from stdin)")
    parser.add_argument("--experiment", default="__agentops_compliance", help="MLflow experiment name")
    args = parser.parse_args()

    # Read results
    if args.results:
        with open(args.results) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    # Handle both formats: list of results or dict with "results" key
    if isinstance(data, list):
        results = data
    elif isinstance(data, dict):
        results = data.get("results", data.get("policies", []))
    else:
        print("ERROR: Unexpected JSON format", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("No results to log.")
        return

    try:
        exp_id = ensure_experiment(args.experiment)
    except Exception as e:
        print(f"ERROR: MLflow unreachable: {e}", file=sys.stderr)
        sys.exit(1)

    # Group by agent
    by_agent: dict[str, list[dict]] = {}
    for r in results:
        agent = r.get("agent", "platform")
        by_agent.setdefault(agent, []).append(r)

    # Log one run per agent
    total_logged = 0
    for agent, agent_results in sorted(by_agent.items()):
        run_id = log_run(exp_id, agent, agent_results)
        passed = sum(1 for r in agent_results if r.get("passed"))
        total = len(agent_results)
        print(f"  ✓ {agent}: {passed}/{total} passed (run {run_id})")
        total_logged += 1

    print(f"\nLogged {total_logged} agent(s) to experiment '{args.experiment}'")


if __name__ == "__main__":
    main()

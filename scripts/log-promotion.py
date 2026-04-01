#!/usr/bin/env python3
"""Log promotion decisions to MLflow.

Records promotion gate results (pass/fail, source/target env, metrics)
to the {agent}-promotions experiment for audit trail.

Usage:
    uv run scripts/log-promotion.py --agent mlops --source dev --target staging --status passed
    uv run scripts/log-promotion.py --agent mlops --source staging --target production --status failed --reason "regression"
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
    """Get or create MLflow experiment, return ID."""
    resp = httpx.get(f"{API}/experiments/get-by-name", params={"experiment_name": name}, timeout=TIMEOUT)
    if resp.status_code == 200:
        return resp.json()["experiment"]["experiment_id"]
    # Create
    resp = httpx.post(f"{API}/experiments/create", json={"name": name}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["experiment_id"]


def main():
    parser = argparse.ArgumentParser(description="Log promotion decision to MLflow")
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--source", required=True, help="Source environment (dev, staging)")
    parser.add_argument("--target", required=True, help="Target environment (staging, production)")
    parser.add_argument("--status", required=True, choices=["passed", "failed", "rolled-back"], help="Promotion result")
    parser.add_argument("--reason", default="", help="Failure/rollback reason")
    parser.add_argument("--version-hash", default="", help="Agent version hash")
    parser.add_argument("--pass-rate", type=float, default=None, help="Eval pass_rate at time of promotion")
    args = parser.parse_args()

    experiment_name = f"{args.agent}-promotions"

    try:
        exp_id = ensure_experiment(experiment_name)
    except Exception as e:
        print(f"ERROR: Could not create/find experiment '{experiment_name}': {e}", file=sys.stderr)
        sys.exit(1)

    # Create run
    run_name = f"{args.source}→{args.target} ({args.status})"
    resp = httpx.post(f"{API}/runs/create", json={
        "experiment_id": exp_id,
        "run_name": run_name,
        "start_time": int(time.time() * 1000),
        "tags": [
            {"key": "agent", "value": args.agent},
            {"key": "source_env", "value": args.source},
            {"key": "target_env", "value": args.target},
            {"key": "status", "value": args.status},
            {"key": "mlflow.runName", "value": run_name},
        ],
    }, timeout=TIMEOUT)
    resp.raise_for_status()
    run_id = resp.json()["run"]["info"]["run_id"]

    # Log params
    params = [
        {"key": "agent", "value": args.agent},
        {"key": "source_env", "value": args.source},
        {"key": "target_env", "value": args.target},
        {"key": "status", "value": args.status},
    ]
    if args.reason:
        params.append({"key": "reason", "value": args.reason})
    if args.version_hash:
        params.append({"key": "version_hash", "value": args.version_hash})

    for p in params:
        httpx.post(f"{API}/runs/log-parameter", json={"run_id": run_id, **p}, timeout=TIMEOUT)

    # Log metrics
    metrics = [{"key": "promoted", "value": 1.0 if args.status == "passed" else 0.0, "timestamp": int(time.time() * 1000)}]
    if args.pass_rate is not None:
        metrics.append({"key": "pass_rate_at_promotion", "value": args.pass_rate, "timestamp": int(time.time() * 1000)})

    for m in metrics:
        httpx.post(f"{API}/runs/log-metric", json={"run_id": run_id, **m}, timeout=TIMEOUT)

    # End run
    httpx.post(f"{API}/runs/update", json={"run_id": run_id, "status": "FINISHED", "end_time": int(time.time() * 1000)}, timeout=TIMEOUT)

    print(f"Logged promotion: {args.agent} {args.source}→{args.target} ({args.status})")
    print(f"  MLflow run: {run_id}")
    print(f"  Experiment: {experiment_name}")


if __name__ == "__main__":
    main()

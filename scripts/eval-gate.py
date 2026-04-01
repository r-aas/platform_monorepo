#!/usr/bin/env python3
"""Eval gate — checks MLflow for passing benchmark run before promotion.

Queries MLflow for the latest benchmark run for an agent, compares against
threshold and baseline. Blocks promotion if requirements aren't met.

Usage:
    uv run scripts/eval-gate.py --agent mlops --threshold 0.85 --gate
    uv run scripts/eval-gate.py --agent mlops --baseline-experiment __baselines --gate
    uv run scripts/eval-gate.py --agent mlops --json
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

import httpx

MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.platform.127.0.0.1.nip.io")
API = f"{MLFLOW_URL}/api/2.0/mlflow"
TIMEOUT = 30


def search_runs(experiment_name: str, filter_string: str = "", max_results: int = 5) -> list[dict]:
    """Search MLflow runs in an experiment."""
    # Get experiment ID
    resp = httpx.get(f"{API}/experiments/get-by-name", params={"experiment_name": experiment_name}, timeout=TIMEOUT)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    exp_id = resp.json()["experiment"]["experiment_id"]

    # Search runs
    body = {
        "experiment_ids": [exp_id],
        "filter_string": filter_string,
        "max_results": max_results,
        "order_by": ["start_time DESC"],
    }
    resp = httpx.post(f"{API}/runs/search", json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("runs", [])


def get_metric(run: dict, key: str) -> float | None:
    """Extract a metric value from an MLflow run."""
    for m in run.get("data", {}).get("metrics", []):
        if m["key"] == key:
            return m["value"]
    return None


def main():
    parser = argparse.ArgumentParser(description="Eval gate — MLflow benchmark check")
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--threshold", type=float, default=0.85, help="Minimum pass_rate (0.0-1.0)")
    parser.add_argument("--baseline-experiment", default="__baselines", help="MLflow experiment for baseline")
    parser.add_argument("--gate", action="store_true", help="Exit 1 if gate fails")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    args = parser.parse_args()

    result = {
        "agent": args.agent,
        "threshold": args.threshold,
        "passed": False,
        "checks": [],
    }

    def check(name: str, passed: bool, reason: str):
        result["checks"].append({"name": name, "passed": passed, "reason": reason})
        return passed

    # 1. Find latest benchmark run
    experiment_name = f"{args.agent}-benchmark"
    try:
        runs = search_runs(experiment_name)
    except Exception as e:
        check("eval-exists", False, f"MLflow unreachable: {e}")
        runs = []

    if not runs:
        check("eval-exists", False, f"No runs in experiment '{experiment_name}'. Run evals first.")
    else:
        latest = runs[0]
        run_id = latest["info"]["run_id"]
        check("eval-exists", True, f"Found run {run_id}")

        # 2. Check pass_rate against threshold
        pass_rate = get_metric(latest, "pass_rate")
        if pass_rate is None:
            check("threshold", False, "No 'pass_rate' metric in latest run")
        elif pass_rate >= args.threshold:
            check("threshold", True, f"pass_rate={pass_rate:.3f} >= {args.threshold}")
        else:
            check("threshold", False, f"pass_rate={pass_rate:.3f} < {args.threshold}")

        # 3. Check against baseline (no regression)
        try:
            baseline_runs = search_runs(args.baseline_experiment, f"tags.agent = '{args.agent}'", max_results=1)
        except Exception:
            baseline_runs = []

        if not baseline_runs:
            check("no-regression", True, "No baseline found — skipping regression check")
        else:
            baseline_pass_rate = get_metric(baseline_runs[0], "pass_rate")
            if baseline_pass_rate is None:
                check("no-regression", True, "Baseline has no pass_rate — skipping")
            elif pass_rate is not None and pass_rate >= baseline_pass_rate:
                check("no-regression", True, f"pass_rate={pass_rate:.3f} >= baseline={baseline_pass_rate:.3f}")
            else:
                check("no-regression", False, f"REGRESSION: pass_rate={pass_rate} < baseline={baseline_pass_rate:.3f}")

    # Overall result
    result["passed"] = all(c["passed"] for c in result["checks"])

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        status = "PASSED" if result["passed"] else "BLOCKED"
        print(f"Eval gate for {args.agent}: {status}")
        for c in result["checks"]:
            icon = "✓" if c["passed"] else "✗"
            print(f"  {icon} {c['name']}: {c['reason']}")

    if args.gate and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

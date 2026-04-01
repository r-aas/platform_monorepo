#!/usr/bin/env python3
"""Regression check — ensures no metric is worse than production baseline.

Compares the latest benchmark run against the blessed baseline in MLflow.
Checks pass_rate, latency_p95, and cost_per_eval.

Usage:
    uv run scripts/regression-check.py --agent mlops --baseline-experiment __baselines
    uv run scripts/regression-check.py --agent mlops --gate --json
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

# Regression thresholds: how much worse is acceptable
REGRESSION_THRESHOLDS = {
    "pass_rate": -0.05,      # max 5% drop
    "latency_p95": 2.0,      # max 2x increase (ratio)
    "cost_per_eval": 1.5,    # max 1.5x increase (ratio)
}


def search_runs(experiment_name: str, filter_string: str = "", max_results: int = 5) -> list[dict]:
    resp = httpx.get(f"{API}/experiments/get-by-name", params={"experiment_name": experiment_name}, timeout=TIMEOUT)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    exp_id = resp.json()["experiment"]["experiment_id"]

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
    for m in run.get("data", {}).get("metrics", []):
        if m["key"] == key:
            return m["value"]
    return None


def main():
    parser = argparse.ArgumentParser(description="Regression check — no metric worse than baseline")
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--baseline-experiment", default="__baselines", help="MLflow baseline experiment")
    parser.add_argument("--gate", action="store_true", help="Exit 1 on regression")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    args = parser.parse_args()

    result = {
        "agent": args.agent,
        "passed": True,
        "checks": [],
    }

    def check(metric: str, passed: bool, reason: str):
        result["checks"].append({"metric": metric, "passed": passed, "reason": reason})
        if not passed:
            result["passed"] = False

    # Get latest benchmark run
    experiment_name = f"{args.agent}-benchmark"
    try:
        current_runs = search_runs(experiment_name, max_results=1)
    except Exception as e:
        check("connectivity", False, f"MLflow unreachable: {e}")
        current_runs = []

    if not current_runs:
        check("eval-exists", False, f"No runs in '{experiment_name}'")
    else:
        current = current_runs[0]

        # Get baseline
        try:
            baseline_runs = search_runs(args.baseline_experiment, f"tags.agent = '{args.agent}'", max_results=1)
        except Exception:
            baseline_runs = []

        if not baseline_runs:
            check("baseline-exists", True, "No baseline — skipping regression checks (first run)")
        else:
            baseline = baseline_runs[0]

            # Check pass_rate (higher is better — regression = lower)
            curr_pr = get_metric(current, "pass_rate")
            base_pr = get_metric(baseline, "pass_rate")
            if curr_pr is not None and base_pr is not None:
                delta = curr_pr - base_pr
                threshold = REGRESSION_THRESHOLDS["pass_rate"]
                if delta >= threshold:
                    check("pass_rate", True, f"{curr_pr:.3f} vs baseline {base_pr:.3f} (delta={delta:+.3f}, allowed={threshold:+.3f})")
                else:
                    check("pass_rate", False, f"REGRESSION: {curr_pr:.3f} vs baseline {base_pr:.3f} (delta={delta:+.3f}, max allowed={threshold:+.3f})")
            else:
                check("pass_rate", True, "Metric not available — skipping")

            # Check latency_p95 (lower is better — regression = higher)
            curr_lat = get_metric(current, "latency_p95")
            base_lat = get_metric(baseline, "latency_p95")
            if curr_lat is not None and base_lat is not None and base_lat > 0:
                ratio = curr_lat / base_lat
                max_ratio = REGRESSION_THRESHOLDS["latency_p95"]
                if ratio <= max_ratio:
                    check("latency_p95", True, f"{curr_lat:.1f}s vs baseline {base_lat:.1f}s (ratio={ratio:.2f}x, max={max_ratio}x)")
                else:
                    check("latency_p95", False, f"REGRESSION: {curr_lat:.1f}s vs baseline {base_lat:.1f}s (ratio={ratio:.2f}x, max={max_ratio}x)")
            else:
                check("latency_p95", True, "Metric not available — skipping")

            # Check cost_per_eval (lower is better — regression = higher)
            curr_cost = get_metric(current, "cost_per_eval")
            base_cost = get_metric(baseline, "cost_per_eval")
            if curr_cost is not None and base_cost is not None and base_cost > 0:
                ratio = curr_cost / base_cost
                max_ratio = REGRESSION_THRESHOLDS["cost_per_eval"]
                if ratio <= max_ratio:
                    check("cost_per_eval", True, f"${curr_cost:.4f} vs baseline ${base_cost:.4f} (ratio={ratio:.2f}x, max={max_ratio}x)")
                else:
                    check("cost_per_eval", False, f"REGRESSION: ${curr_cost:.4f} vs baseline ${base_cost:.4f} (ratio={ratio:.2f}x, max={max_ratio}x)")
            else:
                check("cost_per_eval", True, "Metric not available — skipping")

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        status = "PASSED" if result["passed"] else "REGRESSION DETECTED"
        print(f"Regression check for {args.agent}: {status}")
        for c in result["checks"]:
            icon = "✓" if c["passed"] else "✗"
            print(f"  {icon} {c['metric']}: {c['reason']}")

    if args.gate and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

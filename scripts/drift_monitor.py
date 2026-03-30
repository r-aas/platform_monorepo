#!/usr/bin/env python3
"""Drift Monitor — compare recent trace metrics against baselines.

Usage:
    uv run python scripts/drift_monitor.py [--prompt assistant] [--window 24]

Workflow:
    1. Fetch baseline for prompt from /webhook/traces (baseline_get)
    2. Fetch recent trace summary for the prompt
    3. Compare against thresholds (env vars or baseline)
    4. Log results to MLflow __drift experiment
    5. Exit code 1 if any threshold breached

Environment variables:
    N8N_BASE_URL          — n8n webhook base (default: http://localhost:5678/webhook)
    DRIFT_LATENCY_MAX_MS  — max avg latency before alert (default: 10000)
    DRIFT_ERROR_RATE_MAX  — max error rate before alert (default: 0.1)
    DRIFT_TOKEN_BUDGET_DAILY — max tokens per day before alert (default: 100000)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import httpx

BASE = os.environ.get("N8N_BASE_URL", "http://localhost:5678/webhook")
LATENCY_MAX = float(os.environ.get("DRIFT_LATENCY_MAX_MS", "10000"))
ERROR_RATE_MAX = float(os.environ.get("DRIFT_ERROR_RATE_MAX", "0.1"))
TOKEN_BUDGET = int(os.environ.get("DRIFT_TOKEN_BUDGET_DAILY", "100000"))


def post(endpoint: str, data: dict) -> dict:
    """POST JSON to n8n webhook."""
    r = httpx.post(f"{BASE}/{endpoint}", json=data, timeout=30)
    r.raise_for_status()
    return r.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="GenAI MLOps Drift Monitor")
    parser.add_argument("--prompt", default="assistant", help="Prompt name to check")
    parser.add_argument("--window", type=int, default=24, help="Hours to look back")
    args = parser.parse_args()

    prompt_name = args.prompt
    window_hours = args.window
    drifted = False
    alerts: list[str] = []

    print(f"── Drift Monitor ── {datetime.now().isoformat()}")
    print(f"   Prompt: {prompt_name}, Window: {window_hours}h")
    print()

    # 1. Get baseline
    try:
        baseline = post(
            "traces",
            {
                "action": "baseline_get",
                "prompt_name": prompt_name,
            },
        )
        baseline_metrics = baseline.get("metrics", {})
        print(f"   Baseline: {json.dumps(baseline_metrics)}")
    except Exception as e:
        print(f"   ⚠ No baseline found for {prompt_name}: {e}")
        baseline_metrics = {}

    # 2. Run drift check via trace workflow
    try:
        drift = post(
            "traces",
            {
                "action": "drift_check",
                "prompt_name": prompt_name,
                "window_hours": window_hours,
            },
        )
        print(f"   Drift check: drifted={drift.get('drifted')}")
        if drift.get("drifted"):
            drifted = True
            for metric_name, info in drift.get("drift_metrics", {}).items():
                if info.get("drifted"):
                    alerts.append(
                        f"{metric_name}: current={info.get('current')}, "
                        f"baseline={info.get('baseline')}, "
                        f"threshold={info.get('threshold')}"
                    )
    except Exception as e:
        print(f"   ⚠ Drift check failed: {e}")

    # 3. Check against hard thresholds from env vars
    try:
        summary = post(
            "traces",
            {
                "action": "search",
                "prompt_name": prompt_name,
                "limit": 100,
            },
        )
        traces = summary.get("traces", [])
        if traces:
            latencies = [t.get("latency_ms", 0) for t in traces if t.get("latency_ms")]
            errors = [t for t in traces if t.get("status") == "error"]
            total_tokens = sum(t.get("total_tokens", 0) for t in traces)

            if latencies:
                avg_latency = sum(latencies) / len(latencies)
                if avg_latency > LATENCY_MAX:
                    drifted = True
                    alerts.append(f"avg_latency_ms: {avg_latency:.0f} > {LATENCY_MAX}")
                print(f"   Avg latency: {avg_latency:.0f}ms (max: {LATENCY_MAX})")

            if traces:
                error_rate = len(errors) / len(traces)
                if error_rate > ERROR_RATE_MAX:
                    drifted = True
                    alerts.append(f"error_rate: {error_rate:.3f} > {ERROR_RATE_MAX}")
                print(
                    f"   Error rate: {error_rate:.3f} "
                    f"({len(errors)}/{len(traces)}, max: {ERROR_RATE_MAX})"
                )

            print(f"   Total tokens: {total_tokens} (budget: {TOKEN_BUDGET})")
            if total_tokens > TOKEN_BUDGET:
                drifted = True
                alerts.append(f"token_budget: {total_tokens} > {TOKEN_BUDGET}")
        else:
            print("   No traces found in window")
    except Exception as e:
        print(f"   ⚠ Trace search failed: {e}")

    # 4. Print results
    print()
    if drifted:
        print("   🚨 DRIFT DETECTED:")
        for alert in alerts:
            print(f"      - {alert}")
        print()
        return 1
    else:
        print("   ✓ No drift detected")
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())

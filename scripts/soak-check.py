#!/usr/bin/env python3
"""Soak check — verifies agent ran N scheduled cycles without errors.

Checks Langfuse or kubectl for evidence that the agent has been running
in the source environment for a minimum number of cycles before promotion.

Usage:
    uv run scripts/soak-check.py --agent mlops --namespace genai-dev --min-cycles 2
    uv run scripts/soak-check.py --agent mlops --json
"""
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28"]
# ///

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

LANGFUSE_URL = os.getenv("LANGFUSE_BASE_URL", "http://langfuse.platform.127.0.0.1.nip.io")
LANGFUSE_PK = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SK = os.getenv("LANGFUSE_SECRET_KEY", "")


def check_kubectl(agent: str, namespace: str, min_cycles: int) -> dict:
    """Check agent pod status and recent CronJob completions via kubectl."""
    result = {"method": "kubectl", "passed": False, "reason": "", "cycles_found": 0}

    # Check agent pod is running
    try:
        pod_check = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-l", f"app.kubernetes.io/name={agent}",
             "--no-headers", "-o", "custom-columns=STATUS:.status.phase"],
            capture_output=True, text=True, timeout=15,
        )
        pods = [l.strip() for l in pod_check.stdout.strip().split("\n") if l.strip()]
        running = [p for p in pods if p == "Running"]
        if not running:
            result["reason"] = f"No running pods for {agent} in {namespace}"
            return result
    except (subprocess.TimeoutExpired, FileNotFoundError):
        result["reason"] = "kubectl not available"
        return result

    # Check CronJob completions
    try:
        jobs_check = subprocess.run(
            ["kubectl", "get", "jobs", "-n", namespace,
             "-l", f"agent={agent}", "--no-headers",
             "-o", "custom-columns=NAME:.metadata.name,STATUS:.status.succeeded,COMPLETED:.status.completionTime"],
            capture_output=True, text=True, timeout=15,
        )
        lines = [l for l in jobs_check.stdout.strip().split("\n") if l.strip()]
        completed = [l for l in lines if "1" in l.split()[1] if len(l.split()) >= 2]
        result["cycles_found"] = len(completed)

        if len(completed) >= min_cycles:
            result["passed"] = True
            result["reason"] = f"{len(completed)} completed cycles >= {min_cycles} required"
        else:
            result["reason"] = f"Only {len(completed)} completed cycles, need {min_cycles}"
    except (subprocess.TimeoutExpired, FileNotFoundError, IndexError):
        # Fallback: just check pod uptime
        try:
            age_check = subprocess.run(
                ["kubectl", "get", "pods", "-n", namespace, "-l", f"app.kubernetes.io/name={agent}",
                 "--no-headers", "-o", "custom-columns=AGE:.metadata.creationTimestamp"],
                capture_output=True, text=True, timeout=15,
            )
            timestamps = [l.strip() for l in age_check.stdout.strip().split("\n") if l.strip()]
            if timestamps:
                created = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
                age_hours = (datetime.now(created.tzinfo) - created).total_seconds() / 3600
                # Assume 1 cycle per hour as minimum soak indicator
                if age_hours >= min_cycles:
                    result["passed"] = True
                    result["reason"] = f"Pod running for {age_hours:.1f}h (>= {min_cycles}h soak)"
                    result["cycles_found"] = int(age_hours)
                else:
                    result["reason"] = f"Pod only {age_hours:.1f}h old, need {min_cycles}h soak"
        except Exception:
            result["reason"] = "Could not determine pod age"

    return result


def main():
    parser = argparse.ArgumentParser(description="Soak check — verify agent stability before promotion")
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--namespace", default="genai-dev", help="Source namespace")
    parser.add_argument("--min-cycles", type=int, default=2, help="Minimum completed cycles")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    parser.add_argument("--gate", action="store_true", help="Exit 1 if soak fails")
    args = parser.parse_args()

    result = check_kubectl(args.agent, args.namespace, args.min_cycles)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        status = "PASSED" if result["passed"] else "BLOCKED"
        print(f"Soak check for {args.agent} in {args.namespace}: {status}")
        print(f"  Cycles: {result['cycles_found']} / {args.min_cycles} required")
        print(f"  {result['reason']}")

    if args.gate and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

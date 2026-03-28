"""Benchmark runner — execute eval datasets against agent tasks.

Supports two modes:
- Live mode: sends each case to the gateway via HTTP, evaluates real output
- Stub mode (fallback): evaluates with empty output for structure validation
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


@dataclass
class CaseResult:
    id: str
    passed: bool
    failures: list[str]
    latency: float
    actual_output: str


@dataclass
class BenchmarkResult:
    agent: str
    skill: str
    task: str
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def total_cases(self) -> int:
        return len(self.cases)

    @property
    def pass_rate(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for c in self.cases if c.passed) / len(self.cases)

    @property
    def avg_latency(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.latency for c in self.cases) / len(self.cases)


def evaluate_case(
    case: dict,
    actual_output: str,
    tools_used: list[str],
    latency_seconds: float,
) -> CaseResult:
    """Pure evaluation: check output strings, tool usage, and latency."""
    failures: list[str] = []
    output_lower = actual_output.lower()

    for expected in case.get("expected_output_contains", []):
        if expected.lower() not in output_lower:
            failures.append(f"missing expected string: '{expected}'")

    for expected_tool in case.get("expected_tools_used", []):
        if expected_tool not in tools_used:
            failures.append(f"missing expected tool: '{expected_tool}'")

    max_latency = case.get("max_latency_seconds")
    if max_latency is not None and latency_seconds > max_latency:
        failures.append(f"latency {latency_seconds:.1f}s exceeds max {max_latency}s")

    return CaseResult(
        id=case["id"],
        passed=len(failures) == 0,
        failures=failures,
        latency=latency_seconds,
        actual_output=actual_output,
    )


def load_dataset(path: Path) -> dict:
    """Load an eval dataset JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    return json.loads(path.read_text())


def _invoke_gateway(agent_name: str, message: str, gateway_url: str) -> tuple[str, float]:
    """Call the gateway chat endpoint synchronously. Returns (output, latency_seconds)."""
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{gateway_url}/v1/chat/completions",
                json={
                    "model": f"agent:{agent_name}",
                    "messages": [{"role": "user", "content": message}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        latency = time.monotonic() - t0
        logger.warning("Gateway call failed for case: %s", exc)
        return f"ERROR: {exc}", latency

    latency = time.monotonic() - t0
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return content, latency


def run_benchmark_task(
    skill_name: str,
    task_name: str,
    agent_name: str,
    dataset_path: str,
    tracking_uri: str,
    gateway_url: str = "",
) -> str:
    """Load dataset, run cases against gateway (or stub), record to MLflow.

    Args:
        gateway_url: If provided, sends cases to live gateway. Otherwise uses stub mode.

    Returns: MLflow run_id
    """
    from agent_gateway.benchmark.results import record_results

    dataset = load_dataset(Path(dataset_path))
    results = BenchmarkResult(agent=agent_name, skill=skill_name, task=task_name)
    live_mode = bool(gateway_url)

    for case in dataset.get("cases", []):
        if live_mode:
            output, latency = _invoke_gateway(agent_name, case["input"], gateway_url)
        else:
            output, latency = "", 0.0

        result = evaluate_case(
            case=case,
            actual_output=output,
            tools_used=[],  # TODO: extract from gateway response metadata
            latency_seconds=latency,
        )
        results.cases.append(result)

        if live_mode:
            logger.info(
                "Case %s: %s (%.1fs) %s",
                case["id"],
                "PASS" if result.passed else "FAIL",
                latency,
                result.failures if result.failures else "",
            )

    return record_results(results, tracking_uri=tracking_uri)

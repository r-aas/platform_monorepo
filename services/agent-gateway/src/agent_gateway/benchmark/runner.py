"""Benchmark runner — execute eval datasets against agent tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


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


def run_benchmark_task(skill_name: str, task_name: str, agent_name: str, dataset_path: str, tracking_uri: str) -> str:
    """Load dataset, evaluate stub results (no live gateway), record to MLflow. Returns run_id."""
    from agent_gateway.benchmark.results import record_results

    dataset = load_dataset(Path(dataset_path))
    results = BenchmarkResult(agent=agent_name, skill=skill_name, task=task_name)
    for case in dataset.get("cases", []):
        # Without a live gateway, record cases as pending (empty output, zero latency)
        result = evaluate_case(
            case=case,
            actual_output="",
            tools_used=[],
            latency_seconds=0.0,
        )
        results.cases.append(result)

    return record_results(results, tracking_uri=tracking_uri)

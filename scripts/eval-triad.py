#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "rich>=13.9", "python-dotenv>=1.0"]
# ///
"""Evaluation Triad Benchmark Runner.

Runs externalized JSONL datasets through the agent chat pipeline,
scores responses with LLM-as-judge, compares across models,
and logs everything to MLflow.

Usage:
    uv run scripts/eval-triad.py                              # all datasets, default model
    uv run scripts/eval-triad.py -d coder.review              # single dataset
    uv run scripts/eval-triad.py -m qwen2.5:7b qwen2.5:14b   # compare models
    uv run scripts/eval-triad.py --dry-run                    # validate datasets only
    uv run scripts/eval-triad.py --no-judge                   # skip judge scoring
    uv run scripts/eval-triad.py --no-mlflow                  # skip MLflow logging
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Load .env so WEBHOOK_API_KEY, N8N_BASE_URL, etc. are available without
# requiring the caller to `source .env` first or use Taskfile dotenv.
load_dotenv(Path(__file__).parent.parent / ".env")

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = os.getenv("N8N_BASE_URL", "http://localhost:5678/webhook")
MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5050")
BENCHMARK_DIR = Path(__file__).parent.parent / "data" / "benchmarks"
CHAT_TIMEOUT = 180
JUDGE_TIMEOUT = 120
API_KEY = os.getenv("WEBHOOK_API_KEY", "")

console = Console()


# ── Data Model ────────────────────────────────────────────────────────────────


@dataclass
class Case:
    """Single evaluation case from a JSONL dataset."""

    input: str
    expected: str
    criteria: str
    domain: str
    task: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class Result:
    """Benchmark result for one case x one model."""

    case: Case
    model: str
    response: str = ""
    latency_ms: int = 0
    judge_score: float = 0.0
    judge_reason: str = ""
    error: str = ""
    trace_id: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and self.judge_score >= 0.5


# ── Dataset Loader ────────────────────────────────────────────────────────────


def discover_datasets(directory: Path) -> dict[str, Path]:
    """Find all .jsonl files, keyed by stem (e.g. 'coder.review')."""
    return {p.stem: p for p in sorted(directory.glob("*.jsonl"))}


def load_dataset(path: Path) -> list[Case]:
    """Load JSONL file into Case objects."""
    cases = []
    for i, line in enumerate(path.read_text().strip().splitlines(), 1):
        try:
            d = json.loads(line)
            cases.append(
                Case(
                    input=d["input"],
                    expected=d["expected"],
                    criteria=d["criteria"],
                    domain=d["domain"],
                    task=d.get("task", ""),
                    tags=d.get("tags", []),
                )
            )
        except (json.JSONDecodeError, KeyError) as e:
            console.print(f"[red]  skip {path.name} line {i}: {e}[/]")
    return cases


# ── HTTP Clients ──────────────────────────────────────────────────────────────


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def chat(agent: str, message: str, task: str = "", model: str = "") -> dict:
    """Send message to /webhook/chat. Returns response dict."""
    payload: dict = {"agent_name": agent, "message": message}
    if task and task != "general":
        payload["task"] = task
    if model:
        payload["model"] = model
    try:
        r = httpx.post(
            f"{BASE_URL}/chat",
            json=payload,
            headers=_headers(),
            timeout=CHAT_TIMEOUT,
        )
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "response": ""}
        if not r.content or not r.content.strip():
            return {"error": "empty response body", "response": ""}
        return r.json()
    except httpx.HTTPError as e:
        return {"error": str(e), "response": ""}
    except json.JSONDecodeError as e:
        return {"error": f"invalid JSON: {e}", "response": ""}


def judge_score(
    criteria: str, user_input: str, response: str, domain: str = ""
) -> dict:
    """Score a response using a domain-specific or generic judge via /webhook/eval.

    Uses ``judge.{domain}`` if available, falls back to ``judge``.
    """
    # Domain-specific judges understand nuances better than the generic one
    prompts_to_try = []
    if domain:
        prompts_to_try.append(f"judge.{domain}")
    prompts_to_try.append("judge")  # always have generic fallback

    for prompt_name in prompts_to_try:
        payload = {
            "prompt_name": prompt_name,
            "temperature": 0,
            "test_cases": [
                {
                    "variables": {
                        "criteria": criteria,
                        "input": user_input,
                        "response": response,
                    },
                    "label": "triad-judge",
                }
            ],
        }
        try:
            r = httpx.post(
                f"{BASE_URL}/eval",
                json=payload,
                headers=_headers(),
                timeout=JUDGE_TIMEOUT,
            )
            if r.status_code == 404 and prompt_name != "judge":
                continue  # domain judge not found, try generic
            if r.status_code != 200:
                return {"score": 0.0, "reason": f"HTTP {r.status_code}"}
            data = r.json()
            text = data["results"][0]["response"].strip()
            # Extract JSON from possible markdown code fence
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            parsed = json.loads(text)
            return {
                "score": float(parsed.get("score", 0.0)),
                "reason": parsed.get("reason", ""),
            }
        except Exception as e:
            if prompt_name != "judge":
                continue  # try generic fallback on any error
            return {"score": 0.0, "reason": f"judge error: {e}"}

    return {"score": 0.0, "reason": "no judge available"}


# ── MLflow Logger ─────────────────────────────────────────────────────────────


def log_to_mlflow(
    dataset_name: str, model: str, results: list[Result]
) -> str | None:
    """Log benchmark run to MLflow. Returns run_id or None."""
    experiment_name = f"benchmark/{dataset_name}"
    try:
        client = httpx.Client(base_url=MLFLOW_URL, timeout=30)

        # Get or create experiment
        r = client.get(
            "/api/2.0/mlflow/experiments/get-by-name",
            params={"experiment_name": experiment_name},
        )
        if r.status_code == 200 and "experiment" in r.json():
            exp_id = r.json()["experiment"]["experiment_id"]
        else:
            r = client.post(
                "/api/2.0/mlflow/experiments/create",
                json={"name": experiment_name},
            )
            exp_id = r.json()["experiment_id"]

        # Create run
        now_ms = int(time.time() * 1000)
        r = client.post(
            "/api/2.0/mlflow/runs/create",
            json={
                "experiment_id": exp_id,
                "start_time": now_ms,
                "tags": [
                    {"key": "mlflow.runName", "value": model or "(default)"},
                    {"key": "benchmark.model", "value": model or "(default)"},
                    {"key": "benchmark.dataset", "value": dataset_name},
                    {"key": "benchmark.cases", "value": str(len(results))},
                ],
            },
        )
        run_id = r.json()["run"]["info"]["run_id"]

        # Log params
        for key, val in [
            ("model", model or "(default)"),
            ("dataset", dataset_name),
            ("cases", str(len(results))),
        ]:
            client.post(
                "/api/2.0/mlflow/runs/log-param",
                json={"run_id": run_id, "key": key, "value": val},
            )

        # Compute metrics
        scored = [r for r in results if r.judge_score > 0]
        avg_score = (
            sum(r.judge_score for r in scored) / len(scored) if scored else 0.0
        )
        avg_latency = (
            sum(r.latency_ms for r in results) / len(results) if results else 0
        )
        pass_rate = (
            sum(1 for r in results if r.passed) / len(results)
            if results
            else 0.0
        )

        for key, val in [
            ("avg_score", avg_score),
            ("avg_latency_ms", avg_latency),
            ("pass_rate", pass_rate),
            ("total_cases", float(len(results))),
            ("passed", float(sum(1 for r in results if r.passed))),
            ("failed", float(sum(1 for r in results if not r.passed))),
        ]:
            client.post(
                "/api/2.0/mlflow/runs/log-metric",
                json={
                    "run_id": run_id,
                    "key": key,
                    "value": val,
                    "timestamp": now_ms,
                },
            )

        # Finalize
        client.post(
            "/api/2.0/mlflow/runs/update",
            json={
                "run_id": run_id,
                "status": "FINISHED",
                "end_time": int(time.time() * 1000),
            },
        )
        client.close()
        return run_id

    except Exception as e:
        console.print(f"[yellow]  MLflow log failed: {e}[/]")
        return None


# ── Runner ────────────────────────────────────────────────────────────────────


def run_benchmark(
    cases: list[Case], model: str, use_judge: bool = True
) -> list[Result]:
    """Run all cases for one model, return results."""
    results = []
    for i, case in enumerate(cases, 1):
        console.print(
            f"  [{i}/{len(cases)}] {case.domain}.{case.task} "
            f"[dim]{case.tags}[/]",
            end=" ",
        )

        t0 = time.time()
        resp = chat(case.domain, case.input, task=case.task, model=model)
        latency_ms = int((time.time() - t0) * 1000)

        output = resp.get("response", "") or resp.get("output", "")
        error = resp.get("error", "")
        trace_id = resp.get("trace_id", "")

        result = Result(
            case=case,
            model=model,
            response=output,
            latency_ms=latency_ms,
            error=error,
            trace_id=trace_id,
        )

        if error:
            console.print(f"[red]ERR {latency_ms}ms[/] {error}")
            results.append(result)
            continue

        if use_judge and output:
            j = judge_score(case.criteria, case.input, output, case.domain)
            result.judge_score = j["score"]
            result.judge_reason = j["reason"]

        icon = "[green]PASS[/]" if result.passed else "[red]FAIL[/]"
        console.print(f"{icon} {latency_ms}ms score={result.judge_score:.2f}")
        if result.judge_reason:
            console.print(f"        [dim]{result.judge_reason[:100]}[/]")

        results.append(result)

    return results


def _run_single_case(
    case: Case, model: str, use_judge: bool
) -> Result:
    """Run a single case — designed for concurrent execution."""
    t0 = time.time()
    resp = chat(case.domain, case.input, task=case.task, model=model)
    latency_ms = int((time.time() - t0) * 1000)

    output = resp.get("response", "") or resp.get("output", "")
    error = resp.get("error", "")
    trace_id = resp.get("trace_id", "")

    result = Result(
        case=case,
        model=model,
        response=output,
        latency_ms=latency_ms,
        error=error,
        trace_id=trace_id,
    )

    if not error and use_judge and output:
        j = judge_score(case.criteria, case.input, output, case.domain)
        result.judge_score = j["score"]
        result.judge_reason = j["reason"]

    return result


def run_benchmark_parallel(
    cases: list[Case],
    model: str,
    use_judge: bool = True,
    max_workers: int = 4,
) -> list[Result]:
    """Run cases concurrently with a thread pool."""
    results: list[Result] = [None] * len(cases)  # type: ignore[list-item]
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_idx = {
            pool.submit(_run_single_case, case, model, use_judge): i
            for i, case in enumerate(cases)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                result = future.result()
            except Exception as e:
                case = cases[idx]
                result = Result(
                    case=case,
                    model=model,
                    response="",
                    latency_ms=0,
                    error=f"crash: {e}",
                )
            results[idx] = result
            completed += 1

            icon = "[green]PASS[/]" if result.passed else "[red]FAIL[/]"
            tag = f"{result.case.domain}.{result.case.task}"
            console.print(
                f"  [{completed}/{len(cases)}] {tag} "
                f"{icon} {result.latency_ms}ms "
                f"score={result.judge_score:.2f}"
            )

    return results


# ── Display ───────────────────────────────────────────────────────────────────


def summary_table(
    dataset_name: str, all_runs: dict[str, list[Result]]
) -> None:
    """Rich table for one dataset across all models."""
    table = Table(
        title=f"Benchmark: {dataset_name}",
        show_lines=True,
        title_style="bold cyan",
    )
    table.add_column("Case", style="bold")
    table.add_column("Tags", style="dim")
    for model in all_runs:
        table.add_column(model, justify="center")

    first_results = list(all_runs.values())[0]
    for i, result in enumerate(first_results):
        row: list[str] = [
            f"{result.case.domain}.{result.case.task}",
            ", ".join(result.case.tags[:2]),
        ]
        for _model, model_results in all_runs.items():
            r = model_results[i]
            if r.error:
                cell = "[red]ERR[/]"
            elif r.passed:
                cell = f"[green]{r.judge_score:.2f}[/] {r.latency_ms}ms"
            else:
                cell = f"[red]{r.judge_score:.2f}[/] {r.latency_ms}ms"
            row.append(cell)
        table.add_row(*row)

    # Totals
    totals_row: list[str] = ["[bold]TOTAL[/]", ""]
    for _model, model_results in all_runs.items():
        scored = [r for r in model_results if r.judge_score > 0]
        avg = sum(r.judge_score for r in scored) / len(scored) if scored else 0
        passed = sum(1 for r in model_results if r.passed)
        avg_ms = (
            sum(r.latency_ms for r in model_results) / len(model_results)
            if model_results
            else 0
        )
        color = "green" if avg >= 0.7 else "yellow" if avg >= 0.5 else "red"
        totals_row.append(
            f"[{color}]{avg:.2f}[/] {passed}/{len(model_results)} {avg_ms:.0f}ms"
        )
    table.add_row(*totals_row)

    console.print(table)


def comparison_table(
    all_datasets: dict[str, dict[str, list[Result]]],
) -> None:
    """Cross-dataset comparison when multiple models used."""
    models: set[str] = set()
    for runs in all_datasets.values():
        models.update(runs.keys())
    if len(models) < 2:
        return

    table = Table(
        title="Model Comparison",
        show_lines=True,
        title_style="bold magenta",
    )
    table.add_column("Dataset", style="bold")
    for model in sorted(models):
        table.add_column(model, justify="center")

    for ds_name, runs in all_datasets.items():
        row: list[str] = [ds_name]
        for model in sorted(models):
            model_results = runs.get(model, [])
            if not model_results:
                row.append("[dim]--[/]")
                continue
            scored = [r for r in model_results if r.judge_score > 0]
            avg = (
                sum(r.judge_score for r in scored) / len(scored)
                if scored
                else 0
            )
            passed = sum(1 for r in model_results if r.passed)
            color = (
                "green" if avg >= 0.7 else "yellow" if avg >= 0.5 else "red"
            )
            row.append(
                f"[{color}]{avg:.2f}[/] ({passed}/{len(model_results)})"
            )
        table.add_row(*row)

    console.print(table)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluation Triad Benchmark Runner"
    )
    parser.add_argument(
        "-d", "--datasets", nargs="*",
        help="Dataset names (e.g. coder.review). Default: all.",
    )
    parser.add_argument(
        "-m", "--models", nargs="*",
        help="Models to compare (e.g. qwen2.5:7b qwen2.5:14b). Default: stack default.",
    )
    parser.add_argument(
        "-t", "--threshold", type=float, default=0.5,
        help="Judge score pass threshold (default: 0.5).",
    )
    parser.add_argument(
        "--no-judge", action="store_true",
        help="Skip LLM-as-judge scoring.",
    )
    parser.add_argument(
        "--no-mlflow", action="store_true",
        help="Skip MLflow experiment logging.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate datasets only, don't run.",
    )
    parser.add_argument(
        "--parallel", type=int, nargs="?", const=4, default=0,
        help="Run cases concurrently (default workers: 4).",
    )
    args = parser.parse_args()

    # Discover
    available = discover_datasets(BENCHMARK_DIR)
    if not available:
        console.print(f"[red]No .jsonl files in {BENCHMARK_DIR}[/]")
        sys.exit(1)

    # Filter datasets
    if args.datasets:
        selected = {k: v for k, v in available.items() if k in args.datasets}
        missing = set(args.datasets) - set(selected)
        if missing:
            console.print(f"[red]Unknown datasets: {missing}[/]")
            console.print(f"Available: {list(available.keys())}")
            sys.exit(1)
    else:
        selected = available

    models = args.models or [""]

    # Header
    console.print(
        Panel(
            f"[bold]Evaluation Triad Benchmark[/]\n"
            f"Datasets: {list(selected.keys())}\n"
            f"Models: {models if models != [''] else ['(stack default)']}\n"
            f"Judge: {'off' if args.no_judge else 'on'} | "
            f"MLflow: {'off' if args.no_mlflow else 'on'} | "
            f"Parallel: {args.parallel or 'off'} | "
            f"Threshold: {args.threshold}",
            border_style="cyan",
        )
    )

    # Load datasets
    loaded: dict[str, list[Case]] = {}
    total_cases = 0
    for name, path in selected.items():
        cases = load_dataset(path)
        loaded[name] = cases
        total_cases += len(cases)
        console.print(
            f"  [green]{name}[/]: {len(cases)} cases [dim]({path.name})[/]"
        )

    if args.dry_run:
        console.print(
            f"\n[cyan]Dry run:[/] {total_cases} cases across "
            f"{len(loaded)} datasets validated."
        )
        return

    console.print()

    # Execute
    all_datasets: dict[str, dict[str, list[Result]]] = {}
    run_ids: list[str] = []
    total_passed = 0
    total_failed = 0

    for ds_name, cases in loaded.items():
        all_runs: dict[str, list[Result]] = {}

        for model in models:
            model_label = model or "(default)"
            console.rule(f"{ds_name} x {model_label}")

            if args.parallel:
                results = run_benchmark_parallel(
                    cases,
                    model=model,
                    use_judge=not args.no_judge,
                    max_workers=args.parallel,
                )
            else:
                results = run_benchmark(
                    cases, model=model, use_judge=not args.no_judge
                )
            all_runs[model_label] = results

            passed = sum(1 for r in results if r.passed)
            failed = len(results) - passed
            total_passed += passed
            total_failed += failed

            if not args.no_mlflow:
                run_id = log_to_mlflow(ds_name, model_label, results)
                if run_id:
                    run_ids.append(run_id)
                    console.print(f"  [dim]MLflow run: {run_id[:8]}[/]")

        all_datasets[ds_name] = all_runs
        console.print()
        summary_table(ds_name, all_runs)

    comparison_table(all_datasets)

    # Final
    total = total_passed + total_failed
    console.print()
    if total_failed > 0:
        console.print(
            f"[red bold]{total_passed}/{total} passed[/] "
            f"({total_failed} failed)"
        )
        if run_ids:
            console.print(f"[dim]MLflow runs: {len(run_ids)} logged[/]")
        sys.exit(1)
    else:
        console.print(f"[green bold]{total_passed}/{total} passed[/]")
        if run_ids:
            console.print(
                f"[dim]MLflow runs: {len(run_ids)} logged to {MLFLOW_URL}[/]"
            )


if __name__ == "__main__":
    main()

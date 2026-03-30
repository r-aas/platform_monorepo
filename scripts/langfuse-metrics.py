#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "rich>=13.9"]
# ///
"""Langfuse metrics dashboard — cost, latency, and quality scores.

Queries the Langfuse public API and renders tables in the terminal.
Uses /traces as the primary data source (lightweight) with /observations
as optional enrichment. Handles ClickHouse memory limits gracefully.

Usage:
    uv run scripts/langfuse-metrics.py summary              # overview dashboard
    uv run scripts/langfuse-metrics.py latency               # p50/p95/p99 per model
    uv run scripts/langfuse-metrics.py cost                  # token usage & cost per model
    uv run scripts/langfuse-metrics.py scores                # quality scores from judges
    uv run scripts/langfuse-metrics.py traces --limit 20     # recent traces
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://localhost:3100")
LANGFUSE_PK = os.getenv("LANGFUSE_PUBLIC_KEY", "lf-pk-local")
LANGFUSE_SK = os.getenv("LANGFUSE_SECRET_KEY", "lf-sk-local")
TIMEOUT = 30

console = Console()


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _get(path: str, params: dict | None = None) -> dict | None:
    """GET from Langfuse public API with basic auth. Returns None on error."""
    url = f"{LANGFUSE_HOST}/api/public{path}"
    try:
        r = httpx.get(url, auth=(LANGFUSE_PK, LANGFUSE_SK), params=params, timeout=TIMEOUT)
    except httpx.ConnectError:
        console.print(f"[dim]Connection refused — Langfuse not running?[/]")
        return None
    if r.status_code in (422, 500, 502, 503):
        # ClickHouse OOM, restarting, or query too broad — not fatal
        return None
    if r.status_code != 200:
        console.print(f"[red]HTTP {r.status_code}: {r.text[:200]}[/]")
        return None
    return r.json()


def _paginate(
    path: str, key: str, params: dict | None = None, max_pages: int = 10,
) -> list:
    """Paginate through offset-based Langfuse endpoints.

    Falls back gracefully: tries progressively smaller page sizes and shorter
    time windows if ClickHouse returns 422 (memory limit).
    """
    params = dict(params or {})
    params.setdefault("limit", 50)
    all_items: list = []

    for page in range(1, max_pages + 1):
        params["page"] = page
        data = _get(path, params)

        if data is None:
            # 422 or other error — try smaller page size once
            if params["limit"] > 10:
                params["limit"] = 10
                data = _get(path, params)
            if data is None:
                if page == 1:
                    console.print(
                        f"[dim]Query failed for {path} — ClickHouse may need more memory[/]"
                    )
                break

        items = data.get(key, data.get("data", []))
        if not items:
            break
        all_items.extend(items)
        meta = data.get("meta", {})
        total = meta.get("totalItems", meta.get("total", 0))
        if total and len(all_items) >= total:
            break
    return all_items


# ── Data fetchers ─────────────────────────────────────────────────────────────


def fetch_traces(hours: int = 24, limit: int = 100) -> list[dict]:
    """Fetch traces from the last N hours — lightweight, primary data source."""
    from_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    to_time = datetime.now(timezone.utc).isoformat()
    return _paginate(
        "/traces", "data",
        params={
            "fromTimestamp": from_time,
            "toTimestamp": to_time,
            "limit": min(limit, 50),
        },
    )


def fetch_observations(hours: int = 24, obs_type: str = "GENERATION") -> list[dict]:
    """Fetch observations (generations) — heavier query, may fail on low-memory CH."""
    from_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    to_time = datetime.now(timezone.utc).isoformat()
    return _paginate(
        "/observations", "data",
        params={
            "type": obs_type,
            "fromStartTime": from_time,
            "toStartTime": to_time,
            "limit": 50,
        },
    )


def fetch_scores(hours: int = 24) -> list[dict]:
    """Fetch scores from the last N hours."""
    from_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    to_time = datetime.now(timezone.utc).isoformat()
    return _paginate(
        "/scores", "data",
        params={
            "fromTimestamp": from_time,
            "toTimestamp": to_time,
            "limit": 50,
        },
    )


# ── Trace-based metrics extraction ──────────────────────────────────────────


def _extract_generation_data(traces: list[dict]) -> list[dict]:
    """Extract generation-like data from trace objects.

    Traces have: latency (ms), totalUsage.total/input/output,
    calculatedTotalCost, metadata.model, scores{}.
    observations[] contains string IDs (not full objects) in v3 API.
    """
    results = []
    for t in traces:
        # Skip traces with no useful data
        latency = t.get("latency")
        usage = t.get("totalUsage") or t.get("usage") or {}

        # Get model from metadata (n8n traces) or trace name (litellm traces)
        metadata = t.get("metadata") or {}
        model = metadata.get("model") or "unknown"
        if model == "unknown":
            name = t.get("name") or ""
            if name.startswith("litellm-"):
                model = "litellm"  # model detail only in observations
            elif name:
                model = name

        results.append({
            "model": model,
            "latency": latency,
            "input_tokens": usage.get("input", usage.get("promptTokens", 0)) or 0,
            "output_tokens": usage.get("output", usage.get("completionTokens", 0)) or 0,
            "total_tokens": usage.get("total", usage.get("totalTokens", 0)) or 0,
            "cost": t.get("calculatedTotalCost") or t.get("totalCost") or 0,
            "scores": t.get("scores") or {},
            "trace": t,
        })
    return results


# ── Latency analysis ─────────────────────────────────────────────────────────


def cmd_latency(args: argparse.Namespace) -> None:
    """Show latency percentiles per model."""
    # Try observations first, fall back to traces
    observations = fetch_observations(hours=args.hours)
    if observations:
        by_model = _latency_from_observations(observations)
    else:
        console.print("[dim]Observations unavailable, using traces[/]")
        traces = fetch_traces(hours=args.hours)
        by_model = _latency_from_traces(traces)

    if not by_model:
        console.print("[dim]No latency data available[/]")
        return

    table = Table(title=f"Latency by Model (last {args.hours}h)", show_lines=True)
    table.add_column("Model", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("p50 (ms)", justify="right")
    table.add_column("p95 (ms)", justify="right")
    table.add_column("p99 (ms)", justify="right")
    table.add_column("Max (ms)", justify="right")

    for model in sorted(by_model):
        vals = sorted(by_model[model])
        n = len(vals)
        p50 = vals[int(n * 0.5)] if n else 0
        p95 = vals[int(n * 0.95)] if n else 0
        p99 = vals[int(n * 0.99)] if n else 0
        mx = vals[-1] if n else 0

        latency_style = "green" if p95 < 5000 else "yellow" if p95 < 10000 else "red"
        table.add_row(
            model, str(n),
            f"[{latency_style}]{p50:.0f}[/]",
            f"[{latency_style}]{p95:.0f}[/]",
            f"[{latency_style}]{p99:.0f}[/]",
            f"{mx:.0f}",
        )

    console.print(table)


def _latency_from_observations(observations: list[dict]) -> dict[str, list[float]]:
    by_model: dict[str, list[float]] = defaultdict(list)
    for obs in observations:
        model = obs.get("model") or obs.get("modelId") or "unknown"
        start = obs.get("startTime")
        end = obs.get("endTime")
        if not start or not end:
            latency = obs.get("latency")
            if latency is not None:
                by_model[model].append(latency)
            continue
        try:
            t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
            ms = (t1 - t0).total_seconds() * 1000
            if ms > 0:
                by_model[model].append(ms)
        except (ValueError, TypeError):
            pass
    return by_model


def _latency_from_traces(traces: list[dict]) -> dict[str, list[float]]:
    by_model: dict[str, list[float]] = defaultdict(list)
    for item in _extract_generation_data(traces):
        latency = item["latency"]
        if latency and latency > 0:
            by_model[item["model"]].append(latency)
    return by_model


# ── Cost / token tracking ────────────────────────────────────────────────────


def cmd_cost(args: argparse.Namespace) -> None:
    """Show token usage and cost per model."""
    observations = fetch_observations(hours=args.hours)
    if observations:
        stats = _cost_from_observations(observations)
    else:
        console.print("[dim]Observations unavailable, using traces[/]")
        traces = fetch_traces(hours=args.hours)
        stats = _cost_from_traces(traces)

    if not stats:
        console.print("[dim]No usage data found[/]")
        return

    table = Table(title=f"Token Usage by Model (last {args.hours}h)", show_lines=True)
    table.add_column("Model", style="bold")
    table.add_column("Calls", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Total Tokens", justify="right")
    table.add_column("Cost ($)", justify="right")

    total_calls = total_input = total_output = total_tokens = 0
    total_cost = 0.0

    for model in sorted(stats):
        s = stats[model]
        total_calls += s["count"]
        total_input += s["input_tokens"]
        total_output += s["output_tokens"]
        total_tokens += s["total_tokens"]
        total_cost += s["cost"]

        cost_str = f"{s['cost']:.4f}" if s["cost"] > 0 else "[dim]—[/]"
        table.add_row(
            model, str(s["count"]),
            f"{s['input_tokens']:,}", f"{s['output_tokens']:,}",
            f"{s['total_tokens']:,}", cost_str,
        )

    table.add_section()
    cost_total_str = f"{total_cost:.4f}" if total_cost > 0 else "[dim]—[/]"
    table.add_row(
        "[bold]TOTAL[/]", str(total_calls),
        f"{total_input:,}", f"{total_output:,}",
        f"{total_tokens:,}", cost_total_str,
    )
    console.print(table)


def _cost_from_observations(observations: list[dict]) -> dict[str, dict]:
    stats: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost": 0.0}
    )
    for obs in observations:
        model = obs.get("model") or obs.get("modelId") or "unknown"
        usage = obs.get("usage") or obs.get("usageDetails") or {}
        s = stats[model]
        s["count"] += 1
        s["input_tokens"] += usage.get("input", usage.get("promptTokens", 0)) or 0
        s["output_tokens"] += usage.get("output", usage.get("completionTokens", 0)) or 0
        s["total_tokens"] += usage.get("total", usage.get("totalTokens", 0)) or 0
        s["cost"] += obs.get("calculatedTotalCost") or obs.get("totalCost") or 0
    return stats


def _cost_from_traces(traces: list[dict]) -> dict[str, dict]:
    stats: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost": 0.0}
    )
    for item in _extract_generation_data(traces):
        s = stats[item["model"]]
        s["count"] += 1
        s["input_tokens"] += item["input_tokens"]
        s["output_tokens"] += item["output_tokens"]
        s["total_tokens"] += item["total_tokens"]
        s["cost"] += item["cost"] or 0
    return stats


# ── Quality scores ────────────────────────────────────────────────────────────


def cmd_scores(args: argparse.Namespace) -> None:
    """Show quality scores from LLM-as-judge evaluations."""
    scores = fetch_scores(hours=args.hours)
    if not scores:
        console.print("[dim]No scores found[/]")
        return

    by_name: dict[str, list[float]] = defaultdict(list)
    by_source: dict[str, int] = defaultdict(int)
    for s in scores:
        name = s.get("name", "unknown")
        val = s.get("value")
        if val is not None:
            by_name[name].append(float(val))
        source = s.get("source", "unknown")
        by_source[source] += 1

    table = Table(title=f"Quality Scores (last {args.hours}h)", show_lines=True)
    table.add_column("Score Name", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Mean", justify="right")
    table.add_column("Median", justify="right")
    table.add_column("Min", justify="right")
    table.add_column("Max", justify="right")

    for name in sorted(by_name):
        vals = by_name[name]
        n = len(vals)
        mean = statistics.mean(vals) if vals else 0
        median = statistics.median(vals) if vals else 0
        mn = min(vals) if vals else 0
        mx = max(vals) if vals else 0

        score_style = "green" if mean >= 0.7 else "yellow" if mean >= 0.4 else "red"
        table.add_row(
            name, str(n),
            f"[{score_style}]{mean:.2f}[/]", f"{median:.2f}",
            f"{mn:.2f}", f"{mx:.2f}",
        )

    console.print(table)

    if by_source:
        src_table = Table(title="Score Sources", show_lines=True)
        src_table.add_column("Source", style="bold")
        src_table.add_column("Count", justify="right")
        for source in sorted(by_source):
            src_table.add_row(source, str(by_source[source]))
        console.print(src_table)


# ── Recent traces ─────────────────────────────────────────────────────────────


def cmd_traces(args: argparse.Namespace) -> None:
    """Show recent traces."""
    data = _get("/traces", params={"limit": min(args.limit, 50)})
    if not data:
        # Fallback: try with tight time window
        from_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        data = _get("/traces", params={
            "limit": min(args.limit, 20),
            "fromTimestamp": from_time,
        })
    if not data:
        console.print("[dim]No traces available (ClickHouse may need more memory)[/]")
        return

    traces = data.get("data", [])
    if not traces:
        console.print("[dim]No traces found[/]")
        return

    table = Table(title=f"Recent Traces (last {args.limit})", show_lines=True)
    table.add_column("ID", style="bold", max_width=12)
    table.add_column("Name")
    table.add_column("User")
    table.add_column("Latency", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Scores", justify="right")
    table.add_column("Time")

    for t in traces:
        trace_id = (t.get("id") or "?")[:12]
        name = t.get("name") or "[dim]—[/]"
        user = t.get("userId") or "[dim]—[/]"
        latency = t.get("latency")
        latency_str = f"{latency:.0f}ms" if latency else "[dim]—[/]"
        usage = t.get("totalUsage") or t.get("usage") or {}
        tokens = usage.get("total", usage.get("totalTokens", 0)) or 0
        tokens_str = f"{tokens:,}" if tokens else "[dim]—[/]"
        cost = t.get("calculatedTotalCost") or t.get("totalCost") or 0
        cost_str = f"${cost:.4f}" if cost else "[dim]—[/]"
        scores_raw = t.get("scores") or {}
        if isinstance(scores_raw, dict):
            score_parts = [f"{k}={v:.2f}" for k, v in scores_raw.items() if isinstance(v, (int, float))]
            scores_str = ", ".join(score_parts) if score_parts else "[dim]—[/]"
        else:
            scores_str = "[dim]—[/]"
        timestamp = t.get("timestamp") or t.get("createdAt") or ""
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                timestamp = dt.strftime("%m-%d %H:%M")
            except (ValueError, TypeError):
                pass

        table.add_row(trace_id, name, user, latency_str, tokens_str, cost_str, scores_str, timestamp)

    console.print(table)


# ── Summary dashboard ─────────────────────────────────────────────────────────


def cmd_summary(args: argparse.Namespace) -> None:
    """Overview dashboard combining all metrics."""
    hours = args.hours
    console.print(Panel(f"[bold]Langfuse Metrics Dashboard[/] — last {hours}h", style="blue"))

    # Health check
    try:
        health = _get("/health")
        if health:
            status = health.get("status", "unknown")
            version = health.get("version", "?")
            style = "green" if status == "OK" else "red"
            console.print(f"  Health: [{style}]{status}[/]  Version: {version}")
        else:
            console.print("  Health: [red]unreachable[/]")
    except Exception:
        console.print("  Health: [red]unreachable[/]")

    # Try traces first (lighter query)
    traces = fetch_traces(hours=hours)

    # Also try observations (may fail on low-memory ClickHouse)
    observations = fetch_observations(hours=hours)

    # Use observations if available, otherwise extract from traces
    if observations:
        model_counts, latencies, total_input, total_output, total_cost = _summarize_observations(observations)
        total_gen = len(observations)
        source = "observations"
    elif traces:
        gen_data = _extract_generation_data(traces)
        model_counts, latencies, total_input, total_output, total_cost = _summarize_gen_data(gen_data)
        total_gen = len(traces)
        source = "traces"
    else:
        console.print("[dim]No data available — ClickHouse may need more memory[/]")
        console.print("[dim]Try: docker compose restart langfuse-clickhouse[/]")
        return

    table = Table(show_header=False, show_lines=True, title=f"Overview (via {source})")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total generations", str(total_gen))
    table.add_row("Models used", str(len(model_counts)))
    for model, count in sorted(model_counts.items(), key=lambda x: -x[1]):
        table.add_row(f"  {model}", str(count))

    if latencies:
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        p50 = sorted_lat[int(n * 0.5)]
        p95 = sorted_lat[int(n * 0.95)] if n > 1 else sorted_lat[-1]
        table.add_row("Latency p50", f"{p50:.0f} ms")
        table.add_row("Latency p95", f"{p95:.0f} ms")

    table.add_row("Input tokens", f"{total_input:,}")
    table.add_row("Output tokens", f"{total_output:,}")
    table.add_row("Total tokens", f"{total_input + total_output:,}")
    if total_cost > 0:
        table.add_row("Total cost", f"${total_cost:.4f}")

    # Scores summary
    scores = fetch_scores(hours=hours)
    if scores:
        score_vals = [s["value"] for s in scores if s.get("value") is not None]
        if score_vals:
            table.add_row("Quality scores", str(len(score_vals)))
            table.add_row("Avg quality", f"{statistics.mean(score_vals):.2f}")

    console.print(table)


def _summarize_observations(observations: list[dict]) -> tuple:
    model_counts: dict[str, int] = defaultdict(int)
    latencies: list[float] = []
    total_input = total_output = 0
    total_cost = 0.0

    for obs in observations:
        model = obs.get("model") or obs.get("modelId") or "unknown"
        model_counts[model] += 1
        start = obs.get("startTime")
        end = obs.get("endTime")
        if start and end:
            try:
                t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
                ms = (t1 - t0).total_seconds() * 1000
                if ms > 0:
                    latencies.append(ms)
            except (ValueError, TypeError):
                pass
        elif obs.get("latency"):
            latencies.append(obs["latency"])
        usage = obs.get("usage") or obs.get("usageDetails") or {}
        total_input += usage.get("input", usage.get("promptTokens", 0)) or 0
        total_output += usage.get("output", usage.get("completionTokens", 0)) or 0
        total_cost += obs.get("calculatedTotalCost") or obs.get("totalCost") or 0

    return model_counts, latencies, total_input, total_output, total_cost


def _summarize_gen_data(gen_data: list[dict]) -> tuple:
    model_counts: dict[str, int] = defaultdict(int)
    latencies: list[float] = []
    total_input = total_output = 0
    total_cost = 0.0

    for item in gen_data:
        model_counts[item["model"]] += 1
        if item["latency"] and item["latency"] > 0:
            latencies.append(item["latency"])
        total_input += item["input_tokens"]
        total_output += item["output_tokens"]
        total_cost += item["cost"] or 0

    return model_counts, latencies, total_input, total_output, total_cost


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Langfuse metrics dashboard")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window (default: 24h)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("summary", help="Overview dashboard")
    sub.add_parser("latency", help="Latency percentiles per model")
    sub.add_parser("cost", help="Token usage & cost per model")
    sub.add_parser("scores", help="Quality scores from judges")

    p_traces = sub.add_parser("traces", help="Recent traces")
    p_traces.add_argument("--limit", type=int, default=20, help="Number of traces")

    args = parser.parse_args()

    cmds = {
        "summary": cmd_summary,
        "latency": cmd_latency,
        "cost": cmd_cost,
        "scores": cmd_scores,
        "traces": cmd_traces,
    }

    handler = cmds.get(args.command)
    if handler:
        handler(args)
    else:
        args.command = "summary"
        cmd_summary(args)


if __name__ == "__main__":
    main()

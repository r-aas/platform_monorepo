#!/usr/bin/env python3
"""Benchmark agents end-to-end via /webhook/chat with LLM-as-judge scoring.

Loads test cases from data/benchmarks/*.jsonl datasets, sends messages through
the full chat pipeline, judges response quality, writes scores to Langfuse,
and logs results to MLflow experiments.

Usage:
  uv run scripts/agent-benchmark.py                    # all agents
  uv run scripts/agent-benchmark.py --agent coder      # single agent
  uv run scripts/agent-benchmark.py --agent coder --task review
  uv run scripts/agent-benchmark.py --agent coder --promote --threshold 0.8
  uv run scripts/agent-benchmark.py --seed-datasets    # upload JSONL to MLflow
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

import requests

BASE = os.getenv("N8N_BASE_URL", "http://localhost:5678/webhook")
CHAT_URL = f"{BASE}/chat"
EVAL_URL = f"{BASE}/eval"
PROMPTS_URL = f"{BASE}/prompts"
DATASETS_URL = f"{BASE}/datasets"
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://localhost:3100")
LANGFUSE_PK = os.getenv("LANGFUSE_PUBLIC_KEY", "lf-pk-local")
LANGFUSE_SK = os.getenv("LANGFUSE_SECRET_KEY", "lf-sk-local")
MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5050") + "/api/2.0/mlflow"

API_KEY = os.getenv("WEBHOOK_API_KEY", "")
HEADERS: dict[str, str] = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY

CHAT_TIMEOUT = 180
BENCHMARKS_DIR = Path(__file__).parent.parent / "data" / "benchmarks"

# Direct LLM judge config (bypasses n8n eval workflow for speed + reliability)
LITELLM_URL = os.getenv("LITELLM_URL", os.getenv("AGENT_GATEWAY_URL", "http://gateway.platform.127.0.0.1.nip.io"))
LITELLM_KEY = os.getenv("LITELLM_API_KEY", "not-needed")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "glm-4.7-flash")


# ── JSONL Dataset Loader ──────────────────────────────────────────────────────


def load_benchmarks(
    agent: str | None = None,
    task: str | None = None,
    tags: list[str] | None = None,
) -> list[dict]:
    """Load benchmark cases from data/benchmarks/*.jsonl files.

    Returns list of dicts with: input, expected, criteria, domain, task, tags, label, _file
    """
    pattern = str(BENCHMARKS_DIR / "*.jsonl")
    files = sorted(glob.glob(pattern))
    cases = []

    for fpath in files:
        fname = Path(fpath).stem  # e.g. "coder.review"
        parts = fname.split(".", 1)
        file_agent = parts[0]
        file_task = parts[1] if len(parts) > 1 else "general"

        if agent and file_agent != agent:
            continue
        if task and file_task != task:
            continue

        with open(fpath) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Filter by tags
                row_tags = row.get("tags", [])
                if tags:
                    if not any(t in row_tags for t in tags):
                        continue

                cases.append(
                    {
                        "input": row.get("input", ""),
                        "expected": row.get("expected", ""),
                        "criteria": row.get("criteria", ""),
                        "domain": row.get("domain", file_agent),
                        "task": row.get("task", file_task),
                        "tags": row_tags,
                        "label": f"{file_agent}.{file_task}.{i}",
                        "_file": fname,
                    }
                )

    return cases


def cases_to_suites(cases: list[dict]) -> list[dict]:
    """Group flat case list into agent suites for the runner."""
    by_agent: dict[str, list[dict]] = {}
    for c in cases:
        agent = c["domain"]
        if agent not in by_agent:
            by_agent[agent] = []
        tc = {
            "label": c["label"],
            "message": c["input"],
            "judge_criteria": c["criteria"],
        }
        if c["task"] != "general":
            tc["task"] = c["task"]
        # Use expected as a contains check if it's short enough
        expected = c.get("expected", "")
        if expected and len(expected) < 30 and "\n" not in expected:
            tc["expect_contains"] = expected
        by_agent[agent].append(tc)

    return [{"agent": a, "test_cases": tcs} for a, tcs in sorted(by_agent.items())]


# ── Validators ────────────────────────────────────────────────────────────────


def validate(response: str, tc: dict) -> tuple[bool, str]:
    """Run quality checks on a response. Returns (passed, reason)."""
    r = response.strip().lower()

    if "expect_contains" in tc:
        keyword = tc["expect_contains"].lower()
        if keyword in r:
            return True, f"contains '{keyword}'"
        return False, f"missing '{keyword}' in: {r[:80]}"

    if "expect_min_length" in tc:
        if len(response.strip()) >= tc["expect_min_length"]:
            return True, f"{len(response.strip())} chars"
        return False, f"too short: {len(response.strip())} < {tc['expect_min_length']}"

    if "expect_max_words" in tc:
        words = len(response.strip().split())
        if words <= tc["expect_max_words"]:
            return True, f"{words} words"
        return False, f"{words} words > max {tc['expect_max_words']}"

    return True, "no validator"


# ── Chat Runner ───────────────────────────────────────────────────────────────


def chat(agent: str, message: str, task: str = "") -> dict:
    """Send a message to an agent via /webhook/chat. Returns full response."""
    payload = {"agent_name": agent, "message": message}
    if task:
        payload["task"] = task
    try:
        resp = requests.post(CHAT_URL, json=payload, headers=HEADERS, timeout=CHAT_TIMEOUT)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}", "response": "", "trace_id": ""}
        try:
            return resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            return {"error": f"Invalid JSON: {resp.text[:200]}", "response": "", "trace_id": ""}
    except requests.RequestException as e:
        return {"error": str(e), "response": "", "trace_id": ""}


# ── Judge ─────────────────────────────────────────────────────────────────────


def _parse_judge_json(text: str) -> dict:
    """Extract score/reason from judge LLM output (handles markdown fences)."""
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text)
    return {
        "score": float(parsed.get("score", 0.0)),
        "reason": parsed.get("reason", "no reason"),
    }


def judge_response(criteria: str, user_input: str, response: str) -> dict:
    """Judge an agent response via direct LiteLLM call (fast, reliable).

    Uses a smaller model (qwen2.5:7b by default) for judge calls to avoid
    timeouts that plague the larger models through the n8n eval workflow.
    """
    system_prompt = (
        "You are an expert evaluator. Score the following AI response on a scale of 0.0 to 1.0.\n\n"
        f"Criteria: {criteria}\n\n"
        f"User Input:\n{user_input}\n\n"
        f"AI Response:\n{response}\n\n"
        "Scoring guide:\n"
        "- 0.0-0.3: Response is irrelevant or completely misses the point\n"
        "- 0.3-0.5: Response partially addresses the topic but misses most criteria\n"
        "- 0.5-0.7: Response addresses the main topic and covers some criteria\n"
        "- 0.7-0.9: Response is good, covers most criteria with relevant detail\n"
        "- 0.9-1.0: Response is excellent, thoroughly covers all criteria\n\n"
        "Be fair — reward substantive, relevant answers even if they don't hit every bullet point.\n"
        'Respond with ONLY valid JSON, no other text:\n{"score": 0.00, "reason": "one sentence explanation"}'
    )
    try:
        resp = requests.post(
            f"{LITELLM_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {LITELLM_KEY}", "Content-Type": "application/json"},
            json={
                "model": JUDGE_MODEL,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Evaluate now."},
                ],
            },
            timeout=120,
        )
        if resp.status_code != 200:
            return {"score": 0.0, "reason": f"Judge HTTP {resp.status_code}"}
        data = resp.json()
        judge_text = data["choices"][0]["message"]["content"]
        return _parse_judge_json(judge_text)
    except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
        return {"score": 0.0, "reason": f"Judge parse error: {e}"}
    except requests.RequestException as e:
        return {"score": 0.0, "reason": f"Judge request error: {e}"}


# ── Langfuse Score Writer ────────────────────────────────────────────────────


def write_langfuse_score(
    trace_id: str, name: str, score: float, comment: str
) -> bool:
    """Write a score to a Langfuse trace. Returns True on success."""
    if not trace_id or not LANGFUSE_PK or not LANGFUSE_SK:
        return False

    try:
        resp = requests.post(
            f"{LANGFUSE_HOST}/api/public/scores",
            auth=(LANGFUSE_PK, LANGFUSE_SK),
            json={
                "traceId": trace_id,
                "name": name,
                "value": score,
                "comment": comment,
                "source": "agent-benchmark",
            },
            timeout=10,
        )
        return resp.status_code in (200, 201)
    except requests.RequestException:
        return False


# ── MLflow Experiment Logger ──────────────────────────────────────────────────


def log_benchmark_to_mlflow(agent: str, all_results: list[dict]) -> str | None:
    """Log benchmark run to MLflow experiment. Returns run_id or None."""
    try:
        exp_name = f"{agent}-benchmark"
        # Get or create experiment
        try:
            resp = requests.get(
                f"{MLFLOW_URL}/experiments/get-by-name",
                params={"experiment_name": exp_name},
                timeout=10,
            )
            exp_id = resp.json()["experiment"]["experiment_id"]
        except Exception:
            resp = requests.post(
                f"{MLFLOW_URL}/experiments/create",
                json={"name": exp_name},
                timeout=10,
            )
            exp_id = resp.json()["experiment_id"]

        # Create run
        ts = int(time.time() * 1000)
        resp = requests.post(
            f"{MLFLOW_URL}/runs/create",
            json={
                "experiment_id": exp_id,
                "start_time": ts,
                "run_name": f"benchmark-{agent}-{int(time.time())}",
            },
            timeout=10,
        )
        run_id = resp.json()["run"]["info"]["run_id"]

        # Compute metrics
        total = len(all_results)
        passed = sum(1 for r in all_results if r["status"] == "PASS")
        scored = [r for r in all_results if r["score"] > 0]
        avg_score = sum(r["score"] for r in scored) / len(scored) if scored else 0
        latencies = sorted(r["latency_ms"] for r in all_results)
        p50 = latencies[len(latencies) // 2] if latencies else 0
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0

        metrics = [
            {"key": "total_cases", "value": total, "timestamp": ts, "step": 0},
            {"key": "pass_count", "value": passed, "timestamp": ts, "step": 0},
            {"key": "pass_rate", "value": passed / total if total else 0, "timestamp": ts, "step": 0},
            {"key": "avg_score", "value": avg_score, "timestamp": ts, "step": 0},
            {"key": "latency_p50_ms", "value": p50, "timestamp": ts, "step": 0},
            {"key": "latency_p95_ms", "value": p95, "timestamp": ts, "step": 0},
        ]

        requests.post(
            f"{MLFLOW_URL}/runs/log-batch",
            json={
                "run_id": run_id,
                "params": [
                    {"key": "agent", "value": agent},
                    {"key": "source", "value": "agent-benchmark"},
                ],
                "metrics": metrics,
                "tags": [{"key": "agent", "value": agent}],
            },
            timeout=10,
        )
        requests.post(
            f"{MLFLOW_URL}/runs/update",
            json={"run_id": run_id, "status": "FINISHED", "end_time": int(time.time() * 1000)},
            timeout=10,
        )
        return run_id
    except Exception as e:
        print(f"  (MLflow log failed: {e})")
        return None


# ── Dataset Seeder ────────────────────────────────────────────────────────────


def seed_datasets() -> None:
    """Upload data/benchmarks/*.jsonl to MLflow via /webhook/datasets."""
    pattern = str(BENCHMARKS_DIR / "*.jsonl")
    files = sorted(glob.glob(pattern))
    if not files:
        print("No JSONL files found in data/benchmarks/")
        return

    print(f"Seeding {len(files)} benchmark datasets to MLflow...")
    for fpath in files:
        fname = Path(fpath).stem
        rows = []
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        if not rows:
            continue

        try:
            resp = requests.post(
                DATASETS_URL,
                json={
                    "action": "upload",
                    "name": fname,
                    "source": "benchmark-seed",
                    "rows": rows,
                },
                headers=HEADERS,
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                print(f"  {fname}: {len(rows)} rows -> {data.get('dataset_id', 'ok')}")
            else:
                print(f"  {fname}: HTTP {resp.status_code}")
        except requests.RequestException as e:
            print(f"  {fname}: {e}")


# ── Runner ────────────────────────────────────────────────────────────────────


def run_suite(suite: dict) -> list[dict]:
    """Run one agent test suite, return per-case results."""
    agent = suite["agent"]
    results = []

    for tc in suite["test_cases"]:
        label = tc["label"]
        message = tc["message"]
        criteria = tc.get("judge_criteria", "")

        task = tc.get("task", "")
        t0 = time.time()
        chat_resp = chat(agent, message, task=task)
        latency_ms = int((time.time() - t0) * 1000)

        output = chat_resp.get("response", "") or chat_resp.get("output", "")
        trace_id = chat_resp.get("trace_id", "")
        error = chat_resp.get("error", "")

        if error:
            results.append(
                {
                    "agent": agent,
                    "label": label,
                    "status": "ERROR",
                    "reason": error,
                    "latency_ms": latency_ms,
                    "score": 0.0,
                    "judge_reason": "",
                    "response": "",
                    "trace_id": trace_id,
                    "langfuse_score": False,
                }
            )
            continue

        passed, reason = validate(output, tc)

        score = 0.0
        judge_reason = ""
        if criteria and output:
            judge = judge_response(criteria, message, output)
            score = judge["score"]
            judge_reason = judge["reason"]

        lf_ok = False
        if trace_id and score > 0:
            lf_ok = write_langfuse_score(trace_id, "quality", score, judge_reason)

        if not passed:
            status = "FAIL"
        elif criteria and score < 0.5:
            status = "FAIL"
            reason = f"judge score {score:.2f} < 0.5"
        else:
            status = "PASS"

        results.append(
            {
                "agent": agent,
                "label": label,
                "status": status,
                "reason": reason,
                "latency_ms": latency_ms,
                "score": score,
                "judge_reason": judge_reason,
                "response": output[:120],
                "trace_id": trace_id,
                "langfuse_score": lf_ok,
            }
        )

    return results


# ── Promotion ─────────────────────────────────────────────────────────────────


def promote_agent(agent: str, pass_rate: float, threshold: float, version: str) -> dict | None:
    """Call the promotion pipeline if pass rate meets threshold."""
    if pass_rate < threshold:
        print(f"\n  Promotion skipped: pass rate {pass_rate:.2f} < threshold {threshold:.2f}")
        return None

    agent_system = f"{agent}.SYSTEM"
    payload = {
        "action": "pipeline",
        "name": agent_system,
        "staging_version": version,
        "threshold": threshold,
        "auto_promote": True,
    }

    try:
        resp = requests.post(PROMPTS_URL, json=payload, headers=HEADERS, timeout=300)
        if resp.status_code == 200:
            data = resp.json()
            decision = data.get("decision", "unknown")
            print(f"\n  Pipeline result: {decision}")
            if data.get("staging_score"):
                print(f"  Staging score: {data['staging_score']:.3f}")
            return data
        else:
            print(f"\n  Pipeline HTTP {resp.status_code}: {resp.text[:200]}")
            return None
    except requests.RequestException as e:
        print(f"\n  Pipeline error: {e}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="GenAI MLOps Agent Benchmark")
    parser.add_argument("--agent", help="Benchmark a specific agent (e.g. coder)")
    parser.add_argument("--task", help="Filter by task (e.g. review)")
    parser.add_argument("--tags", nargs="*", help="Filter by tags")
    parser.add_argument(
        "--threshold", type=float, default=0.7,
        help="Pass rate threshold for exit code (default: 0.7)",
    )
    parser.add_argument(
        "--promote", action="store_true",
        help="Trigger promotion pipeline if benchmark passes",
    )
    parser.add_argument(
        "--version", default="staging",
        help="Version to promote (default: staging alias)",
    )
    parser.add_argument(
        "--seed-datasets", action="store_true",
        help="Upload data/benchmarks/*.jsonl to MLflow datasets",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limit number of test cases per suite (0=all, useful for smoke tests)",
    )
    args = parser.parse_args()

    if args.seed_datasets:
        seed_datasets()
        return

    print("== GenAI MLOps Agent Benchmark ==")
    print(f"Chat: {CHAT_URL}")
    print(f"Eval: {EVAL_URL}")
    print(f"Benchmarks: {BENCHMARKS_DIR}")
    print()

    # Load cases from JSONL
    cases = load_benchmarks(agent=args.agent, task=args.task, tags=args.tags)
    if not cases:
        print(f"No benchmark cases found", file=sys.stderr)
        if args.agent:
            print(f"  Looked for: data/benchmarks/{args.agent}.*.jsonl", file=sys.stderr)
        sys.exit(1)

    suites = cases_to_suites(cases)

    # Apply --limit if specified
    if args.limit > 0:
        for suite in suites:
            suite["test_cases"] = suite["test_cases"][:args.limit]
        cases = [c for s in suites for c in s["test_cases"]]

    print(f"Loaded {len(cases)} cases across {len(suites)} agent(s)")
    print()

    all_results = []
    for suite in suites:
        agent = suite["agent"]
        print(f"-- {agent} ({len(suite['test_cases'])} cases) --")
        results = run_suite(suite)
        all_results.extend(results)

        for r in results:
            icon = "+" if r["status"] == "PASS" else "x"
            lf = "*" if r["langfuse_score"] else " "
            print(
                f"  {icon} {r['label']:30s}  {r['latency_ms']:6d}ms  "
                f"score={r['score']:.2f}  {r['status']:5s}  {lf}  {r['reason']}"
            )
            if r["judge_reason"]:
                print(f"    judge: {r['judge_reason'][:100]}")

        # Log to MLflow per agent
        run_id = log_benchmark_to_mlflow(agent, results)
        if run_id:
            print(f"  MLflow: {agent}-benchmark run {run_id[:8]}")
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("== Summary ==")
    print(
        f"{'Agent':<12s} {'Cases':>5s} {'Pass':>4s} {'Fail':>4s} "
        f"{'Avg ms':>7s} {'Avg Score':>9s}"
    )
    print("-" * 50)

    agents_seen = []
    for suite in suites:
        agent = suite["agent"]
        if agent in agents_seen:
            continue
        agents_seen.append(agent)
        agent_results = [r for r in all_results if r["agent"] == agent]
        passed = sum(1 for r in agent_results if r["status"] == "PASS")
        failed = sum(1 for r in agent_results if r["status"] != "PASS")
        avg_ms = (
            sum(r["latency_ms"] for r in agent_results) / len(agent_results)
            if agent_results
            else 0
        )
        scored = [r for r in agent_results if r["score"] > 0]
        avg_score = sum(r["score"] for r in scored) / len(scored) if scored else 0
        print(
            f"{agent:<12s} {len(agent_results):>5d} {passed:>4d} {failed:>4d} "
            f"{avg_ms:>7.0f} {avg_score:>9.2f}"
        )

    total = len(all_results)
    total_pass = sum(1 for r in all_results if r["status"] == "PASS")
    total_fail = total - total_pass
    pass_rate = total_pass / total if total else 0
    avg_ms_all = sum(r["latency_ms"] for r in all_results) / total if total else 0
    scored_all = [r for r in all_results if r["score"] > 0]
    avg_score_all = (
        sum(r["score"] for r in scored_all) / len(scored_all) if scored_all else 0
    )

    print("-" * 50)
    print(
        f"{'TOTAL':<12s} {total:>5d} {total_pass:>4d} {total_fail:>4d} "
        f"{avg_ms_all:>7.0f} {avg_score_all:>9.2f}"
    )
    print(f"\nPass rate: {pass_rate:.1%} (threshold: {args.threshold:.1%})")

    # ── Promote if requested ──────────────────────────────────────────────────
    if args.promote and args.agent:
        print(f"\n== Promotion Pipeline ==")
        promote_agent(args.agent, pass_rate, args.threshold, args.version)

    if pass_rate < args.threshold:
        print(f"\nBenchmark FAILED: {pass_rate:.1%} < {args.threshold:.1%}")
        if total_fail > 0:
            for r in all_results:
                if r["status"] != "PASS":
                    print(f"  x {r['agent']}/{r['label']}: {r['reason']}")
        sys.exit(1)
    else:
        print(f"\nBenchmark PASSED: {pass_rate:.1%} >= {args.threshold:.1%}")


if __name__ == "__main__":
    main()

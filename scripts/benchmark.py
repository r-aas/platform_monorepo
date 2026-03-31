#!/usr/bin/env python3
"""AgenticOps Benchmark Runner — evaluate agents across models and runtimes.

Supports three execution paths:
1. Prompt benchmarks: test_cases → /webhook/eval (prompt templates like summarizer)
2. Agent benchmarks (gateway): test_cases → agent-gateway /v1/chat/completions (via n8n)
3. Agent benchmarks (direct): test_cases → LiteLLM /v1/chat/completions (LLM-only, no orchestrator)

Results logged to MLflow as experiment runs for comparison.

Usage:
    uv run python scripts/benchmark.py                              # all suites, default model
    uv run python scripts/benchmark.py --agent mlops                # single agent
    uv run python scripts/benchmark.py --model qwen2.5:7b           # specific model
    uv run python scripts/benchmark.py --matrix                     # full model × agent matrix
    uv run python scripts/benchmark.py --runtime direct             # direct LLM (no gateway/n8n)
    uv run python scripts/benchmark.py --runtime all                # compare gateway vs direct
    uv run python scripts/benchmark.py --type prompt                # prompt suites only
    uv run python scripts/benchmark.py --type agent                 # agent suites only
    uv run python scripts/benchmark.py --log-mlflow                 # log results to MLflow
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Configuration ────────────────────────────────────────────────────────────

EVAL_URL = os.getenv("EVAL_URL", "http://n8n.platform.127.0.0.1.nip.io/webhook/eval")
CHAT_URL = os.getenv("CHAT_URL", "http://gateway.platform.127.0.0.1.nip.io/v1/chat/completions")
LITELLM_URL = os.getenv("LITELLM_URL", "http://litellm.platform.127.0.0.1.nip.io/v1/chat/completions")
LITELLM_KEY = os.getenv("LITELLM_API_KEY", os.getenv("LITELLM_KEY", "sk-litellm-mewtwo-local"))
MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.platform.127.0.0.1.nip.io")
BENCHMARK_DIR = Path(__file__).parent.parent / "data" / "benchmarks"

MODELS = ["glm-4.7-flash", "qwen3:32b", "qwen2.5:14b", "gemma3:12b"]

# Map agent names to their MLflow system prompt names
AGENT_PROMPT_MAP = {
    "mlops": "mlops.SYSTEM",
    "developer": "developer.SYSTEM",
    "platform-admin": "platform-admin.SYSTEM",
    "coder": "coder.SYSTEM",
    "writer": "writer.SYSTEM",
    "reasoner": "reasoner.SYSTEM",
    "analyst": "analyst.SYSTEM",
    "devops": "devops.SYSTEM",
    "mcp": "mcp.SYSTEM",
}


# ── Inline Prompt Suites ────────────────────────────────────────────────────

PROMPT_SUITES = [
    {
        "prompt_name": "summarizer",
        "temperature": 0,
        "test_cases": [
            {
                "label": "summ-short",
                "variables": {
                    "num_sentences": "2",
                    "text": (
                        "Kubernetes is an open-source container orchestration platform "
                        "that automates the deployment, scaling, and management of "
                        "containerized applications. It was originally designed by Google "
                        "and is now maintained by the Cloud Native Computing Foundation."
                    ),
                },
                "validators": [{"type": "expect_max_sentences", "value": 3}],
            },
            {
                "label": "summ-medium",
                "variables": {
                    "num_sentences": "3",
                    "text": (
                        "Machine learning operations, or MLOps, is a set of practices "
                        "that aims to deploy and maintain machine learning models in "
                        "production reliably and efficiently. It combines machine learning, "
                        "DevOps, and data engineering. Key components include experiment "
                        "tracking, model versioning, automated testing, continuous "
                        "integration and delivery for ML pipelines, and monitoring of "
                        "model performance in production environments."
                    ),
                },
                "validators": [{"type": "expect_max_sentences", "value": 4}],
            },
            {
                "label": "summ-technical",
                "variables": {
                    "num_sentences": "2",
                    "text": (
                        "Retrieval-Augmented Generation combines information retrieval "
                        "with text generation. A query is first used to retrieve relevant "
                        "documents from a knowledge base using semantic similarity search. "
                        "These documents are then provided as context to a large language "
                        "model, which generates a response grounded in the retrieved "
                        "information, reducing hallucinations."
                    ),
                },
                "validators": [{"type": "expect_max_sentences", "value": 3}],
            },
        ],
    },
    {
        "prompt_name": "classifier",
        "temperature": 0,
        "test_cases": [
            {
                "label": "class-billing",
                "variables": {
                    "categories": "billing, technical, account, feature-request",
                    "ticket": "I was charged twice for my subscription. Please refund.",
                },
                "validators": [{"type": "expect_contains", "value": "billing"}],
            },
            {
                "label": "class-technical",
                "variables": {
                    "categories": "billing, technical, account, feature-request",
                    "ticket": "The API returns a 502 error on large file uploads.",
                },
                "validators": [{"type": "expect_contains", "value": "technical"}],
            },
            {
                "label": "class-feature",
                "variables": {
                    "categories": "billing, technical, account, feature-request",
                    "ticket": "It would be great to add dark mode to the dashboard.",
                },
                "validators": [{"type": "expect_contains", "value": "feature"}],
            },
        ],
    },
    {
        "prompt_name": "extractor",
        "temperature": 0,
        "test_cases": [
            {
                "label": "ext-person",
                "variables": {
                    "fields": "name, email, company, role",
                    "text": "Hi, I'm Sarah Chen from Acme Corp. I'm VP of Engineering. Reach me at sarah.chen@acme.com.",
                },
                "validators": [{"type": "expect_json_keys", "value": ["name", "email", "company", "role"]}],
            },
            {
                "label": "ext-event",
                "variables": {
                    "fields": "event_name, date, location, organizer",
                    "text": "Join us for KubeCon NA on November 12-15, 2025 in Salt Lake City. Organized by the CNCF.",
                },
                "validators": [{"type": "expect_json_keys", "value": ["event_name", "date", "location"]}],
            },
        ],
    },
]


# ── Validators ───────────────────────────────────────────────────────────────


def validate(response: str, validators: list[dict]) -> tuple[bool, str]:
    """Run quality checks on a response. Returns (passed, reason)."""
    if not validators:
        return True, "no validator"

    r = response.strip()
    rl = r.lower()

    for v in validators:
        vtype = v["type"]
        val = v["value"]

        if vtype == "expect_contains":
            if val.lower() not in rl:
                return False, f"missing '{val}'"

        elif vtype == "expect_json_keys":
            try:
                text = r
                if "```" in text:
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                obj = json.loads(text)
                missing = [k for k in val if k not in obj]
                if missing:
                    return False, f"missing keys: {missing}"
            except json.JSONDecodeError:
                return False, f"invalid JSON: {r[:60]}"

        elif vtype == "expect_max_sentences":
            sentences = [s.strip() for s in r.split(".") if s.strip()]
            if len(sentences) > val:
                return False, f"{len(sentences)} sentences > {val}"

        elif vtype == "expect_min_length":
            if len(r) < val:
                return False, f"{len(r)} chars < {val}"

        elif vtype == "expect_max_words":
            words = len(r.split())
            if words > val:
                return False, f"{words} words > {val}"

    return True, "ok"


# ── Loaders ──────────────────────────────────────────────────────────────────


def load_agent_suites(agent_filter: str | None = None) -> list[dict]:
    """Load agent benchmark test cases from data/benchmarks/*.json and *.jsonl."""
    suites = []
    if not BENCHMARK_DIR.exists():
        return suites

    # Load .json files (variables + validators format)
    for f in sorted(BENCHMARK_DIR.glob("*.json")):
        parts = f.stem.split(".", 1)
        if len(parts) != 2:
            continue
        agent, task = parts
        if agent_filter and agent != agent_filter:
            continue

        with open(f) as fh:
            test_cases = json.load(fh)

        suites.append({
            "agent": agent,
            "task": task,
            "format": "json",
            "test_cases": test_cases,
        })

    # Load .jsonl files (input/expected/criteria format)
    for f in sorted(BENCHMARK_DIR.glob("*.jsonl")):
        parts = f.stem.split(".", 1)
        if len(parts) != 2:
            continue
        agent, task = parts
        if agent_filter and agent != agent_filter:
            continue

        # Skip if we already loaded a .json version
        if any(s["agent"] == agent and s["task"] == task for s in suites):
            continue

        test_cases = []
        with open(f) as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                tc = json.loads(line)
                tc["label"] = tc.get("label", f"{agent}-{task}-{i}")
                test_cases.append(tc)

        suites.append({
            "agent": agent,
            "task": task,
            "format": "jsonl",
            "test_cases": test_cases,
        })

    return suites


# ── System Prompt Fetcher ────────────────────────────────────────────────────


_prompt_cache: dict[str, str] = {}


def fetch_system_prompt(agent: str, task: str | None = None) -> str:
    """Fetch system prompt from MLflow for direct runtime mode."""
    name = f"{agent}.SYSTEM"
    cache_key = f"{name}+{task or ''}"

    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]

    prompt = ""
    try:
        # Fetch system prompt
        resp = requests.get(
            f"{MLFLOW_URL}/api/2.0/mlflow/registered-models/get",
            params={"name": name},
            timeout=10,
        )
        if resp.status_code == 200:
            model = resp.json().get("registered_model", {})
            tags = {t["key"]: t["value"] for t in model.get("tags", [])}
            prompt = tags.get("mlflow.prompt.text", "")

        # Fetch task prompt if specified
        if task:
            task_name = f"{agent}.{task}"
            resp2 = requests.get(
                f"{MLFLOW_URL}/api/2.0/mlflow/registered-models/get",
                params={"name": task_name},
                timeout=10,
            )
            if resp2.status_code == 200:
                model2 = resp2.json().get("registered_model", {})
                tags2 = {t["key"]: t["value"] for t in model2.get("tags", [])}
                task_prompt = tags2.get("mlflow.prompt.text", "")
                if task_prompt:
                    prompt = f"{prompt}\n\n{task_prompt}"

    except requests.RequestException:
        pass

    _prompt_cache[cache_key] = prompt
    return prompt


# ── Runners ──────────────────────────────────────────────────────────────────


def run_prompt_suite(suite: dict, model: str | None = None) -> list[dict]:
    """Run a prompt eval suite via /webhook/eval."""
    prompt_name = suite["prompt_name"]
    temperature = suite.get("temperature", 0.7)

    payload = {
        "prompt_name": prompt_name,
        "temperature": temperature,
        "test_cases": [
            {"variables": tc["variables"], "label": tc["label"]}
            for tc in suite["test_cases"]
        ],
    }
    if model:
        payload["model"] = model

    try:
        resp = requests.post(EVAL_URL, json=payload, timeout=300)
    except requests.RequestException as e:
        return [
            _error_result(prompt_name, tc["label"], str(e), model, "n8n")
            for tc in suite["test_cases"]
        ]

    if resp.status_code != 200:
        return [
            _error_result(prompt_name, tc["label"], f"HTTP {resp.status_code}", model, "n8n")
            for tc in suite["test_cases"]
        ]

    data = resp.json()
    results = []
    for i, tc in enumerate(suite["test_cases"]):
        r = data["results"][i]
        passed, reason = validate(r["response"], tc.get("validators", []))
        results.append({
            "suite": prompt_name,
            "label": tc["label"],
            "model": model or "default",
            "runtime": "n8n",
            "status": "PASS" if passed else "FAIL",
            "reason": reason,
            "latency_ms": r.get("latency_ms", 0),
            "tokens": r.get("total_tokens", 0),
            "response": r["response"][:200],
        })
    return results


def run_agent_suite_gateway(suite: dict, model: str | None = None) -> list[dict]:
    """Run agent benchmark via agent-gateway (n8n runtime)."""
    return _run_agent_suite(suite, model, CHAT_URL, "gateway", use_agent_prefix=True)


def run_agent_suite_direct(suite: dict, model: str | None = None) -> list[dict]:
    """Run agent benchmark via direct LLM call (no orchestrator)."""
    return _run_agent_suite(suite, model, LITELLM_URL, "direct", use_agent_prefix=False)


def _run_agent_suite(
    suite: dict,
    model: str | None,
    url: str,
    runtime: str,
    use_agent_prefix: bool,
) -> list[dict]:
    """Run agent benchmark against a given endpoint."""
    agent = suite["agent"]
    task = suite["task"]
    suite_name = f"{agent}.{task}"
    fmt = suite.get("format", "json")
    results = []

    # For direct mode, fetch system prompt from MLflow
    system_prompt = ""
    if not use_agent_prefix:
        system_prompt = fetch_system_prompt(agent, task)

    for tc in suite["test_cases"]:
        label = tc.get("label", "unknown")

        # Build user message based on format
        if fmt == "jsonl":
            user_msg = tc.get("input", "")
        else:
            msg_parts = []
            for k, v in tc.get("variables", {}).items():
                msg_parts.append(f"{k}: {v}")
            user_msg = "\n".join(msg_parts)

        # Build payload
        messages = []
        if system_prompt and not use_agent_prefix:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_msg})

        payload: dict = {
            "messages": messages,
            "stream": False,
            "temperature": 0,
        }

        if use_agent_prefix:
            payload["model"] = f"agent:{agent}"
            if model:
                payload["model_override"] = model
        else:
            payload["model"] = model or "qwen2.5:14b"

        headers = {"Content-Type": "application/json"}
        if not use_agent_prefix:
            headers["Authorization"] = f"Bearer {LITELLM_KEY}"

        t0 = time.time()
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            latency_ms = int((time.time() - t0) * 1000)
        except requests.RequestException as e:
            results.append(_error_result(suite_name, label, str(e), model, runtime))
            continue

        if resp.status_code != 200:
            err = f"HTTP {resp.status_code}"
            try:
                err += f": {resp.json().get('error', {}).get('message', '')[:80]}"
            except Exception:
                pass
            results.append(_error_result(suite_name, label, err, model, runtime))
            continue

        data = resp.json()
        tokens = 0
        try:
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)
            # agent-gateway may wrap response in JSON
            try:
                inner = json.loads(content)
                response_text = inner.get("response", content) if isinstance(inner, dict) else content
            except (json.JSONDecodeError, TypeError):
                response_text = content
        except (KeyError, IndexError):
            response_text = str(data)

        # Validate based on format
        if fmt == "jsonl":
            # For JSONL: check if response addresses the criteria
            criteria = tc.get("criteria", "")
            expected = tc.get("expected", "")
            # Basic validation: response should be non-trivial
            if len(response_text.strip()) < 50:
                passed, reason = False, f"too short ({len(response_text)} chars)"
            else:
                # Check if key terms from expected output appear
                expected_terms = [w.lower() for w in expected.split() if len(w) > 4]
                matches = sum(1 for t in expected_terms if t in response_text.lower())
                match_ratio = matches / max(len(expected_terms), 1)
                if match_ratio >= 0.2:
                    passed, reason = True, f"term match {match_ratio:.0%}"
                else:
                    passed, reason = False, f"low term match {match_ratio:.0%}"
        else:
            passed, reason = validate(response_text, tc.get("validators", []))

        results.append({
            "suite": suite_name,
            "label": label,
            "model": model or "default",
            "runtime": runtime,
            "status": "PASS" if passed else "FAIL",
            "reason": reason,
            "latency_ms": latency_ms,
            "tokens": tokens,
            "response": response_text[:200],
        })

    return results


def _error_result(suite: str, label: str, reason: str, model: str | None, runtime: str) -> dict:
    return {
        "suite": suite,
        "label": label,
        "model": model or "default",
        "runtime": runtime,
        "status": "ERROR",
        "reason": reason,
        "latency_ms": 0,
        "tokens": 0,
        "response": "",
    }


# ── MLflow Logging ───────────────────────────────────────────────────────────


def log_to_mlflow(all_results: list[dict], run_name: str) -> str | None:
    """Log benchmark results to MLflow as an experiment run."""
    experiment_name = "__benchmarks"

    # Create experiment if needed
    try:
        resp = requests.get(
            f"{MLFLOW_URL}/api/2.0/mlflow/experiments/get-by-name",
            params={"experiment_name": experiment_name},
            timeout=10,
        )
        if resp.status_code == 200:
            experiment_id = resp.json()["experiment"]["experiment_id"]
        else:
            resp = requests.post(
                f"{MLFLOW_URL}/api/2.0/mlflow/experiments/create",
                json={"name": experiment_name},
                timeout=10,
            )
            experiment_id = resp.json()["experiment_id"]
    except requests.RequestException as e:
        print(f"  MLflow experiment error: {e}")
        return None

    # Create run
    try:
        resp = requests.post(
            f"{MLFLOW_URL}/api/2.0/mlflow/runs/create",
            json={
                "experiment_id": experiment_id,
                "run_name": run_name,
                "start_time": int(time.time() * 1000),
            },
            timeout=10,
        )
        run_id = resp.json()["run"]["info"]["run_id"]
    except (requests.RequestException, KeyError) as e:
        print(f"  MLflow run create error: {e}")
        return None

    # Aggregate metrics
    total = len(all_results)
    passed = sum(1 for r in all_results if r["status"] == "PASS")
    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    errors = sum(1 for r in all_results if r["status"] == "ERROR")
    avg_latency = sum(r["latency_ms"] for r in all_results) / max(total, 1)
    total_tokens = sum(r["tokens"] for r in all_results)

    # Per-suite metrics
    suites = sorted(set(r["suite"] for r in all_results))
    ts = int(time.time() * 1000)
    metrics = [
        {"key": "total_cases", "value": float(total), "timestamp": ts, "step": 0},
        {"key": "pass_count", "value": float(passed), "timestamp": ts, "step": 0},
        {"key": "fail_count", "value": float(failed), "timestamp": ts, "step": 0},
        {"key": "error_count", "value": float(errors), "timestamp": ts, "step": 0},
        {"key": "pass_rate", "value": float(passed / max(total, 1)), "timestamp": ts, "step": 0},
        {"key": "avg_latency_ms", "value": float(avg_latency), "timestamp": ts, "step": 0},
        {"key": "total_tokens", "value": float(total_tokens), "timestamp": ts, "step": 0},
    ]

    for suite_name in suites:
        suite_results = [r for r in all_results if r["suite"] == suite_name]
        suite_pass = sum(1 for r in suite_results if r["status"] == "PASS")
        suite_total = len(suite_results)
        suite_avg_ms = sum(r["latency_ms"] for r in suite_results) / max(suite_total, 1)
        safe_name = suite_name.replace(".", "_").replace("-", "_")
        metrics.append({"key": f"{safe_name}_pass_rate", "value": float(suite_pass / max(suite_total, 1)), "timestamp": ts, "step": 0})
        metrics.append({"key": f"{safe_name}_avg_ms", "value": float(suite_avg_ms), "timestamp": ts, "step": 0})

    # Per-model metrics
    models_seen = sorted(set(r["model"] for r in all_results))
    for m in models_seen:
        model_results = [r for r in all_results if r["model"] == m]
        m_pass = sum(1 for r in model_results if r["status"] == "PASS")
        m_total = len(model_results)
        m_avg_ms = sum(r["latency_ms"] for r in model_results) / max(m_total, 1)
        safe_m = m.replace(".", "_").replace(":", "_").replace("-", "_")
        metrics.append({"key": f"model_{safe_m}_pass_rate", "value": float(m_pass / max(m_total, 1)), "timestamp": ts, "step": 0})
        metrics.append({"key": f"model_{safe_m}_avg_ms", "value": float(m_avg_ms), "timestamp": ts, "step": 0})

    # Per-runtime metrics
    runtimes_seen = sorted(set(r["runtime"] for r in all_results))
    for rt in runtimes_seen:
        rt_results = [r for r in all_results if r["runtime"] == rt]
        rt_pass = sum(1 for r in rt_results if r["status"] == "PASS")
        rt_total = len(rt_results)
        rt_avg_ms = sum(r["latency_ms"] for r in rt_results) / max(rt_total, 1)
        metrics.append({"key": f"runtime_{rt}_pass_rate", "value": float(rt_pass / max(rt_total, 1)), "timestamp": ts, "step": 0})
        metrics.append({"key": f"runtime_{rt}_avg_ms", "value": float(rt_avg_ms), "timestamp": ts, "step": 0})

    # Log params + metrics
    params = [
        {"key": "models", "value": ",".join(models_seen)[:500]},
        {"key": "runtimes", "value": ",".join(runtimes_seen)[:500]},
        {"key": "suites", "value": ",".join(suites)[:500]},
        {"key": "timestamp", "value": datetime.now(timezone.utc).isoformat()},
    ]

    try:
        batch_resp = requests.post(
            f"{MLFLOW_URL}/api/2.0/mlflow/runs/log-batch",
            json={"run_id": run_id, "metrics": metrics, "params": params},
            timeout=15,
        )
        if batch_resp.status_code != 200:
            print(f"  MLflow log-batch error {batch_resp.status_code}: {batch_resp.text[:200]}")
        else:
            print(f"  MLflow: logged {len(metrics)} metrics + {len(params)} params")
        # End run
        requests.post(
            f"{MLFLOW_URL}/api/2.0/mlflow/runs/update",
            json={"run_id": run_id, "status": "FINISHED", "end_time": int(time.time() * 1000)},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"  MLflow log error: {e}")

    return run_id


# ── Display ──────────────────────────────────────────────────────────────────


def print_results(all_results: list[dict], suites_run: list[str]) -> None:
    """Print results table and summary."""
    print()
    print("══ Results by Suite ══")
    print(f"{'Suite':<28s} {'Model':<20s} {'Runtime':<8s} {'Cases':>5s} {'Pass':>4s} {'Fail':>4s} {'Err':>4s} {'Avg ms':>7s} {'Tokens':>7s}")
    print("─" * 90)

    for suite_name in suites_run:
        cases = [r for r in all_results if r["suite"] == suite_name]
        if not cases:
            continue
        # Group by model × runtime
        combos = sorted(set((r["model"], r["runtime"]) for r in cases))
        for m, rt in combos:
            mc = [r for r in cases if r["model"] == m and r["runtime"] == rt]
            passed = sum(1 for r in mc if r["status"] == "PASS")
            failed = sum(1 for r in mc if r["status"] == "FAIL")
            errors = sum(1 for r in mc if r["status"] == "ERROR")
            avg_ms = sum(r["latency_ms"] for r in mc) / len(mc) if mc else 0
            tokens = sum(r["tokens"] for r in mc)
            print(f"{suite_name:<28s} {m:<20s} {rt:<8s} {len(mc):>5d} {passed:>4d} {failed:>4d} {errors:>4d} {avg_ms:>7.0f} {tokens:>7d}")

    # Model comparison matrix
    models_seen = sorted(set(r["model"] for r in all_results))
    runtimes_seen = sorted(set(r["runtime"] for r in all_results))

    if len(models_seen) > 1 or len(runtimes_seen) > 1:
        print()
        print("══ Model × Runtime Matrix ══")
        print(f"{'Model':<24s} {'Runtime':<8s} {'Total':>5s} {'Pass%':>6s} {'Avg ms':>7s} {'Tokens':>7s}")
        print("─" * 65)
        for m in models_seen:
            for rt in runtimes_seen:
                mc = [r for r in all_results if r["model"] == m and r["runtime"] == rt]
                if not mc:
                    continue
                passed = sum(1 for r in mc if r["status"] == "PASS")
                avg_ms = sum(r["latency_ms"] for r in mc) / len(mc)
                tokens = sum(r["tokens"] for r in mc)
                pct = f"{100 * passed / len(mc):.0f}%"
                print(f"{m:<24s} {rt:<8s} {len(mc):>5d} {pct:>6s} {avg_ms:>7.0f} {tokens:>7d}")

    total = len(all_results)
    total_pass = sum(1 for r in all_results if r["status"] == "PASS")
    total_fail = sum(1 for r in all_results if r["status"] == "FAIL")
    total_err = sum(1 for r in all_results if r["status"] == "ERROR")
    avg_ms_all = sum(r["latency_ms"] for r in all_results) / total if total else 0

    print()
    print("─" * 65)
    print(f"TOTAL: {total} cases | {total_pass} pass | {total_fail} fail | {total_err} error | avg {avg_ms_all:.0f}ms")

    if total_fail + total_err > 0:
        print(f"⚠ {total_fail + total_err}/{total} test(s) did not pass")
    else:
        print(f"✓ All {total} tests passed")


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AgenticOps Benchmark Runner")
    parser.add_argument("--type", choices=["prompt", "agent", "all"], default="all",
                        help="Which suites to run (default: all)")
    parser.add_argument("--agent", help="Run only this agent's suites")
    parser.add_argument("--model", help="Override model for all suites")
    parser.add_argument("--runtime", choices=["gateway", "direct", "all"], default="gateway",
                        help="Execution runtime (default: gateway)")
    parser.add_argument("--matrix", action="store_true",
                        help="Run all models × all suites")
    parser.add_argument("--log-mlflow", action="store_true",
                        help="Log results to MLflow __benchmarks experiment")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show per-case results")
    args = parser.parse_args()

    models_to_run = [args.model] if args.model else (MODELS if args.matrix else [None])
    runtimes_to_run = ["gateway", "direct"] if args.runtime == "all" else [args.runtime]

    print("══ AgenticOps Benchmark ══")
    print(f"  Eval:     {EVAL_URL}")
    print(f"  Gateway:  {CHAT_URL}")
    print(f"  Direct:   {LITELLM_URL}")
    print(f"  MLflow:   {MLFLOW_URL}")
    print(f"  Models:   {', '.join(m or 'default' for m in models_to_run)}")
    print(f"  Runtimes: {', '.join(runtimes_to_run)}")
    print()

    all_results = []
    suites_run = []

    for model in models_to_run:
        model_label = model or "default"

        # Prompt suites (always via n8n eval endpoint)
        if args.type in ("prompt", "all") and not args.agent:
            for suite in PROMPT_SUITES:
                name = suite["prompt_name"]
                if name not in suites_run:
                    suites_run.append(name)
                print(f"── {name} ({model_label}) ──")
                results = run_prompt_suite(suite, model)
                all_results.extend(results)
                if args.verbose:
                    for r in results:
                        icon = "✓" if r["status"] == "PASS" else "✗" if r["status"] == "FAIL" else "!"
                        print(f"  {icon} {r['label']:25s} {r['latency_ms']:5d}ms {r['status']:5s} {r['reason']}")
                else:
                    passed = sum(1 for r in results if r["status"] == "PASS")
                    print(f"  {passed}/{len(results)} passed")
                print()

        # Agent suites
        if args.type in ("agent", "all"):
            agent_suites = load_agent_suites(args.agent)
            for suite in agent_suites:
                name = f"{suite['agent']}.{suite['task']}"
                if name not in suites_run:
                    suites_run.append(name)

                for runtime in runtimes_to_run:
                    print(f"── {name} ({model_label}, {runtime}) ──")
                    if runtime == "gateway":
                        results = run_agent_suite_gateway(suite, model)
                    else:
                        results = run_agent_suite_direct(suite, model)

                    all_results.extend(results)
                    if args.verbose:
                        for r in results:
                            icon = "✓" if r["status"] == "PASS" else "✗" if r["status"] == "FAIL" else "!"
                            print(f"  {icon} {r['label']:25s} {r['latency_ms']:5d}ms {r['status']:5s} {r['reason']}")
                            if args.verbose and r["response"]:
                                print(f"    → {r['response'][:100]}")
                    else:
                        passed = sum(1 for r in results if r["status"] == "PASS")
                        print(f"  {passed}/{len(results)} passed")
                    print()

    print_results(all_results, suites_run)

    # Log to MLflow
    if args.log_mlflow and all_results:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_name = f"bench-{ts}"
        print(f"\nLogging to MLflow as '{run_name}'...")
        run_id = log_to_mlflow(all_results, run_name)
        if run_id:
            print(f"  MLflow run: {run_id}")
            print(f"  View: {MLFLOW_URL}/#/experiments/__benchmarks")

    sys.exit(1 if any(r["status"] not in ("PASS",) for r in all_results) else 0)


if __name__ == "__main__":
    main()

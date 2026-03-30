#!/usr/bin/env python3
"""GenAI MLOps Full Lifecycle Demo.

Demonstrates the complete MLOps workflow:
  1. Prompt Registry     — seed prompts, list registry
  2. Evaluate with Judges — classifier eval with LLM judges
  3. Create New Version  — classifier v2 with few-shot examples
  4. A/B Evaluation      — v1 vs v2 comparison
  5. Agent + Session     — MLOps agent with conversation memory
  6. Feedback Annotation — rate agent traces
  7. Drift Detection     — baseline + drift check
  8. Promote to Prod     — promote best version

Usage: uv run python scripts/demo-mlops.py
"""

from __future__ import annotations

import os
import sys
import time

import httpx

BASE = os.environ.get("N8N_BASE_URL", "http://localhost:5678/webhook")
CLIENT = httpx.Client(timeout=60)


def post(endpoint: str, data: dict) -> dict:
    """POST JSON to n8n webhook."""
    r = CLIENT.post(f"{BASE}/{endpoint}", json=data)
    r.raise_for_status()
    return r.json()


def step(num: int, title: str) -> None:
    """Print step header."""
    print(f"\n{'─' * 60}")
    print(f"  Step {num}: {title}")
    print(f"{'─' * 60}")


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠ {msg}")


def fail(msg: str) -> None:
    print(f"  ✗ {msg}")


# ── Step 1: Prompt Registry ─────────────────────────────────────────────────


def step1_prompt_registry() -> bool:
    step(1, "Prompt Registry")

    # List existing prompts
    resp = post("prompts", {"action": "list"})
    prompts = resp.get("prompts", [])
    ok(f"Registry has {len(prompts)} prompt(s)")
    for p in prompts:
        print(f"       {p.get('name', '?'):<20s} v{p.get('version', '?')}")

    # Get classifier prompt
    resp = post("prompts", {"action": "get", "name": "classifier"})
    if resp.get("error"):
        fail("Classifier prompt not found — run 'task seed-prompts' first")
        return False
    ok(f"classifier v{resp.get('version')} loaded")
    return True


# ── Step 2: Evaluate with Judges ────────────────────────────────────────────


def step2_evaluate() -> dict | None:
    step(2, "Evaluate with Judges")

    payload = {
        "prompt_name": "classifier",
        "temperature": 0,
        "test_cases": [
            {
                "label": "billing-ticket",
                "variables": {
                    "categories": "billing, technical, account, feature-request",
                    "ticket": "I was charged twice for my subscription this month.",
                },
            },
            {
                "label": "technical-ticket",
                "variables": {
                    "categories": "billing, technical, account, feature-request",
                    "ticket": "The API returns a 502 error when uploading files > 50MB.",
                },
            },
        ],
        "judges": [
            {
                "name": "relevance",
                "criteria": "Does the classification match the ticket content?",
            }
        ],
    }

    resp = post("eval", payload)
    results = resp.get("results", [])

    for r in results:
        status = "✓" if r.get("response") else "✗"
        scores = r.get("judge_scores", {})
        score_str = ", ".join(f"{k}={v}" for k, v in scores.items()) if scores else "no scores"
        print(
            f"  {status} {r.get('label', '?'):<20s} → {r.get('response', '?')[:30]:<30s} [{score_str}]"
        )

    ok(f"Eval complete: {len(results)} cases, run_id={resp.get('run_id', '?')}")
    return resp


# ── Step 3: Create New Version ──────────────────────────────────────────────


def step3_new_version() -> bool:
    step(3, "Create New Version")

    new_template = (
        "Classify this support ticket into exactly one category.\n"
        "Categories: {{categories}}\n\n"
        "Examples:\n"
        '- "I was charged twice" → billing\n'
        '- "API returns 500 error" → technical\n'
        '- "Add dark mode" → feature-request\n'
        '- "Reset my password" → account\n\n'
        "Ticket: {{ticket}}\n\n"
        "Respond with ONLY the category name, nothing else."
    )

    resp = post(
        "prompts",
        {
            "action": "upsert",
            "name": "classifier",
            "alias": "staging",
            "template": new_template,
            "commit_message": "v2: Added few-shot examples for better accuracy",
        },
    )
    if resp.get("error"):
        fail(f"Failed to create version: {resp.get('message')}")
        return False

    ok(f"Created classifier v{resp.get('version')} (staging)")
    return True


# ── Step 4: A/B Evaluation ──────────────────────────────────────────────────


def step4_ab_eval() -> None:
    step(4, "A/B Evaluation")

    test_cases = [
        {
            "label": "billing",
            "variables": {
                "categories": "billing, technical, account, feature-request",
                "ticket": "Refund my duplicate charge from last month.",
            },
        },
        {
            "label": "technical",
            "variables": {
                "categories": "billing, technical, account, feature-request",
                "ticket": "Getting timeout errors on the dashboard page.",
            },
        },
        {
            "label": "feature-req",
            "variables": {
                "categories": "billing, technical, account, feature-request",
                "ticket": "It would be great if you could add CSV export to reports.",
            },
        },
    ]

    # Eval production (v1)
    print("  Running v1 (production)...")
    resp_v1 = post(
        "eval",
        {
            "prompt_name": "classifier",
            "prompt_version": "production",
            "temperature": 0,
            "test_cases": test_cases,
        },
    )

    # Eval staging (v2)
    print("  Running v2 (staging)...")
    resp_v2 = post(
        "eval",
        {
            "prompt_name": "classifier",
            "prompt_version": "staging",
            "temperature": 0,
            "test_cases": test_cases,
        },
    )

    # Compare
    print(f"\n  {'Label':<15s} {'v1 (prod)':<25s} {'v2 (staging)':<25s}")
    print(f"  {'─' * 65}")
    r1 = resp_v1.get("results", [])
    r2 = resp_v2.get("results", [])
    for i in range(min(len(r1), len(r2))):
        label = r1[i].get("label", "?")
        out1 = r1[i].get("response", "?")[:22]
        out2 = r2[i].get("response", "?")[:22]
        ms1 = r1[i].get("latency_ms", 0)
        ms2 = r2[i].get("latency_ms", 0)
        print(f"  {label:<15s} {out1:<18s} {ms1:>4d}ms  {out2:<18s} {ms2:>4d}ms")

    ok("A/B comparison complete")


# ── Step 5: Agent + Session ─────────────────────────────────────────────────


def step5_agent_session() -> str | None:
    step(5, "Agent + Session")

    # Create session
    session = post("sessions", {"action": "create", "metadata": {"demo": True}})
    session_id = session.get("session_id", "")
    ok(f"Created session: {session_id}")

    # First message — ask agent to list prompts
    print("  Sending: 'List all prompts in the registry'")
    try:
        resp = CLIENT.post(
            f"{BASE}/chat",
            json={
                "agent_name": "mlops",
                "message": "List all prompts in the registry",
                "session_id": session_id,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        response_text = data.get("response", "")[:120]
        trace_id = data.get("trace_id", "")
        ok(f"Agent responded (trace: {trace_id})")
        print(f"       {response_text}...")
    except Exception as e:
        warn(f"Agent call failed: {e}")
        # Try the MCP agent as fallback
        try:
            resp = CLIENT.post(
                f"{BASE}/chat",
                json={
                    "agent_name": "mcp",
                    "message": "Hello, what can you help with?",
                    "session_id": session_id,
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            trace_id = data.get("trace_id", "")
            ok(f"MCP agent responded (trace: {trace_id})")
        except Exception as e2:
            warn(f"MCP agent also failed: {e2}")
            trace_id = ""

    # Verify session has messages
    session_data = post("sessions", {"action": "get", "session_id": session_id})
    msg_count = session_data.get("message_count", 0)
    ok(f"Session has {msg_count} message(s)")

    return trace_id


# ── Step 6: Feedback Annotation ─────────────────────────────────────────────


def step6_feedback(trace_id: str) -> None:
    step(6, "Feedback Annotation")

    if not trace_id:
        warn("No trace_id from step 5 — searching recent traces")
        traces = post("traces", {"action": "search", "limit": 5})
        trace_list = traces.get("traces", [])
        if trace_list:
            trace_id = trace_list[0].get("trace_id", "")
            ok(f"Using trace: {trace_id}")
        else:
            warn("No traces found — skipping feedback")
            return

    resp = post(
        "traces",
        {
            "action": "feedback",
            "trace_id": trace_id,
            "rating": 4,
            "comment": "Good response from demo",
        },
    )
    if resp.get("error"):
        warn(f"Feedback failed: {resp.get('message')}")
    else:
        ok(f"Feedback submitted: rating=4 for {trace_id}")


# ── Step 7: Drift Detection ────────────────────────────────────────────────


def step7_drift() -> None:
    step(7, "Drift Detection")

    # Set baseline
    resp = post(
        "traces",
        {
            "action": "baseline_set",
            "prompt_name": "classifier",
        },
    )
    if resp.get("error"):
        warn(f"Baseline set failed: {resp.get('message')}")
    else:
        ok("Baseline set for classifier")

    # Check drift
    resp = post(
        "traces",
        {
            "action": "drift_check",
            "prompt_name": "classifier",
            "window_hours": 24,
        },
    )
    drifted = resp.get("drifted", False)
    if drifted:
        warn("Drift detected!")
        for name, info in resp.get("drift_metrics", {}).items():
            if info.get("drifted"):
                print(f"       {name}: {info.get('current')} vs baseline {info.get('baseline')}")
    else:
        ok("No drift detected")


# ── Step 8: Promote to Production ───────────────────────────────────────────


def step8_promote() -> None:
    step(8, "Promote to Production")

    # Check current versions
    resp = post("prompts", {"action": "versions", "name": "classifier"})
    versions = resp.get("versions", [])
    if len(versions) < 2:
        warn("Need at least 2 versions to promote — skipping")
        return

    print(f"  Versions: {len(versions)}")
    for v in versions[:3]:
        aliases = ", ".join(v.get("aliases", [])) or "none"
        print(f"       v{v.get('version')}: aliases=[{aliases}]")

    # Promote staging to production
    resp = post(
        "prompts",
        {
            "action": "promote",
            "name": "classifier",
            "from_alias": "staging",
            "to_alias": "production",
        },
    )
    if resp.get("error"):
        warn(f"Promote failed: {resp.get('message')}")
    else:
        ok(f"Promoted classifier staging → production (now v{resp.get('version', '?')})")

    # Clear canary if exists
    post("prompts", {"action": "clear_alias", "name": "classifier", "alias": "canary"})
    ok("Cleared canary alias")


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    print("══ GenAI MLOps Full Lifecycle Demo ══")
    print(f"   Base URL: {BASE}")
    print(f"   Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Step 1
    if not step1_prompt_registry():
        sys.exit(1)

    # Step 2
    step2_evaluate()

    # Step 3
    step3_new_version()

    # Step 4
    step4_ab_eval()

    # Step 5
    trace_id = step5_agent_session()

    # Step 6
    step6_feedback(trace_id or "")

    # Step 7
    step7_drift()

    # Step 8
    step8_promote()

    print(f"\n{'═' * 60}")
    print("  ✓ Demo complete — all 8 steps executed")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()

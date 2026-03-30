#!/usr/bin/env python3
"""Signal Collector — OBSERVE layer for autonomous agents.

Polls platform services and emits typed signals to pgvector.
Designed to run as a Taskfile task or n8n Code node.

Signals are the raw events that the task router turns into work items.

Usage:
    uv run scripts/signal-collector.py              # collect all signals
    uv run scripts/signal-collector.py --source k8s # collect from kubernetes only
    uv run scripts/signal-collector.py --dry-run    # print signals, don't write
"""
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "psycopg[binary]"]
# ///
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import httpx
import psycopg


@dataclass
class Signal:
    signal_type: str
    source: str
    priority: str
    payload: dict = field(default_factory=dict)


# ── Kubernetes signals ────────────────────────────────────

def collect_k8s_signals() -> list[Signal]:
    """Check for pod crashes, restarts, not-ready pods."""
    signals = []
    try:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-A", "-o", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return signals
        pods = json.loads(result.stdout).get("items", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return signals

    for pod in pods:
        name = pod["metadata"]["name"]
        ns = pod["metadata"]["namespace"]
        if ns == "kube-system":
            continue

        phase = pod.get("status", {}).get("phase", "Unknown")
        containers = pod.get("status", {}).get("containerStatuses", [])

        for cs in containers:
            restarts = cs.get("restartCount", 0)
            waiting = cs.get("state", {}).get("waiting", {})
            reason = waiting.get("reason", "")

            if reason == "CrashLoopBackOff":
                signals.append(Signal(
                    signal_type="pod_crash",
                    source="kubernetes",
                    priority="P0",
                    payload={"pod": name, "namespace": ns, "reason": reason, "restarts": restarts},
                ))
            elif restarts > 5:
                signals.append(Signal(
                    signal_type="pod_restarts",
                    source="kubernetes",
                    priority="P1",
                    payload={"pod": name, "namespace": ns, "restarts": restarts},
                ))

        if phase == "Failed":
            signals.append(Signal(
                signal_type="pod_failed",
                source="kubernetes",
                priority="P1",
                payload={"pod": name, "namespace": ns, "phase": phase},
            ))

    # Check node conditions
    try:
        result = subprocess.run(
            ["kubectl", "get", "nodes", "-o", "json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            nodes = json.loads(result.stdout).get("items", [])
            for node in nodes:
                name = node["metadata"]["name"]
                for cond in node.get("status", {}).get("conditions", []):
                    if cond["type"] == "DiskPressure" and cond["status"] == "True":
                        signals.append(Signal(
                            signal_type="disk_pressure",
                            source="kubernetes",
                            priority="P0",
                            payload={"node": name},
                        ))
                    if cond["type"] == "MemoryPressure" and cond["status"] == "True":
                        signals.append(Signal(
                            signal_type="memory_pressure",
                            source="kubernetes",
                            priority="P0",
                            payload={"node": name},
                        ))
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass

    return signals


# ── ArgoCD signals ────────────────────────────────────────

def collect_argocd_signals() -> list[Signal]:
    """Check for OutOfSync or Degraded ArgoCD apps."""
    signals = []
    try:
        result = subprocess.run(
            ["kubectl", "get", "applications", "-n", "platform", "-o", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return signals
        apps = json.loads(result.stdout).get("items", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return signals

    for app in apps:
        name = app["metadata"]["name"]
        health = app.get("status", {}).get("health", {}).get("status", "Unknown")
        sync = app.get("status", {}).get("sync", {}).get("status", "Unknown")

        if health in ("Degraded", "Missing"):
            signals.append(Signal(
                signal_type="argocd_degraded",
                source="argocd",
                priority="P0",
                payload={"app": name, "health": health, "sync": sync},
            ))
        elif sync == "OutOfSync":
            signals.append(Signal(
                signal_type="argocd_outofsync",
                source="argocd",
                priority="P1",
                payload={"app": name, "health": health, "sync": sync},
            ))

    return signals


# ── Service health signals ────────────────────────────────

def collect_health_signals() -> list[Signal]:
    """Check key service health endpoints."""
    signals = []
    checks = [
        ("n8n", "http://n8n.platform.127.0.0.1.nip.io/healthz"),
        ("mlflow", "http://mlflow.platform.127.0.0.1.nip.io/health"),
        ("litellm", "http://litellm.platform.127.0.0.1.nip.io/health"),
        ("langfuse", "http://langfuse.platform.127.0.0.1.nip.io/api/public/health"),
        ("agent-gateway", "http://agent-gateway.platform.127.0.0.1.nip.io/health"),
        ("datahub", "http://datahub-gms.platform.127.0.0.1.nip.io/health"),
    ]

    with httpx.Client(timeout=5) as client:
        for name, url in checks:
            try:
                r = client.get(url)
                if r.status_code >= 500:
                    signals.append(Signal(
                        signal_type="service_unhealthy",
                        source="health",
                        priority="P0",
                        payload={"service": name, "status_code": r.status_code, "url": url},
                    ))
                elif r.status_code >= 400:
                    signals.append(Signal(
                        signal_type="service_degraded",
                        source="health",
                        priority="P1",
                        payload={"service": name, "status_code": r.status_code, "url": url},
                    ))
            except httpx.HTTPError:
                signals.append(Signal(
                    signal_type="service_unreachable",
                    source="health",
                    priority="P0",
                    payload={"service": name, "url": url},
                ))

    return signals


# ── Deduplication ─────────────────────────────────────────

def deduplicate(signals: list[Signal], conn: psycopg.Connection) -> list[Signal]:
    """Skip signals that already exist unresolved in the last hour."""
    new = []
    for s in signals:
        # Check if same type+source+payload exists unresolved in last 1h
        row = conn.execute(
            """
            SELECT id FROM signals
            WHERE signal_type = %s AND source = %s AND NOT resolved
              AND created_at > NOW() - INTERVAL '1 hour'
              AND payload @> %s
            LIMIT 1
            """,
            (s.signal_type, s.source, json.dumps(s.payload)),
        ).fetchone()
        if not row:
            new.append(s)
    return new


# ── Write to pgvector ─────────────────────────────────────

def write_signals(signals: list[Signal], conn: psycopg.Connection) -> int:
    """Insert signals into pgvector."""
    count = 0
    for s in signals:
        conn.execute(
            """
            INSERT INTO signals (signal_type, source, priority, payload)
            VALUES (%s, %s, %s, %s)
            """,
            (s.signal_type, s.source, s.priority, json.dumps(s.payload)),
        )
        count += 1
    conn.commit()
    return count


# ── Main ──────────────────────────────────────────────────

COLLECTORS = {
    "k8s": collect_k8s_signals,
    "argocd": collect_argocd_signals,
    "health": collect_health_signals,
}

PG_DSN = "postgresql://pgvector:pgvector@localhost:5432/kagent"  # port-forwarded or direct


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect platform signals")
    parser.add_argument("--source", choices=list(COLLECTORS.keys()), help="Collect from specific source only")
    parser.add_argument("--dry-run", action="store_true", help="Print signals without writing")
    parser.add_argument("--dsn", default=PG_DSN, help="PostgreSQL DSN")
    args = parser.parse_args()

    collectors = {args.source: COLLECTORS[args.source]} if args.source else COLLECTORS

    all_signals: list[Signal] = []
    for name, fn in collectors.items():
        t0 = time.monotonic()
        signals = fn()
        elapsed = round((time.monotonic() - t0) * 1000)
        print(f"  {name}: {len(signals)} signals ({elapsed}ms)")
        all_signals.extend(signals)

    if not all_signals:
        print("  No signals detected. Platform healthy.")
        return

    if args.dry_run:
        for s in all_signals:
            print(f"  [{s.priority}] {s.signal_type} from {s.source}: {json.dumps(s.payload)}")
        return

    # Write to DB (dedup first)
    try:
        with psycopg.connect(args.dsn) as conn:
            new_signals = deduplicate(all_signals, conn)
            if new_signals:
                written = write_signals(new_signals, conn)
                print(f"  Wrote {written} new signals ({len(all_signals) - len(new_signals)} deduped)")
            else:
                print(f"  All {len(all_signals)} signals already tracked (deduped)")
    except psycopg.OperationalError as e:
        print(f"  DB unavailable ({e}), printing signals to stdout:")
        for s in all_signals:
            print(f"  [{s.priority}] {s.signal_type} from {s.source}: {json.dumps(s.payload)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

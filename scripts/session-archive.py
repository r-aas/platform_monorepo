#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "rich>=13.9"]
# ///
"""Session archival utility.

Lists, closes, and cleans up old chat sessions stored in MLflow.

Usage:
    uv run scripts/session-archive.py list              # list all sessions
    uv run scripts/session-archive.py list --active      # active sessions only
    uv run scripts/session-archive.py close-old 24       # close sessions >24h old
    uv run scripts/session-archive.py stats              # session statistics
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import httpx
from rich.console import Console
from rich.table import Table

BASE_URL = os.getenv("N8N_BASE_URL", "http://localhost:5678/webhook")
API_KEY = os.getenv("WEBHOOK_API_KEY", "")
TIMEOUT = 30

console = Console()


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def _post(action: str, **kwargs: object) -> dict:
    payload: dict = {"action": action, **kwargs}
    r = httpx.post(
        f"{BASE_URL}/sessions", json=payload, headers=_headers(), timeout=TIMEOUT
    )
    if r.status_code != 200:
        console.print(f"[red]HTTP {r.status_code}: {r.text[:200]}[/]")
        sys.exit(1)
    return r.json()


def cmd_list(args: argparse.Namespace) -> None:
    """List sessions with optional status filter."""
    kwargs: dict = {}
    if args.active:
        kwargs["status"] = "active"
    elif args.closed:
        kwargs["status"] = "closed"

    data = _post("list", **kwargs)
    sessions = data.get("sessions", [])

    table = Table(title=f"Sessions ({len(sessions)})", show_lines=True)
    table.add_column("Session ID", style="bold")
    table.add_column("Status")
    table.add_column("Messages", justify="right")
    table.add_column("Created")

    for s in sessions:
        status_style = "green" if s.get("status") == "active" else "dim"
        created = s.get("created_at", "")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                created = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, AttributeError):
                pass
        table.add_row(
            s.get("session_id", "?")[:20],
            f"[{status_style}]{s.get('status', '?')}[/]",
            str(s.get("message_count", "?")),
            created,
        )

    console.print(table)


def cmd_close_old(args: argparse.Namespace) -> None:
    """Close sessions older than N hours."""
    data = _post("list", status="active")
    sessions = data.get("sessions", [])
    cutoff = time.time() - (args.hours * 3600)
    closed = 0

    for s in sessions:
        created = s.get("created_at", "")
        if not created:
            continue
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            ts = dt.timestamp()
        except (ValueError, AttributeError):
            continue

        if ts < cutoff:
            sid = s["session_id"]
            result = _post("close", session_id=sid)
            if result.get("status") == "closed":
                console.print(f"  [yellow]closed[/] {sid[:20]} ({s.get('message_count', 0)} msgs)")
                closed += 1

    if closed:
        console.print(f"\n[green]{closed} session(s) archived[/]")
    else:
        console.print(f"[dim]No sessions older than {args.hours}h found[/]")


def cmd_stats(args: argparse.Namespace) -> None:
    """Show session statistics."""
    all_data = _post("list")
    sessions = all_data.get("sessions", [])

    active = [s for s in sessions if s.get("status") == "active"]
    closed = [s for s in sessions if s.get("status") == "closed"]

    msg_counts = [s.get("message_count", 0) for s in sessions if s.get("message_count")]
    total_msgs = sum(msg_counts)
    avg_msgs = total_msgs / len(msg_counts) if msg_counts else 0

    table = Table(title="Session Statistics", show_lines=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total sessions", str(len(sessions)))
    table.add_row("Active", f"[green]{len(active)}[/]")
    table.add_row("Closed", f"[dim]{len(closed)}[/]")
    table.add_row("Total messages", str(total_msgs))
    table.add_row("Avg msgs/session", f"{avg_msgs:.1f}")
    if msg_counts:
        table.add_row("Max msgs", str(max(msg_counts)))

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="Session archival utility")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="List sessions")
    p_list.add_argument("--active", action="store_true", help="Active only")
    p_list.add_argument("--closed", action="store_true", help="Closed only")

    p_close = sub.add_parser("close-old", help="Close sessions older than N hours")
    p_close.add_argument("hours", type=float, help="Age threshold in hours")

    sub.add_parser("stats", help="Session statistics")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "close-old":
        cmd_close_old(args)
    elif args.command == "stats":
        cmd_stats(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

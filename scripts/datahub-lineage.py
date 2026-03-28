#!/usr/bin/env python3
"""Emit cross-service lineage edges to DataHub.

Creates dataset-level lineage between n8n, MLflow, and Langfuse databases
using DataHub's REST API (no datahub Python package needed).

Lineage edges:
  n8n.workflow_entity → mlflow.experiments     (workflows call MLflow for prompts/eval)
  n8n.execution_entity → langfuse.traces       (chat workflow logs traces)
  mlflow.runs → langfuse.traces                (eval runs produce traces)
  mlflow.registered_models → n8n.workflow_entity (prompts used by workflows)

Usage:
  python3 scripts/datahub-lineage.py
  python3 scripts/datahub-lineage.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

GMS_URL = "http://datahub-gms.genai.127.0.0.1.nip.io"
PLATFORM_INSTANCE = "k3d-mewtwo"


def _urn(db: str, table: str) -> str:
    """Dataset URN for a postgres table."""
    return f"urn:li:dataset:(urn:li:dataPlatform:postgres,{PLATFORM_INSTANCE}.{db}.public.{table},PROD)"


# (upstream, downstream, description)
LINEAGE_EDGES = [
    (_urn("n8n", "workflow_entity"), _urn("mlflow", "experiments"), "Workflows use MLflow prompts and create eval experiments"),
    (_urn("n8n", "execution_entity"), _urn("langfuse", "traces"), "Chat executions log traces to Langfuse"),
    (_urn("mlflow", "runs"), _urn("langfuse", "traces"), "Eval runs write observation traces"),
    (_urn("mlflow", "registered_models"), _urn("n8n", "workflow_entity"), "Prompt registry feeds workflow templates"),
    (_urn("n8n", "execution_entity"), _urn("mlflow", "runs"), "Session data stored as MLflow run tags"),
]


def emit_lineage(upstream: str, downstream: str, gms_url: str, dry_run: bool = False) -> bool:
    """Emit a single lineage edge via DataHub REST ingestProposal API."""
    aspect = {
        "upstreams": [
            {
                "auditStamp": {
                    "time": int(time.time() * 1000),
                    "actor": "urn:li:corpuser:datahub",
                },
                "dataset": upstream,
                "type": "TRANSFORMED",
            }
        ]
    }

    proposal = {
        "entityType": "dataset",
        "entityUrn": downstream,
        "aspectName": "upstreamLineage",
        "aspect": {
            "value": json.dumps(aspect),
            "contentType": "application/json",
        },
        "changeType": "UPSERT",
    }

    if dry_run:
        print(f"  [dry-run] {upstream.split(',')[1]} → {downstream.split(',')[1]}")
        return True

    url = f"{gms_url}/aspects?action=ingestProposal"
    data = json.dumps({"proposal": proposal}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True
            print(f"  ! HTTP {resp.status}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  ! {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Emit DataHub lineage edges")
    parser.add_argument("--dry-run", action="store_true", help="Print edges without emitting")
    parser.add_argument("--gms-url", default=GMS_URL, help="DataHub GMS URL")
    args = parser.parse_args()

    gms_url = args.gms_url

    print("DataHub Lineage Emitter")
    print(f"  GMS: {gms_url}")
    print(f"  Edges: {len(LINEAGE_EDGES)}")
    print()

    if not args.dry_run:
        try:
            req = urllib.request.Request(f"{gms_url}/config", method="GET")
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception as e:
            print(f"ERROR: GMS not reachable: {e}", file=sys.stderr)
            sys.exit(1)

    ok = 0
    fail = 0
    for upstream, downstream, desc in LINEAGE_EDGES:
        up_short = upstream.split(",")[1]
        down_short = downstream.split(",")[1]
        success = emit_lineage(upstream, downstream, gms_url=gms_url, dry_run=args.dry_run)
        if success:
            print(f"  ✓ {up_short} → {down_short}")
            print(f"    {desc}")
            ok += 1
        else:
            print(f"  ✗ {up_short} → {down_short}")
            fail += 1

    print()
    print(f"Done. {ok} emitted, {fail} failed.")
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

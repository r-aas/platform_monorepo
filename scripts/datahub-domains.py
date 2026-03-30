#!/usr/bin/env python3
"""Tag DataHub datasets by domain (agent, eval, trace, workflow).

Creates DataHub domains and assigns datasets to the appropriate domain
based on table name and database patterns.

Domains:
  Agent     — agent registry, skills, deployments, MCP servers
  Eval      — experiments, runs, model versions, benchmarks
  Trace     — execution traces, langfuse observations, sessions
  Workflow  — workflow definitions, executions, credentials
  Research  — youtube pipeline, embeddings, analysis

Usage:
  python3 scripts/datahub-domains.py
  python3 scripts/datahub-domains.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

GMS_URL = "http://datahub-gms.platform.127.0.0.1.nip.io"
PLATFORM_INSTANCE = "k3d-mewtwo"


def _urn(db: str, table: str) -> str:
    """Dataset URN for a postgres table."""
    return f"urn:li:dataset:(urn:li:dataPlatform:postgres,{PLATFORM_INSTANCE}.{db}.public.{table},PROD)"


def _domain_urn(name: str) -> str:
    """Domain URN."""
    return f"urn:li:domain:{name}"


# Domain definitions: (id, name, description)
DOMAINS = [
    ("agent", "Agent", "Agent registry, skills, deployments, MCP server configurations"),
    ("eval", "Eval", "Experiment tracking, model evaluation runs, benchmarks, model registry"),
    ("trace", "Trace", "Execution traces, LLM observations, user feedback, sessions"),
    ("workflow", "Workflow", "Workflow definitions, executions, credentials, webhook state"),
    ("research", "Research", "YouTube pipeline, content analysis, embeddings, knowledge extraction"),
]

# Dataset → domain mappings: (dataset_urn, domain_id)
DATASET_DOMAINS = [
    # Agent domain — agent registry tables
    (_urn("mlflow", "registered_models"), "agent"),
    (_urn("mlflow", "registered_model_tags"), "agent"),

    # Eval domain — experiment and run tracking
    (_urn("mlflow", "experiments"), "eval"),
    (_urn("mlflow", "experiment_tags"), "eval"),
    (_urn("mlflow", "runs"), "eval"),
    (_urn("mlflow", "metrics"), "eval"),
    (_urn("mlflow", "params"), "eval"),
    (_urn("mlflow", "tags"), "eval"),
    (_urn("mlflow", "model_versions"), "eval"),
    (_urn("mlflow", "model_version_tags"), "eval"),

    # Trace domain — langfuse traces and observations
    (_urn("langfuse", "traces"), "trace"),
    (_urn("langfuse", "observations"), "trace"),
    (_urn("langfuse", "scores"), "trace"),

    # Workflow domain — n8n workflow definitions and execution history
    (_urn("n8n", "workflow_entity"), "workflow"),
    (_urn("n8n", "execution_entity"), "workflow"),
    (_urn("n8n", "credentials_entity"), "workflow"),
    (_urn("n8n", "webhook_entity"), "workflow"),

    # Research domain — youtube pipeline
    (_urn("youtube", "yt_videos"), "research"),
    (_urn("youtube", "yt_transcripts"), "research"),
    (_urn("youtube", "yt_analysis"), "research"),
    (_urn("youtube", "yt_embeddings"), "research"),
    (_urn("youtube", "yt_pipeline_runs"), "research"),
]


def _gms_post(url: str, data: dict, dry_run: bool = False) -> bool:
    """POST JSON to DataHub GMS. Returns success."""
    if dry_run:
        return True
    encoded = json.dumps(data).encode()
    req = urllib.request.Request(url, data=encoded, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"  ! {e}", file=sys.stderr)
        return False


def create_domain(domain_id: str, name: str, description: str, gms_url: str, dry_run: bool) -> bool:
    """Create or update a DataHub domain."""
    urn = _domain_urn(domain_id)
    proposal = {
        "entityType": "domain",
        "entityUrn": urn,
        "aspectName": "domainProperties",
        "aspect": {
            "value": json.dumps({
                "name": name,
                "description": description,
                "created": {"time": int(time.time() * 1000), "actor": "urn:li:corpuser:datahub"},
            }),
            "contentType": "application/json",
        },
        "changeType": "UPSERT",
    }
    url = f"{gms_url}/aspects?action=ingestProposal"
    return _gms_post(url, {"proposal": proposal}, dry_run)


def assign_domain(dataset_urn: str, domain_id: str, gms_url: str, dry_run: bool) -> bool:
    """Assign a dataset to a domain."""
    proposal = {
        "entityType": "dataset",
        "entityUrn": dataset_urn,
        "aspectName": "domains",
        "aspect": {
            "value": json.dumps({
                "domains": [_domain_urn(domain_id)],
            }),
            "contentType": "application/json",
        },
        "changeType": "UPSERT",
    }
    url = f"{gms_url}/aspects?action=ingestProposal"
    return _gms_post(url, {"proposal": proposal}, dry_run)


def main():
    parser = argparse.ArgumentParser(description="Tag DataHub datasets by domain")
    parser.add_argument("--dry-run", action="store_true", help="Print assignments without applying")
    parser.add_argument("--gms-url", default=GMS_URL, help="DataHub GMS URL")
    args = parser.parse_args()

    gms_url = args.gms_url

    print("DataHub Domain Tagger")
    print(f"  GMS: {gms_url}")
    print(f"  Domains: {len(DOMAINS)}")
    print(f"  Assignments: {len(DATASET_DOMAINS)}")
    print()

    if not args.dry_run:
        try:
            req = urllib.request.Request(f"{gms_url}/config", method="GET")
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception as e:
            print(f"ERROR: GMS not reachable: {e}", file=sys.stderr)
            sys.exit(1)

    # Step 1: Create domains
    print("Creating domains:")
    for domain_id, name, description in DOMAINS:
        ok = create_domain(domain_id, name, description, gms_url, args.dry_run)
        status = "ok" if ok else "FAIL"
        prefix = "[dry-run] " if args.dry_run else ""
        print(f"  {prefix}{name:12s} — {description[:60]}  [{status}]")

    print()

    # Step 2: Assign datasets to domains
    print("Assigning datasets to domains:")
    ok_count = 0
    fail_count = 0
    for dataset_urn, domain_id in DATASET_DOMAINS:
        # Extract short name from URN
        short = dataset_urn.split(",")[1].split(".")[-1]
        db = dataset_urn.split(",")[1].split(".")[1]
        domain_name = next(d[1] for d in DOMAINS if d[0] == domain_id)

        success = assign_domain(dataset_urn, domain_id, gms_url, args.dry_run)
        if success:
            prefix = "[dry-run] " if args.dry_run else ""
            print(f"  {prefix}{db}.{short:25s} -> {domain_name}")
            ok_count += 1
        else:
            print(f"  FAIL  {db}.{short:25s} -> {domain_name}")
            fail_count += 1

    print()
    print(f"Done. {ok_count} assigned, {fail_count} failed.")
    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

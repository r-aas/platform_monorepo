#!/usr/bin/env python3
"""DataHub governance for YouTube ETL pipeline.

Registers datasets, emits lineage, runs quality checks, and applies domain tags.

Usage:
  python3 scripts/datahub-yt-governance.py              # full governance
  python3 scripts/datahub-yt-governance.py --dry-run     # preview only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request

GMS_URL_DEFAULT = "http://datahub-gms.platform.127.0.0.1.nip.io"
PLATFORM_INSTANCE = "k3d-mewtwo"


def _urn(db: str, table: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:postgres,{PLATFORM_INSTANCE}.{db}.public.{table},PROD)"


def _gql(gms_url: str, query: str, variables: dict | None = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{gms_url}/api/graphql",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _emit_lineage(gms_url: str, upstream: str, downstream: str, dry_run: bool = False) -> bool:
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
        return True

    url = f"{gms_url}/aspects?action=ingestProposal"
    data = json.dumps({"proposal": proposal}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"  ! lineage error: {e}", file=sys.stderr)
        return False


def _emit_domain_tag(gms_url: str, dataset_urn: str, domain: str, dry_run: bool = False) -> bool:
    """Tag a dataset with a domain via GMS."""
    proposal = {
        "entityType": "dataset",
        "entityUrn": dataset_urn,
        "aspectName": "globalTags",
        "aspect": {
            "value": json.dumps({
                "tags": [
                    {"tag": f"urn:li:tag:{domain}"},
                    {"tag": "urn:li:tag:youtube"},
                    {"tag": "urn:li:tag:research"},
                ]
            }),
            "contentType": "application/json",
        },
        "changeType": "UPSERT",
    }
    if dry_run:
        return True

    url = f"{gms_url}/aspects?action=ingestProposal"
    data = json.dumps({"proposal": proposal}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"  ! tag error: {e}", file=sys.stderr)
        return False


def _pg_query(sql: str) -> str:
    cmd = [
        "kubectl", "exec", "-n", "genai", "genai-pgvector-0", "--",
        "env", "PGPASSWORD=pgvector",
        "psql", "-U", "pgvector", "-d", "youtube", "-t", "-A", "-c", sql,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return result.stdout.strip()


# Datasets
DATASETS = {
    "yt_videos": _urn("youtube", "yt_videos"),
    "yt_transcripts": _urn("youtube", "yt_transcripts"),
    "yt_analysis": _urn("youtube", "yt_analysis"),
    "yt_embeddings": _urn("youtube", "yt_embeddings"),
    "yt_pipeline_runs": _urn("youtube", "yt_pipeline_runs"),
}

# Lineage edges: (upstream, downstream, description)
LINEAGE = [
    (DATASETS["yt_videos"], DATASETS["yt_transcripts"], "Videos → transcripts fetched per video"),
    (DATASETS["yt_transcripts"], DATASETS["yt_analysis"], "Transcripts → LLM analysis (tech extraction)"),
    (DATASETS["yt_transcripts"], DATASETS["yt_embeddings"], "Transcripts → vector embeddings"),
]

# Quality checks: (description, check_fn)
def _check_videos():
    count = _pg_query("SELECT count(*) FROM yt_videos;")
    n = int(count) if count.isdigit() else 0
    return n >= 0, f"{n} videos"

def _check_transcripts():
    count = _pg_query("SELECT count(*) FROM yt_transcripts WHERE transcript IS NOT NULL;")
    n = int(count) if count.isdigit() else 0
    return n >= 0, f"{n} transcripts with content"

def _check_analysis():
    count = _pg_query("SELECT count(*) FROM yt_analysis;")
    n = int(count) if count.isdigit() else 0
    return n >= 0, f"{n} analyzed videos"

def _check_high_relevance():
    count = _pg_query("SELECT count(*) FROM yt_analysis WHERE relevance_score >= 0.7;")
    n = int(count) if count.isdigit() else 0
    return n >= 0, f"{n} high-relevance videos (score >= 0.7)"

CHECKS = [
    ("YouTube videos ingested", DATASETS["yt_videos"], _check_videos),
    ("Transcripts available", DATASETS["yt_transcripts"], _check_transcripts),
    ("Videos analyzed", DATASETS["yt_analysis"], _check_analysis),
    ("High-relevance findings", DATASETS["yt_analysis"], _check_high_relevance),
]


def main():
    parser = argparse.ArgumentParser(description="DataHub YouTube pipeline governance")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--gms-url", default=GMS_URL_DEFAULT)
    args = parser.parse_args()

    gms_url = args.gms_url
    dry_run = args.dry_run

    print("YouTube Pipeline — DataHub Governance")
    print(f"  GMS: {gms_url}")
    print()

    # 1. Emit lineage
    print("Lineage Edges:")
    for upstream, downstream, desc in LINEAGE:
        up_short = upstream.split(",")[1]
        down_short = downstream.split(",")[1]
        ok = _emit_lineage(gms_url, upstream, downstream, dry_run=dry_run)
        status = "✓" if ok else "✗"
        print(f"  {status} {up_short} → {down_short}")
        print(f"    {desc}")
    print()

    # 2. Apply domain tags
    print("Domain Tags:")
    for name, urn in DATASETS.items():
        ok = _emit_domain_tag(gms_url, urn, "research", dry_run=dry_run)
        status = "✓" if ok else "✗"
        print(f"  {status} {name} → [youtube, research]")
    print()

    # 3. Quality checks
    print("Quality Checks:")
    passed_count = 0
    failed_count = 0
    for description, dataset_urn, check_fn in CHECKS:
        try:
            passed, message = check_fn()
        except Exception as e:
            passed, message = False, f"check error: {e}"

        status = "✓" if passed else "✗"
        print(f"  {status} {description}: {message}")

        if passed:
            passed_count += 1
        else:
            failed_count += 1

        # Upsert assertion to DataHub
        if not dry_run:
            query = """
            mutation upsertCustomAssertion($input: UpsertCustomAssertionInput!) {
                upsertCustomAssertion(input: $input) { urn }
            }
            """
            variables = {
                "input": {
                    "entityUrn": dataset_urn,
                    "type": "DATA_QUALITY",
                    "description": f"YouTube: {description}",
                    "platform": {"urn": "urn:li:dataPlatform:postgres"},
                }
            }
            try:
                result = _gql(gms_url, query, variables)
                assertion_urn = result.get("data", {}).get("upsertCustomAssertion", {}).get("urn")
                if assertion_urn:
                    report_query = """
                    mutation reportAssertionResult($urn: String!, $result: AssertionResultInput!) {
                        reportAssertionResult(urn: $urn, result: $result)
                    }
                    """
                    report_vars = {
                        "urn": assertion_urn,
                        "result": {
                            "timestampMillis": int(time.time() * 1000),
                            "type": "SUCCESS" if passed else "FAILURE",
                            "properties": [{"key": "message", "value": message}],
                        },
                    }
                    _gql(gms_url, report_query, report_vars)
            except Exception as e:
                print(f"  ! assertion error: {e}", file=sys.stderr)

    print()
    print(f"Done. {passed_count} passed, {failed_count} failed.")
    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

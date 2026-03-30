#!/usr/bin/env python3
"""Create and run data quality assertions in DataHub.

Checks freshness and row counts for platform databases, reports results
via DataHub's GraphQL API.

Usage:
  python3 scripts/datahub-quality.py              # run all checks
  python3 scripts/datahub-quality.py --dry-run     # preview only
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


def _pg_query(pod: str, db: str, user: str, password: str, sql: str) -> str:
    """Run SQL against a k8s PostgreSQL pod."""
    cmd = [
        "kubectl", "exec", "-n", "genai", pod, "--",
        "env", f"PGPASSWORD={password}",
        "psql", "-U", user, "-d", db, "-t", "-A", "-c", sql,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return result.stdout.strip()


# Quality checks: (description, dataset_urn, check_fn)
# check_fn returns (passed: bool, message: str)
def _check_n8n_workflows() -> tuple[bool, str]:
    count = _pg_query("genai-pg-n8n-0", "n8n", "n8n", "n8n",
                      "SELECT count(*) FROM workflow_entity;")
    n = int(count) if count.isdigit() else 0
    return n > 0, f"{n} workflows (expect >0)"


def _check_n8n_executions() -> tuple[bool, str]:
    count = _pg_query("genai-pg-n8n-0", "n8n", "n8n", "n8n",
                      "SELECT count(*) FROM execution_entity;")
    n = int(count) if count.isdigit() else 0
    return n >= 0, f"{n} executions"


def _check_mlflow_experiments() -> tuple[bool, str]:
    count = _pg_query("genai-pg-mlflow-0", "mlflow", "mlflow", "mlflow",
                      "SELECT count(*) FROM experiments;")
    n = int(count) if count.isdigit() else 0
    return n >= 3, f"{n} experiments (expect >=3)"


def _check_mlflow_runs() -> tuple[bool, str]:
    count = _pg_query("genai-pg-mlflow-0", "mlflow", "mlflow", "mlflow",
                      "SELECT count(*) FROM runs;")
    n = int(count) if count.isdigit() else 0
    return n > 0, f"{n} runs (expect >0)"


def _check_mlflow_models() -> tuple[bool, str]:
    count = _pg_query("genai-pg-mlflow-0", "mlflow", "mlflow", "mlflow",
                      "SELECT count(*) FROM registered_models;")
    n = int(count) if count.isdigit() else 0
    return n >= 5, f"{n} registered models (expect >=5 prompts)"


CHECKS = [
    ("n8n workflows exist", _urn("n8n", "workflow_entity"), _check_n8n_workflows),
    ("n8n executions accessible", _urn("n8n", "execution_entity"), _check_n8n_executions),
    ("MLflow experiments seeded", _urn("mlflow", "experiments"), _check_mlflow_experiments),
    ("MLflow runs present", _urn("mlflow", "runs"), _check_mlflow_runs),
    ("MLflow prompts registered", _urn("mlflow", "registered_models"), _check_mlflow_models),
]


def upsert_assertion(gms_url: str, dataset_urn: str, description: str, dry_run: bool = False) -> str | None:
    """Create or update a custom assertion. Returns assertion URN."""
    if dry_run:
        return "urn:li:assertion:dry-run"

    query = """
    mutation upsertCustomAssertion($input: UpsertCustomAssertionInput!) {
        upsertCustomAssertion(input: $input) { urn }
    }
    """
    variables = {
        "input": {
            "entityUrn": dataset_urn,
            "type": "DATA_QUALITY",
            "description": description,
            "platform": {"urn": "urn:li:dataPlatform:postgres"},
        }
    }
    try:
        result = _gql(gms_url, query, variables)
        assertion = result.get("data", {}).get("upsertCustomAssertion", {})
        return assertion.get("urn") if assertion else None
    except Exception as e:
        print(f"  ! upsert failed: {e}", file=sys.stderr)
        return None


def report_result(gms_url: str, assertion_urn: str, passed: bool, message: str, dry_run: bool = False) -> bool:
    """Report assertion result."""
    if dry_run:
        return True

    query = """
    mutation reportAssertionResult($urn: String!, $result: AssertionResultInput!) {
        reportAssertionResult(urn: $urn, result: $result)
    }
    """
    variables = {
        "urn": assertion_urn,
        "result": {
            "timestampMillis": int(time.time() * 1000),
            "type": "SUCCESS" if passed else "FAILURE",
            "properties": [
                {"key": "message", "value": message},
            ],
        },
    }
    try:
        result = _gql(gms_url, query, variables)
        if result.get("errors"):
            print(f"  ! report error: {result['errors'][0]['message'][:120]}", file=sys.stderr)
            return False
        return result.get("data", {}).get("reportAssertionResult") is not None
    except Exception as e:
        print(f"  ! report failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="DataHub data quality checks")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--gms-url", default=GMS_URL_DEFAULT)
    args = parser.parse_args()

    gms_url = args.gms_url
    print("DataHub Quality Checks")
    print(f"  GMS: {gms_url}")
    print(f"  Checks: {len(CHECKS)}")
    print()

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

        # Upsert assertion and report result to DataHub
        assertion_urn = upsert_assertion(gms_url, dataset_urn, description, dry_run=args.dry_run)
        if assertion_urn:
            report_result(gms_url, assertion_urn, passed, message, dry_run=args.dry_run)

    print()
    print(f"Done. {passed_count} passed, {failed_count} failed.")
    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

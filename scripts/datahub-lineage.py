#!/usr/bin/env python3
"""Emit cross-system lineage assertions to DataHub.

Creates lineage edges:
  agent → prompt → model (MLflow entities)
  workflow → service → database (n8n/k8s entities)

Usage: python3 scripts/datahub-lineage.py [--dry-run]
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

GMS_URL = os.environ.get(
    "DATAHUB_GMS_URL",
    "http://datahub-gms.genai.127.0.0.1.nip.io",
)
TOKEN = os.environ.get("DATAHUB_TOKEN", "")
DRY_RUN = "--dry-run" in sys.argv

# Platform URN helpers
def dataset_urn(platform: str, name: str, env: str = "PROD") -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{name},{env})"

def dataflow_urn(platform: str, name: str, cluster: str = "PROD") -> str:
    return f"urn:li:dataFlow:({platform},{name},{cluster})"

def datajob_urn(flow: str, job_id: str) -> str:
    return f"urn:li:dataJob:({flow},{job_id})"


# === Lineage Definitions ===

# Agent → Prompt → Model lineage
AGENT_LINEAGE = [
    # agent:mlops uses mlops.SYSTEM prompt, which uses qwen2.5:14b model
    {
        "upstream": dataset_urn("mlflow", "prompts/mlops.SYSTEM"),
        "downstream": dataset_urn("mlflow", "agents/mlops"),
        "label": "agent:mlops → mlops.SYSTEM prompt",
    },
    {
        "upstream": dataset_urn("mlflow", "models/qwen2.5:14b"),
        "downstream": dataset_urn("mlflow", "prompts/mlops.SYSTEM"),
        "label": "mlops.SYSTEM prompt → qwen2.5:14b model",
    },
    # agent:developer
    {
        "upstream": dataset_urn("mlflow", "prompts/developer.SYSTEM"),
        "downstream": dataset_urn("mlflow", "agents/developer"),
        "label": "agent:developer → developer.SYSTEM prompt",
    },
    {
        "upstream": dataset_urn("mlflow", "models/qwen2.5:14b"),
        "downstream": dataset_urn("mlflow", "prompts/developer.SYSTEM"),
        "label": "developer.SYSTEM → qwen2.5:14b model",
    },
    # agent:platform-admin
    {
        "upstream": dataset_urn("mlflow", "prompts/platform-admin.SYSTEM"),
        "downstream": dataset_urn("mlflow", "agents/platform-admin"),
        "label": "agent:platform-admin → platform-admin.SYSTEM prompt",
    },
]

# Workflow → Service → Database lineage
WORKFLOW_LINEAGE = [
    # chat-v1 workflow → LiteLLM → Ollama
    {
        "upstream": dataset_urn("k8s", "genai/genai-litellm"),
        "downstream": dataflow_urn("n8n", "chat-v1"),
        "label": "chat-v1 → LiteLLM",
    },
    {
        "upstream": dataset_urn("k8s", "host/ollama"),
        "downstream": dataset_urn("k8s", "genai/genai-litellm"),
        "label": "LiteLLM → Ollama",
    },
    # eval workflow → MLflow
    {
        "upstream": dataset_urn("k8s", "genai/genai-mlflow"),
        "downstream": dataflow_urn("n8n", "eval-v1"),
        "label": "eval-v1 → MLflow",
    },
    # sessions workflow → PostgreSQL
    {
        "upstream": dataset_urn("k8s", "genai/genai-pg-n8n"),
        "downstream": dataflow_urn("n8n", "sessions-v1"),
        "label": "sessions-v1 → PostgreSQL",
    },
]


def emit_lineage(upstream: str, downstream: str, label: str) -> bool:
    """Post an upstream lineage MCP to DataHub GMS."""
    mcp = {
        "proposal": {
            "entityType": downstream.split(":")[2] if "dataFlow" in downstream or "dataJob" in downstream else "dataset",
            "entityUrn": downstream,
            "aspectName": "upstreamLineage",
            "aspect": {
                "contentType": "application/json",
                "value": json.dumps({
                    "upstreams": [
                        {
                            "auditStamp": {
                                "time": 0,
                                "actor": "urn:li:corpuser:datahub",
                            },
                            "dataset": upstream,
                            "type": "TRANSFORMED",
                        }
                    ]
                }),
            },
            "changeType": "UPSERT",
        }
    }

    if DRY_RUN:
        print(f"  [DRY-RUN] {label}")
        return True

    try:
        data = json.dumps(mcp).encode()
        headers = {"Content-Type": "application/json"}
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"

        req = urllib.request.Request(
            f"{GMS_URL}/aspects?action=ingestProposal",
            data=data,
            headers=headers,
        )
        resp = urllib.request.urlopen(req, timeout=10)
        if resp.status == 200:
            print(f"  [OK] {label}")
            return True
        else:
            print(f"  [FAIL:{resp.status}] {label}")
            return False
    except Exception as e:
        print(f"  [ERROR] {label}: {e}")
        return False


def main() -> None:
    print("=== Emitting Cross-System Lineage ===")
    print(f"    GMS: {GMS_URL}")
    print(f"    Mode: {'DRY-RUN' if DRY_RUN else 'LIVE'}")
    print()

    ok = 0
    fail = 0

    print("--- Agent → Prompt → Model ---")
    for edge in AGENT_LINEAGE:
        if emit_lineage(edge["upstream"], edge["downstream"], edge["label"]):
            ok += 1
        else:
            fail += 1

    print()
    print("--- Workflow → Service → Database ---")
    for edge in WORKFLOW_LINEAGE:
        if emit_lineage(edge["upstream"], edge["downstream"], edge["label"]):
            ok += 1
        else:
            fail += 1

    print()
    print(f"=== Done: {ok} OK, {fail} FAIL ===")
    sys.exit(1 if fail > 0 else 0)


if __name__ == "__main__":
    main()

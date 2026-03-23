import copy
import json
from pathlib import Path

import httpx

VOLATILE_FIELDS = frozenset({"id", "active", "updatedAt", "createdAt", "versionId"})


def strip_volatile(workflow: dict) -> dict:
    """Remove fields that change between environments and shouldn't be tracked."""
    result = copy.deepcopy(workflow)
    for field in VOLATILE_FIELDS:
        result.pop(field, None)
    if isinstance(result.get("meta"), dict):
        result["meta"].pop("executionCount", None)
    return result


def sort_nodes(workflow: dict) -> dict:
    """Sort workflow nodes alphabetically by name for stable diffs."""
    result = copy.deepcopy(workflow)
    if "nodes" in result:
        result["nodes"] = sorted(result["nodes"], key=lambda n: n.get("name", ""))
    return result


def portabilize_credentials(workflow: dict) -> dict:
    """Replace environment-specific credential IDs with portable type+name refs."""
    result = copy.deepcopy(workflow)
    for node in result.get("nodes", []):
        for cred_type, cred_val in list(node.get("credentials", {}).items()):
            if isinstance(cred_val, dict) and "id" in cred_val:
                node["credentials"][cred_type] = {
                    "$portable": True,
                    "type": cred_type,
                    "name": cred_val.get("name", ""),
                }
    return result


def export_workflow(workflow: dict) -> dict:
    """Apply the full export pipeline: strip → sort → portabilize."""
    result = strip_volatile(workflow)
    result = sort_nodes(result)
    result = portabilize_credentials(result)
    return result


async def fetch_workflows(n8n_base_url: str, api_key: str) -> list[dict]:
    """Fetch all workflows from n8n via API."""
    headers = {"X-N8N-API-KEY": api_key}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{n8n_base_url}/api/v1/workflows", headers=headers)
        response.raise_for_status()
        return response.json().get("data", [])


async def export_all(n8n_base_url: str, api_key: str, output_dir: Path) -> list[str]:
    """Fetch workflows from n8n, export each as portable JSON to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    workflows = await fetch_workflows(n8n_base_url, api_key)
    exported = []
    for wf in workflows:
        portable = export_workflow(wf)
        name = portable.get("name", "unknown")
        safe_name = name.replace(" ", "-").lower()
        out_path = output_dir / f"{safe_name}.json"
        out_path.write_text(json.dumps(portable, indent=2))
        exported.append(safe_name)
    return exported

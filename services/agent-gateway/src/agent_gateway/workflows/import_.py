import copy
import json
from pathlib import Path

import httpx


async def fetch_credentials(
    n8n_base_url: str, api_key: str
) -> dict[tuple[str, str], str]:
    """Fetch all credentials from n8n and return a (type, name) → id map."""
    headers = {"X-N8N-API-KEY": api_key}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{n8n_base_url}/api/v1/credentials", headers=headers)
        response.raise_for_status()
        creds = response.json().get("data", [])
    return {(c["type"], c["name"]): c["id"] for c in creds}


def resolve_credentials(
    workflow: dict, cred_map: dict[tuple[str, str], str]
) -> dict:
    """Replace portable credential refs with real IDs from the target n8n instance."""
    result = copy.deepcopy(workflow)
    for node in result.get("nodes", []):
        for cred_type, cred_val in list(node.get("credentials", {}).items()):
            if isinstance(cred_val, dict) and cred_val.get("$portable"):
                key = (cred_val["type"], cred_val["name"])
                if key not in cred_map:
                    raise ValueError(
                        f"Cannot resolve portable credential {cred_type!r} "
                        f"name={cred_val['name']!r}: not found in target n8n"
                    )
                node["credentials"][cred_type] = {
                    "id": cred_map[key],
                    "name": cred_val["name"],
                }
    return result


async def import_workflow(workflow: dict, n8n_base_url: str, api_key: str) -> dict:
    """Create a workflow in the target n8n via API."""
    headers = {"X-N8N-API-KEY": api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{n8n_base_url}/api/v1/workflows",
            headers=headers,
            json=workflow,
        )
        response.raise_for_status()
        return response.json()


async def import_all(
    workflows_dir: Path, n8n_base_url: str, api_key: str
) -> list[str]:
    """Import all workflow JSONs from workflows_dir into the target n8n."""
    cred_map = await fetch_credentials(n8n_base_url, api_key)
    imported = []
    for wf_file in sorted(workflows_dir.glob("*.json")):
        workflow = json.loads(wf_file.read_text())
        resolved = resolve_credentials(workflow, cred_map)
        result = await import_workflow(resolved, n8n_base_url, api_key)
        imported.append(result.get("name", wf_file.stem))
    return imported

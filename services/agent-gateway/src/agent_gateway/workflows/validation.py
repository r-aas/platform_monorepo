"""Credential portability validation — pre-export and pre-import checks."""


def validate_portable_export(workflow: dict) -> list[str]:
    """Check that all credential references are portable (no raw IDs remain).

    Returns a list of error strings. Empty list means the workflow is fully portable.
    """
    errors = []
    for node in workflow.get("nodes", []):
        for cred_type, cred_val in node.get("credentials", {}).items():
            if isinstance(cred_val, dict) and "id" in cred_val and not cred_val.get("$portable"):
                node_name = node.get("name", "<unknown>")
                errors.append(
                    f"Node '{node_name}' has raw credential ID for '{cred_type}'"
                    f" — run portabilize_credentials() before export"
                )
    return errors


def validate_credentials_resolvable(
    workflow: dict, cred_map: dict[tuple[str, str], str]
) -> list[str]:
    """Check that all portable credential refs can be resolved from cred_map.

    Returns a list of error strings. Empty list means the import can proceed.
    Non-portable credentials (raw IDs) are not checked.
    """
    errors = []
    for node in workflow.get("nodes", []):
        for cred_type, cred_val in node.get("credentials", {}).items():
            if isinstance(cred_val, dict) and cred_val.get("$portable"):
                key = (cred_val["type"], cred_val["name"])
                if key not in cred_map:
                    node_name = node.get("name", "<unknown>")
                    errors.append(
                        f"Node '{node_name}': portable credential '{cred_val['name']}'"
                        f" (type={cred_type!r}) not found in target n8n"
                    )
    return errors

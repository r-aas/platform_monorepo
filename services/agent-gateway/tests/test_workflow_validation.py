"""Tests for workflow credential portability validation (E.01)."""

from agent_gateway.workflows.validation import (
    validate_credentials_resolvable,
    validate_portable_export,
)

# Workflow with fully portabilized credentials
PORTABLE_WORKFLOW = {
    "name": "clean-workflow",
    "nodes": [
        {
            "name": "webhook",
            "credentials": {
                "httpAuth": {"$portable": True, "type": "httpAuth", "name": "webhook-auth"}
            },
        },
        {
            "name": "action",
            "credentials": {},
        },
    ],
}

# Workflow with a raw credential ID still present (not portabilized)
RAW_CRED_WORKFLOW = {
    "name": "raw-workflow",
    "nodes": [
        {
            "name": "webhook",
            "credentials": {"httpAuth": {"id": "cred-99", "name": "webhook-auth"}},
        },
    ],
}

CRED_MAP = {("httpAuth", "webhook-auth"): "real-cred-id-42"}


# ──────────────────────────────────────────────────────────────────────────────
# validate_portable_export
# ──────────────────────────────────────────────────────────────────────────────


def test_validate_portable_export_clean_returns_empty():
    errors = validate_portable_export(PORTABLE_WORKFLOW)
    assert errors == []


def test_validate_portable_export_finds_raw_credential_ids():
    errors = validate_portable_export(RAW_CRED_WORKFLOW)
    assert len(errors) == 1


def test_validate_portable_export_no_credentials_is_clean():
    wf = {"name": "no-creds", "nodes": [{"name": "code-node", "credentials": {}}]}
    errors = validate_portable_export(wf)
    assert errors == []


def test_validate_portable_export_error_includes_node_name():
    errors = validate_portable_export(RAW_CRED_WORKFLOW)
    assert any("webhook" in e for e in errors), f"Expected 'webhook' in errors: {errors}"


# ──────────────────────────────────────────────────────────────────────────────
# validate_credentials_resolvable
# ──────────────────────────────────────────────────────────────────────────────


def test_validate_credentials_resolvable_all_found_returns_empty():
    errors = validate_credentials_resolvable(PORTABLE_WORKFLOW, CRED_MAP)
    assert errors == []


def test_validate_credentials_resolvable_missing_returns_errors():
    errors = validate_credentials_resolvable(PORTABLE_WORKFLOW, {})
    assert len(errors) == 1


def test_validate_credentials_resolvable_non_portable_creds_ignored():
    wf = {
        "name": "raw-wf",
        "nodes": [
            {
                "name": "node",
                "credentials": {"someType": {"id": "raw-id", "name": "raw-name"}},
            }
        ],
    }
    # Non-portable creds don't need to be in the map — they're not checked
    errors = validate_credentials_resolvable(wf, {})
    assert errors == []


def test_validate_credentials_resolvable_error_includes_credential_name():
    errors = validate_credentials_resolvable(PORTABLE_WORKFLOW, {})
    assert any("webhook-auth" in e for e in errors), f"Expected 'webhook-auth' in errors: {errors}"

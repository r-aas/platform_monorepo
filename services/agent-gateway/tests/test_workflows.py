import copy

import pytest

from agent_gateway.workflows.export import (
    export_workflow,
    portabilize_credentials,
    sort_nodes,
    strip_volatile,
)
from agent_gateway.workflows.import_ import resolve_credentials

SAMPLE_WORKFLOW = {
    "id": "abc123",
    "name": "test-workflow",
    "active": True,
    "updatedAt": "2026-01-01T00:00:00Z",
    "createdAt": "2026-01-01T00:00:00Z",
    "versionId": "v1",
    "meta": {"executionCount": 42, "instanceId": "inst-1"},
    "nodes": [
        {
            "name": "webhook",
            "credentials": {"httpAuth": {"id": "cred-99", "name": "webhook-auth"}},
        },
        {
            "name": "action",
            "credentials": {},
        },
        {
            "name": "another",
            "credentials": {"ollamaApi": {"id": "cred-01", "name": "ollama-default"}},
        },
    ],
    "connections": {},
}


# --- strip_volatile ---


def test_strip_volatile_removes_top_level_fields():
    result = strip_volatile(SAMPLE_WORKFLOW)
    for field in ("id", "active", "updatedAt", "createdAt", "versionId"):
        assert field not in result


def test_strip_volatile_removes_execution_count_from_meta():
    result = strip_volatile(SAMPLE_WORKFLOW)
    assert "executionCount" not in result.get("meta", {})


def test_strip_volatile_preserves_other_meta():
    result = strip_volatile(SAMPLE_WORKFLOW)
    assert result["meta"]["instanceId"] == "inst-1"


def test_strip_volatile_preserves_name_and_nodes():
    result = strip_volatile(SAMPLE_WORKFLOW)
    assert result["name"] == "test-workflow"
    assert len(result["nodes"]) == 3


def test_strip_volatile_does_not_mutate_input():
    original_id = SAMPLE_WORKFLOW.get("id")
    strip_volatile(SAMPLE_WORKFLOW)
    assert SAMPLE_WORKFLOW.get("id") == original_id


# --- sort_nodes ---


def test_sort_nodes_alphabetical():
    result = sort_nodes(SAMPLE_WORKFLOW)
    names = [n["name"] for n in result["nodes"]]
    assert names == sorted(names)


def test_sort_nodes_does_not_mutate_input():
    original_order = [n["name"] for n in SAMPLE_WORKFLOW["nodes"]]
    sort_nodes(SAMPLE_WORKFLOW)
    assert [n["name"] for n in SAMPLE_WORKFLOW["nodes"]] == original_order


def test_sort_nodes_no_nodes_field():
    wf = {"name": "empty"}
    result = sort_nodes(wf)
    assert result == {"name": "empty"}


# --- portabilize_credentials ---


def test_portabilize_credentials_replaces_id_with_portable_ref():
    result = portabilize_credentials(SAMPLE_WORKFLOW)
    webhook_node = next(n for n in result["nodes"] if n["name"] == "webhook")
    http_cred = webhook_node["credentials"]["httpAuth"]
    assert http_cred == {"$portable": True, "type": "httpAuth", "name": "webhook-auth"}


def test_portabilize_credentials_empty_creds_unchanged():
    result = portabilize_credentials(SAMPLE_WORKFLOW)
    action_node = next(n for n in result["nodes"] if n["name"] == "action")
    assert action_node["credentials"] == {}


def test_portabilize_credentials_multiple_nodes():
    result = portabilize_credentials(SAMPLE_WORKFLOW)
    another_node = next(n for n in result["nodes"] if n["name"] == "another")
    ollama_cred = another_node["credentials"]["ollamaApi"]
    assert ollama_cred == {"$portable": True, "type": "ollamaApi", "name": "ollama-default"}


def test_portabilize_credentials_does_not_mutate_input():
    portabilize_credentials(SAMPLE_WORKFLOW)
    webhook_node = next(n for n in SAMPLE_WORKFLOW["nodes"] if n["name"] == "webhook")
    assert "id" in webhook_node["credentials"]["httpAuth"]


# --- export_workflow (full pipeline) ---


def test_export_workflow_strips_volatile():
    result = export_workflow(SAMPLE_WORKFLOW)
    assert "id" not in result
    assert "active" not in result
    assert "executionCount" not in result.get("meta", {})


def test_export_workflow_sorts_nodes():
    result = export_workflow(SAMPLE_WORKFLOW)
    names = [n["name"] for n in result["nodes"]]
    assert names == sorted(names)


def test_export_workflow_portabilizes_credentials():
    result = export_workflow(SAMPLE_WORKFLOW)
    for node in result["nodes"]:
        for cred_val in node.get("credentials", {}).values():
            if cred_val:
                assert "id" not in cred_val, f"Raw credential ID found: {cred_val}"


def test_export_workflow_does_not_mutate_input():
    SAMPLE_WORKFLOW_COPY = copy.deepcopy(SAMPLE_WORKFLOW)
    export_workflow(SAMPLE_WORKFLOW)
    assert SAMPLE_WORKFLOW == SAMPLE_WORKFLOW_COPY


# --- resolve_credentials ---

PORTABLE_WORKFLOW = {
    "name": "test-workflow",
    "nodes": [
        {
            "name": "webhook",
            "credentials": {
                "httpAuth": {"$portable": True, "type": "httpAuth", "name": "webhook-auth"}
            },
        },
    ],
}

CRED_MAP = {("httpAuth", "webhook-auth"): "real-cred-id-42"}


def test_resolve_credentials_replaces_portable_ref():
    result = resolve_credentials(PORTABLE_WORKFLOW, CRED_MAP)
    http_cred = result["nodes"][0]["credentials"]["httpAuth"]
    assert http_cred == {"id": "real-cred-id-42", "name": "webhook-auth"}


def test_resolve_credentials_missing_raises_valueerror():
    with pytest.raises(ValueError, match="httpAuth"):
        resolve_credentials(PORTABLE_WORKFLOW, {})


def test_resolve_credentials_missing_raises_includes_name():
    with pytest.raises(ValueError, match="webhook-auth"):
        resolve_credentials(PORTABLE_WORKFLOW, {})


def test_resolve_credentials_non_portable_unchanged():
    wf = {
        "nodes": [
            {
                "name": "node",
                "credentials": {"someType": {"id": "raw-id", "name": "raw-name"}},
            }
        ]
    }
    result = resolve_credentials(wf, {})
    assert result["nodes"][0]["credentials"]["someType"] == {"id": "raw-id", "name": "raw-name"}


def test_resolve_credentials_does_not_mutate_input():
    PORTABLE_COPY = copy.deepcopy(PORTABLE_WORKFLOW)
    resolve_credentials(PORTABLE_WORKFLOW, CRED_MAP)
    assert PORTABLE_WORKFLOW == PORTABLE_COPY

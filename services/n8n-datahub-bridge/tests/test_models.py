from datetime import datetime, timezone

from bridge.models import N8nExecutionEvent


def test_event_parses_from_n8n_payload():
    payload = {
        "executionId": "123",
        "workflowId": "wf-abc",
        "workflowName": "chat-v1",
        "status": "success",
        "startedAt": "2026-03-25T10:00:00Z",
        "finishedAt": "2026-03-25T10:00:05Z",
        "mode": "webhook",
    }
    event = N8nExecutionEvent(**payload)
    assert event.execution_id == "123"
    assert event.workflow_id == "wf-abc"
    assert event.workflow_name == "chat-v1"


def test_datajob_urn():
    event = N8nExecutionEvent(executionId="1", workflowId="wf-1", workflowName="test")
    assert "urn:li:dataJob:" in event.datajob_urn
    assert "wf-1" in event.datajob_urn


def test_to_mcps_produces_expected_entities():
    event = N8nExecutionEvent(
        executionId="exec-1",
        workflowId="wf-1",
        workflowName="chat-v1",
        status="success",
        startedAt=datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc),
        finishedAt=datetime(2026, 3, 25, 10, 0, 5, tzinfo=timezone.utc),
    )
    mcps = event.to_mcps()
    entity_types = [m["entityType"] for m in mcps]
    assert "dataFlow" in entity_types
    assert "dataJob" in entity_types
    assert "dataProcessInstance" in entity_types
    assert len(mcps) == 4  # flow + job + instance + run event


def test_to_mcps_error_status():
    event = N8nExecutionEvent(
        executionId="exec-2",
        workflowId="wf-1",
        workflowName="chat-v1",
        status="error",
    )
    mcps = event.to_mcps()
    run_events = [m for m in mcps if m["aspectName"] == "dataProcessInstanceRunEvent"]
    assert len(run_events) == 1
    assert run_events[0]["aspect"]["result"]["type"] == "FAILURE"


def test_to_mcps_no_run_event_for_running():
    event = N8nExecutionEvent(
        executionId="exec-3",
        workflowId="wf-1",
        workflowName="chat-v1",
        status="running",
    )
    mcps = event.to_mcps()
    run_events = [m for m in mcps if m["aspectName"] == "dataProcessInstanceRunEvent"]
    assert len(run_events) == 0

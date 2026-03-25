import pytest
from unittest.mock import AsyncMock, patch

from bridge.models import N8nExecutionEvent
from bridge.emitter import emit_execution_event


@pytest.mark.asyncio
async def test_emit_sends_mcps():
    event = N8nExecutionEvent(
        executionId="exec-1",
        workflowId="wf-1",
        workflowName="test",
        status="success",
    )

    mock_response = AsyncMock()
    mock_response.status_code = 200

    with patch("bridge.emitter.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await emit_execution_event(event)

    assert result["emitted"] == 4  # flow + job + instance + run event
    assert result["errors"] == 0
    assert mock_client.post.call_count == 4

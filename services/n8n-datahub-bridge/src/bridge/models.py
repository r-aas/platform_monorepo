from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class N8nExecutionEvent(BaseModel):
    """n8n webhook payload for workflow execution events."""

    execution_id: str = Field(..., alias="executionId")
    workflow_id: str = Field(..., alias="workflowId")
    workflow_name: str = Field("", alias="workflowName")
    status: str = "success"
    started_at: datetime | None = Field(None, alias="startedAt")
    finished_at: datetime | None = Field(None, alias="finishedAt")
    mode: str = "webhook"
    retry_of: str | None = Field(None, alias="retryOf")

    model_config = {"populate_by_name": True}

    @property
    def datajob_urn(self) -> str:
        return f"urn:li:dataJob:(urn:li:dataFlow:(n8n,{self.workflow_id},PROD),{self.workflow_id})"

    @property
    def dataprocess_instance_urn(self) -> str:
        return f"urn:li:dataProcessInstance:(urn:li:dataFlow:(n8n,{self.workflow_id},PROD),{self.execution_id})"

    def to_mcps(self) -> list[dict]:
        """Convert to DataHub MetadataChangeProposal dicts for REST emitter."""
        mcps = []

        # DataFlow (represents the n8n instance)
        mcps.append({
            "entityType": "dataFlow",
            "entityUrn": f"urn:li:dataFlow:(n8n,{self.workflow_id},PROD)",
            "changeType": "UPSERT",
            "aspectName": "dataFlowInfo",
            "aspect": {
                "__type": "DataFlowInfo",
                "name": self.workflow_name or self.workflow_id,
                "customProperties": {"platform": "n8n", "mode": self.mode},
            },
        })

        # DataJob (represents the workflow definition)
        mcps.append({
            "entityType": "dataJob",
            "entityUrn": self.datajob_urn,
            "changeType": "UPSERT",
            "aspectName": "dataJobInfo",
            "aspect": {
                "__type": "DataJobInfo",
                "name": self.workflow_name or self.workflow_id,
                "type": "N8N_WORKFLOW",
                "customProperties": {
                    "workflow_id": self.workflow_id,
                    "workflow_name": self.workflow_name,
                },
            },
        })

        # DataProcessInstance (represents this specific execution)
        instance_aspect: dict = {
            "__type": "DataProcessInstanceProperties",
            "name": f"{self.workflow_name}-{self.execution_id}",
            "type": "BATCH_SCHEDULED",
            "customProperties": {
                "execution_id": self.execution_id,
                "status": self.status,
                "mode": self.mode,
            },
        }
        if self.started_at:
            instance_aspect["created"] = {
                "time": int(self.started_at.timestamp() * 1000),
                "actor": "urn:li:corpuser:n8n",
            }
        mcps.append({
            "entityType": "dataProcessInstance",
            "entityUrn": self.dataprocess_instance_urn,
            "changeType": "UPSERT",
            "aspectName": "dataProcessInstanceProperties",
            "aspect": instance_aspect,
        })

        # Run result event
        if self.status in ("success", "error"):
            result_type = "SUCCESS" if self.status == "success" else "FAILURE"
            mcps.append({
                "entityType": "dataProcessInstance",
                "entityUrn": self.dataprocess_instance_urn,
                "changeType": "UPSERT",
                "aspectName": "dataProcessInstanceRunEvent",
                "aspect": {
                    "__type": "DataProcessInstanceRunEvent",
                    "status": "COMPLETE",
                    "timestampMillis": int((self.finished_at or datetime.now()).timestamp() * 1000),
                    "result": {"type": result_type, "nativeResultType": self.status},
                },
            })

        return mcps

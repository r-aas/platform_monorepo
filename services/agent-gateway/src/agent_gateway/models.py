from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


class MCPServerRef(BaseModel):
    """Reference to an MCP server — just a URL with optional tool filter."""

    url: str
    tool_filter: list[str] | None = None


class EvaluationRef(BaseModel):
    """Reference to an evaluation dataset for a task."""

    dataset: str
    metrics: list[str] = []


class TaskDefinition(BaseModel):
    """A named unit of work within a skill."""

    name: str
    description: str = ""
    inputs: list[dict[str, Any]] = []
    evaluation: EvaluationRef | None = None


class SkillDefinition(BaseModel):
    """A named, versioned group of tasks + MCP servers + prompt fragment."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    tags: list[str] = []
    mcp_servers: list[MCPServerRef] = []
    prompt_fragment: str = ""
    tasks: list[TaskDefinition] = []


class LlmConfig(BaseModel):
    """LLM configuration."""

    url: str = ""
    model_id: str = ""
    api_key: str = ""


class AgentDefinition(BaseModel):
    """Full agent definition — identity + capabilities."""

    name: str
    description: str = ""
    system_prompt: str = ""
    mcp_servers: list[MCPServerRef] = []
    skills: list[str] = []
    llm_config: LlmConfig = LlmConfig()
    runtime: str = "n8n"
    workflow: str = ""
    inputs: list[dict[str, Any]] = []
    agentspec_version: str = "26.2.0"
    promotion_stage: str = "primary"
    canary_weight: int = 0


class PipelineStage(BaseModel):
    """A single stage in a multi-agent pipeline."""

    name: str
    agent: str
    description: str = ""
    depends_on: list[str] = []
    inputs: dict[str, Any] = {}


class PipelineRouting(BaseModel):
    """Routing and error-handling config for a pipeline."""

    on_error: str = "stop"  # stop | continue | retry
    max_retries: int = 0
    default_timeout: int = 60


class PipelineDefinition(BaseModel):
    """Multi-agent pipeline — ordered stages with routing config."""

    component_type: str = "Pipeline"
    name: str
    description: str = ""
    version: str = "1.0.0"
    stages: list[PipelineStage]
    routing: PipelineRouting = PipelineRouting()


@dataclass
class AgentRunConfig:
    """Runtime-agnostic invocation payload — the complete recipe to reproduce a run."""

    # Identity
    system_prompt: str

    # Capabilities (resolved from skills)
    prompt_fragments: list[str] = field(default_factory=list)
    mcp_servers: list[MCPServerRef] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)

    # Invocation
    message: str = ""
    agent_params: dict[str, Any] = field(default_factory=dict)

    # Metadata
    agent_name: str = ""
    session_id: str = ""
    llm_config: LlmConfig = field(default_factory=LlmConfig)
    runtime: str = "n8n"
    workflow: str = ""

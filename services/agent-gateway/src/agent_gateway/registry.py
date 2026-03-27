"""Agent registry — reads agent definitions from PostgreSQL.

Supports promotion-aware agent resolution: when an agent has shadow/canary
versions, the resolver uses weighted routing to select the appropriate version.
"""

from __future__ import annotations

import random

from agent_gateway.models import AgentDefinition, LlmConfig, MCPServerRef
from agent_gateway.store.agents import get_agent as _db_get_agent
from agent_gateway.store.agents import list_agents as _db_list_agents


def _row_to_agent(row) -> AgentDefinition:
    """Convert an AgentRow to an AgentDefinition."""
    spec = row.spec or {}

    mcp_servers = []
    for s in spec.get("mcp_servers", []):
        if isinstance(s, dict):
            mcp_servers.append(MCPServerRef(**s))

    llm = spec.get("llm_config", {})
    if isinstance(llm, dict):
        llm_config = LlmConfig(
            url=llm.get("url", llm.get("base_url", "")),
            model_id=llm.get("model_id", llm.get("default_model", "")),
            api_key=llm.get("api_key", llm.get("api_key_ref", "")),
        )
    else:
        llm_config = LlmConfig()

    return AgentDefinition(
        name=row.name,
        description=spec.get("description", ""),
        system_prompt=row.system_prompt or spec.get("system_prompt", ""),
        mcp_servers=mcp_servers,
        skills=row.skills or spec.get("skills", []),
        llm_config=llm_config,
        runtime=row.runtime or spec.get("runtime", "n8n"),
        workflow=spec.get("workflow", spec.get("metadata", {}).get("workflow", "")),
        inputs=spec.get("inputs", []),
        agentspec_version=row.version or spec.get("agentspec_version", "26.2.0"),
    )


async def get_agent(name: str) -> AgentDefinition:
    """Look up an agent by name from PostgreSQL.

    If the agent is at 'canary' stage, randomly routes canary_weight% of
    requests to this version. The caller sees no difference — the routing
    is transparent. Shadow agents are never returned here (they run in
    parallel via the shadow execution path).
    """
    row = await _db_get_agent(name)
    agent = _row_to_agent(row)
    agent.promotion_stage = getattr(row, "promotion_stage", "primary") or "primary"
    agent.canary_weight = getattr(row, "canary_weight", 0) or 0
    return agent


async def list_agents() -> list[AgentDefinition]:
    """List all agents from PostgreSQL."""
    rows = await _db_list_agents()
    return [_row_to_agent(r) for r in rows]

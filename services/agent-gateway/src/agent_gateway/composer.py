"""Compose an AgentRunConfig from agent definition + resolved skills."""

import uuid

from agent_gateway.models import AgentDefinition, AgentRunConfig, MCPServerRef, SkillDefinition


def compose(
    agent: AgentDefinition,
    skills: list[SkillDefinition] | None = None,
    message: str = "",
    params: dict | None = None,
    session_id: str = "",
) -> AgentRunConfig:
    """Build a runtime-agnostic AgentRunConfig from agent + skills."""
    skills = skills or []
    params = params or {}

    # Collect prompt fragments from skills
    prompt_fragments = [s.prompt_fragment for s in skills if s.prompt_fragment]

    # Merge MCP servers: agent's own + all skills', deduplicated by URL
    seen_urls: set[str] = set()
    merged_mcp: list[MCPServerRef] = []
    for s in [*agent.mcp_servers, *[ms for skill in skills for ms in skill.mcp_servers]]:
        if s.url not in seen_urls:
            seen_urls.add(s.url)
            merged_mcp.append(s)

    # Merge tool filters from all skills
    allowed_tools: list[str] = []
    for skill in skills:
        for ms in skill.mcp_servers:
            if ms.tool_filter:
                allowed_tools.extend(ms.tool_filter)

    # Resolve {{placeholders}} in system prompt
    effective_prompt = agent.system_prompt
    for key, value in params.items():
        effective_prompt = effective_prompt.replace(f"{{{{{key}}}}}", str(value))

    return AgentRunConfig(
        system_prompt=effective_prompt,
        prompt_fragments=prompt_fragments,
        mcp_servers=merged_mcp,
        allowed_tools=allowed_tools,
        message=message,
        agent_params=params,
        agent_name=agent.name,
        session_id=session_id or str(uuid.uuid4()),
        llm_config=agent.llm_config,
        runtime=agent.runtime,
        workflow=agent.workflow,
    )

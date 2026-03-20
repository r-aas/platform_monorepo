"""Agent registry — reads agent definitions from MLflow prompt registry."""

import json

import mlflow

from agent_gateway.models import AgentDefinition, LlmConfig, MCPServerRef


def _parse_agent_from_prompt(prompt_name: str, version) -> AgentDefinition:
    """Parse an AgentDefinition from an MLflow prompt version."""
    name = prompt_name.removeprefix("agent:")
    tags = version.tags or {}

    mcp_servers = []
    if mcp_json := tags.get("mcp_servers_json"):
        for s in json.loads(mcp_json):
            mcp_servers.append(MCPServerRef(**s))

    skills = []
    if skills_json := tags.get("skills_json"):
        skills = json.loads(skills_json)

    inputs = []
    if input_json := tags.get("input_schema"):
        inputs = json.loads(input_json)

    return AgentDefinition(
        name=name,
        description=tags.get("agent_description", ""),
        system_prompt=version.template,
        mcp_servers=mcp_servers,
        skills=skills,
        llm_config=LlmConfig(
            url=tags.get("llm_url", ""),
            model_id=tags.get("llm_model", ""),
        ),
        runtime=tags.get("runtime", "n8n"),
        workflow=tags.get("workflow", ""),
        inputs=inputs,
        agentspec_version=tags.get("agentspec_version", "26.2.0"),
    )


async def get_agent(name: str) -> AgentDefinition:
    """Look up an agent by name from MLflow."""
    client = mlflow.MlflowClient()
    try:
        prompt = client.get_prompt(f"agent:{name}")
    except Exception as e:
        raise KeyError(f"Agent '{name}' not found") from e

    latest = prompt.latest_versions[0]
    return _parse_agent_from_prompt(f"agent:{name}", latest)


async def list_agents() -> list[AgentDefinition]:
    """List all agents from MLflow."""
    client = mlflow.MlflowClient()
    prompts = client.search_prompts(filter_string="name LIKE 'agent:%'")
    agents = []
    for p in prompts:
        if p.latest_versions:
            agents.append(_parse_agent_from_prompt(p.name, p.latest_versions[0]))
    return agents

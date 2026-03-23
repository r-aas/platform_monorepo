"""Sync agent definitions from YAML to MLflow prompt registry."""

import json
from pathlib import Path

import mlflow

from agent_gateway.agentspec.loader import load_agents_dir
from agent_gateway.models import AgentDefinition


def sync_agent(agent: AgentDefinition) -> None:
    """Sync a single agent definition to MLflow prompt registry."""
    client = mlflow.MlflowClient()
    prompt_name = f"agent:{agent.name}"

    # Check if prompt exists
    existing = client.search_prompts(filter_string=f"name = '{prompt_name}'")

    if not existing:
        client.create_prompt(name=prompt_name, description=agent.description)

    # Build tags
    tags = {
        "runtime": agent.runtime,
        "workflow": agent.workflow,
        "llm_model": agent.llm_config.model_id,
        "llm_url": agent.llm_config.url,
        "agentspec_version": agent.agentspec_version,
        "agent_description": agent.description,
        "mcp_servers_json": json.dumps([s.model_dump() for s in agent.mcp_servers]),
        "skills_json": json.dumps(agent.skills),
    }

    if agent.inputs:
        tags["input_schema"] = json.dumps(agent.inputs)

    # Create new version and point the "latest" alias at it
    pv = client.create_prompt_version(
        name=prompt_name,
        template=agent.system_prompt,
        tags=tags,
    )
    client.set_prompt_alias(prompt_name, "current", pv.version)


def sync_all(agents_dir: Path) -> list[str]:
    """Sync all agent YAMLs from a directory to MLflow. Returns list of synced agent names."""
    agents = load_agents_dir(agents_dir)
    synced = []
    for agent in agents:
        sync_agent(agent)
        synced.append(agent.name)
    return synced

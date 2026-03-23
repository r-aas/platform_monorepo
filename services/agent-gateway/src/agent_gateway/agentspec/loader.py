"""Load Agent Spec YAML files and resolve $component_ref references."""

from pathlib import Path

import yaml

from agent_gateway.models import AgentDefinition, LlmConfig, MCPServerRef


def _resolve_component_ref(ref_path: str, agents_dir: Path) -> dict:
    """Resolve a $component_ref to its YAML content."""
    ref_file = agents_dir / f"{ref_path}.yaml"
    if not ref_file.exists():
        raise FileNotFoundError(f"Component ref not found: {ref_file}")
    with open(ref_file) as f:
        return yaml.safe_load(f)


def _resolve_refs(data: dict, agents_dir: Path) -> dict:
    """Recursively resolve $component_ref entries in a dict."""
    resolved = {}
    for key, value in data.items():
        if isinstance(value, dict):
            if "$component_ref" in value:
                ref_data = _resolve_component_ref(value["$component_ref"], agents_dir)
                resolved[key] = ref_data
            else:
                resolved[key] = _resolve_refs(value, agents_dir)
        else:
            resolved[key] = value
    return resolved


def load_agent_yaml(path: Path, agents_dir: Path) -> AgentDefinition:
    """Load a single agent YAML file and return an AgentDefinition."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Invalid YAML structure in {path}")

    # Resolve $component_ref
    resolved = _resolve_refs(raw, agents_dir)

    name = resolved.get("name")
    if not name:
        raise ValueError(f"Agent YAML missing required field 'name' in {path}")

    metadata = resolved.get("metadata", {})

    # Parse mcp_servers
    mcp_servers = [MCPServerRef(**s) for s in resolved.get("mcp_servers", [])]

    # Parse llm_config
    llm_raw = resolved.get("llm_config", {})
    llm_config = LlmConfig(
        url=llm_raw.get("url", ""),
        model_id=llm_raw.get("model_id", ""),
        api_key=llm_raw.get("api_key", ""),
    )

    return AgentDefinition(
        name=name,
        description=resolved.get("description", ""),
        system_prompt=resolved.get("system_prompt", ""),
        mcp_servers=mcp_servers,
        skills=metadata.get("skills", []),
        llm_config=llm_config,
        runtime=metadata.get("runtime", "n8n"),
        workflow=metadata.get("workflow", ""),
        inputs=resolved.get("inputs", []),
        agentspec_version=resolved.get("agentspec_version", "26.2.0"),
    )


def load_agents_dir(agents_dir: Path) -> list[AgentDefinition]:
    """Load all agent YAML files from a directory, skipping _shared/."""
    agents = []
    for path in sorted(agents_dir.glob("*.yaml")):
        if path.parent.name == "_shared":
            continue
        agents.append(load_agent_yaml(path, agents_dir))
    return agents

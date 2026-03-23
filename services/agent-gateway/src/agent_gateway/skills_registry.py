"""Skills registry — CRUD operations backed by MLflow model registry."""

import json

import mlflow

from agent_gateway.models import EvaluationRef, MCPServerRef, SkillDefinition, TaskDefinition


def _skill_to_tags(skill: SkillDefinition) -> dict[str, str]:
    """Convert a SkillDefinition to MLflow model tags."""
    return {
        "description": skill.description,
        "version": skill.version,
        "tags_json": json.dumps(skill.tags),
        "mcp_servers_json": json.dumps([s.model_dump() for s in skill.mcp_servers]),
        "prompt_fragment": skill.prompt_fragment,
        "tasks_json": json.dumps([t.model_dump() for t in skill.tasks]),
    }


def _tags_to_skill(model_name: str, tags: dict[str, str]) -> SkillDefinition:
    """Parse a SkillDefinition from MLflow model tags."""
    name = model_name.removeprefix("skill:")

    mcp_servers = []
    if mcp_json := tags.get("mcp_servers_json"):
        mcp_servers = [MCPServerRef(**s) for s in json.loads(mcp_json)]

    tasks = []
    if tasks_json := tags.get("tasks_json"):
        for t in json.loads(tasks_json):
            eval_data = t.pop("evaluation", None)
            task = TaskDefinition(**t)
            if eval_data:
                task.evaluation = EvaluationRef(**eval_data)
            tasks.append(task)

    skill_tags = []
    if tags_json := tags.get("tags_json"):
        skill_tags = json.loads(tags_json)

    return SkillDefinition(
        name=name,
        description=tags.get("description", ""),
        version=tags.get("version", "1.0.0"),
        tags=skill_tags,
        mcp_servers=mcp_servers,
        prompt_fragment=tags.get("prompt_fragment", ""),
        tasks=tasks,
    )


def create_skill(skill: SkillDefinition) -> None:
    """Create a new skill in the registry."""
    client = mlflow.MlflowClient()
    model_name = f"skill:{skill.name}"

    existing = client.search_registered_models(filter_string=f"name = '{model_name}'")
    if existing:
        raise ValueError(f"Skill '{skill.name}' already exists. Use update_skill to modify.")

    client.create_registered_model(name=model_name, description=skill.description, tags=_skill_to_tags(skill))


def get_skill(name: str) -> SkillDefinition:
    """Get a skill by name."""
    client = mlflow.MlflowClient()
    try:
        model = client.get_registered_model(f"skill:{name}")
    except Exception as e:
        raise KeyError(f"Skill '{name}' not found") from e
    return _tags_to_skill(model.name, model.tags)


def list_skills() -> list[SkillDefinition]:
    """List all skills."""
    client = mlflow.MlflowClient()
    models = client.search_registered_models(filter_string="name LIKE 'skill:%'")
    return [_tags_to_skill(m.name, m.tags) for m in models]


def update_skill(skill: SkillDefinition) -> None:
    """Update a skill (sets new tags on the registered model)."""
    client = mlflow.MlflowClient()
    model_name = f"skill:{skill.name}"
    tags = _skill_to_tags(skill)
    for key, value in tags.items():
        client.set_registered_model_tag(model_name, key, value)


def delete_skill(name: str, force: bool = False) -> None:
    """Delete a skill. If force=False and any agent references it, raises ValueError."""
    client = mlflow.MlflowClient()
    model_name = f"skill:{name}"

    if not force:
        referencing_agents = []
        prompts = client.search_prompts(filter_string="name LIKE 'agent:%'")
        for p in prompts:
            if p.latest_versions:
                tags = p.latest_versions[0].tags or {}
                skills_json = tags.get("skills_json", "[]")
                try:
                    agent_skills = json.loads(skills_json)
                except (ValueError, TypeError):
                    agent_skills = []
                if name in agent_skills:
                    referencing_agents.append(p.name.removeprefix("agent:"))
        if referencing_agents:
            raise ValueError(
                f"Skill '{name}' is referenced by agents: {referencing_agents}. "
                "Use force=True to delete anyway."
            )

    client.delete_registered_model(model_name)

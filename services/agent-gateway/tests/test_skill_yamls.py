"""Tests for skill YAML definitions — validate schema + required fields."""

from pathlib import Path

import yaml

from agent_gateway.models import SkillDefinition

# Skills directory is at monorepo_root/skills/
MONOREPO_ROOT = Path(__file__).parent.parent.parent.parent
SKILLS_DIR = MONOREPO_ROOT / "skills"


def load_skill_yaml(name: str) -> SkillDefinition:
    """Load and validate a skill YAML from the skills/ directory."""
    path = SKILLS_DIR / f"{name}.yaml"
    with open(path) as f:
        raw = yaml.safe_load(f)
    return SkillDefinition.model_validate(raw)


# ──────────────────────────────────────────────────────────────────────────────
# B.10 — data-ingestion
# ──────────────────────────────────────────────────────────────────────────────


def test_data_ingestion_skill_loads():
    skill = load_skill_yaml("data-ingestion")
    assert skill.name == "data-ingestion"


def test_data_ingestion_has_description():
    skill = load_skill_yaml("data-ingestion")
    assert skill.description


def test_data_ingestion_has_tags():
    skill = load_skill_yaml("data-ingestion")
    assert skill.tags, "data-ingestion skill must have at least one tag"


def test_data_ingestion_has_mcp_servers():
    skill = load_skill_yaml("data-ingestion")
    assert skill.mcp_servers, "data-ingestion skill must reference at least one MCP server"


def test_data_ingestion_has_prompt_fragment():
    skill = load_skill_yaml("data-ingestion")
    assert skill.prompt_fragment.strip(), "data-ingestion skill must have a non-empty prompt_fragment"


def test_data_ingestion_has_tasks():
    skill = load_skill_yaml("data-ingestion")
    assert skill.tasks, "data-ingestion skill must define at least one task"


def test_data_ingestion_task_names():
    skill = load_skill_yaml("data-ingestion")
    task_names = {t.name for t in skill.tasks}
    # Must cover the core operations described in the ledger
    assert task_names & {"ingest-s3", "ingest-gcs", "load-postgres", "load-vector-store"}, (
        f"Expected at least one of: ingest-s3, ingest-gcs, load-postgres, load-vector-store. Got: {task_names}"
    )


def test_data_ingestion_tasks_have_descriptions():
    skill = load_skill_yaml("data-ingestion")
    for task in skill.tasks:
        assert task.description, f"Task '{task.name}' must have a description"


# ──────────────────────────────────────────────────────────────────────────────
# B.11 — vector-store-ops
# ──────────────────────────────────────────────────────────────────────────────


def test_vector_store_ops_skill_loads():
    skill = load_skill_yaml("vector-store-ops")
    assert skill.name == "vector-store-ops"


def test_vector_store_ops_has_description():
    skill = load_skill_yaml("vector-store-ops")
    assert skill.description


def test_vector_store_ops_has_tags():
    skill = load_skill_yaml("vector-store-ops")
    assert skill.tags, "vector-store-ops skill must have at least one tag"


def test_vector_store_ops_has_mcp_servers():
    skill = load_skill_yaml("vector-store-ops")
    assert skill.mcp_servers, "vector-store-ops skill must reference at least one MCP server"


def test_vector_store_ops_has_prompt_fragment():
    skill = load_skill_yaml("vector-store-ops")
    assert skill.prompt_fragment.strip(), "vector-store-ops skill must have a non-empty prompt_fragment"


def test_vector_store_ops_has_tasks():
    skill = load_skill_yaml("vector-store-ops")
    assert skill.tasks, "vector-store-ops skill must define at least one task"


def test_vector_store_ops_task_names():
    skill = load_skill_yaml("vector-store-ops")
    task_names = {t.name for t in skill.tasks}
    assert task_names & {"create-index", "similarity-search", "upsert-vectors", "delete-index"}, (
        f"Expected at least one of: create-index, similarity-search, upsert-vectors, delete-index. Got: {task_names}"
    )


def test_vector_store_ops_tasks_have_descriptions():
    skill = load_skill_yaml("vector-store-ops")
    for task in skill.tasks:
        assert task.description, f"Task '{task.name}' must have a description"


# ──────────────────────────────────────────────────────────────────────────────
# B.12 — prompt-engineering
# ──────────────────────────────────────────────────────────────────────────────


def test_prompt_engineering_skill_loads():
    skill = load_skill_yaml("prompt-engineering")
    assert skill.name == "prompt-engineering"


def test_prompt_engineering_has_description():
    skill = load_skill_yaml("prompt-engineering")
    assert skill.description


def test_prompt_engineering_has_tags():
    skill = load_skill_yaml("prompt-engineering")
    assert skill.tags, "prompt-engineering skill must have at least one tag"


def test_prompt_engineering_has_mcp_servers():
    skill = load_skill_yaml("prompt-engineering")
    assert skill.mcp_servers, "prompt-engineering skill must reference at least one MCP server"


def test_prompt_engineering_has_prompt_fragment():
    skill = load_skill_yaml("prompt-engineering")
    assert skill.prompt_fragment.strip(), "prompt-engineering skill must have a non-empty prompt_fragment"


def test_prompt_engineering_has_tasks():
    skill = load_skill_yaml("prompt-engineering")
    assert skill.tasks, "prompt-engineering skill must define at least one task"


def test_prompt_engineering_task_names():
    skill = load_skill_yaml("prompt-engineering")
    task_names = {t.name for t in skill.tasks}
    assert task_names & {"design-variants", "run-evals", "compare-results", "apply-best"}, (
        f"Expected at least one of: design-variants, run-evals, compare-results, apply-best. Got: {task_names}"
    )


def test_prompt_engineering_tasks_have_descriptions():
    skill = load_skill_yaml("prompt-engineering")
    for task in skill.tasks:
        assert task.description, f"Task '{task.name}' must have a description"


# ──────────────────────────────────────────────────────────────────────────────
# B.13 — code-generation
# ──────────────────────────────────────────────────────────────────────────────


def test_code_generation_skill_loads():
    skill = load_skill_yaml("code-generation")
    assert skill.name == "code-generation"


def test_code_generation_has_description():
    skill = load_skill_yaml("code-generation")
    assert skill.description


def test_code_generation_has_tags():
    skill = load_skill_yaml("code-generation")
    assert skill.tags, "code-generation skill must have at least one tag"


def test_code_generation_has_mcp_servers():
    skill = load_skill_yaml("code-generation")
    assert skill.mcp_servers, "code-generation skill must reference at least one MCP server"


def test_code_generation_has_prompt_fragment():
    skill = load_skill_yaml("code-generation")
    assert skill.prompt_fragment.strip(), "code-generation skill must have a non-empty prompt_fragment"


def test_code_generation_has_tasks():
    skill = load_skill_yaml("code-generation")
    assert skill.tasks, "code-generation skill must define at least one task"


def test_code_generation_task_names():
    skill = load_skill_yaml("code-generation")
    task_names = {t.name for t in skill.tasks}
    assert task_names & {"generate-code", "modify-code", "verify-tests", "review-diff"}, (
        f"Expected at least one of: generate-code, modify-code, verify-tests, review-diff. Got: {task_names}"
    )


def test_code_generation_tasks_have_descriptions():
    skill = load_skill_yaml("code-generation")
    for task in skill.tasks:
        assert task.description, f"Task '{task.name}' must have a description"

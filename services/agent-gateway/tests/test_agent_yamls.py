"""Tests for agent YAML definitions — validate schema + required fields."""

from pathlib import Path

from agent_gateway.agentspec.loader import load_agent_yaml

# Agents directory is at monorepo_root/agents/
MONOREPO_ROOT = Path(__file__).parent.parent.parent.parent
AGENTS_DIR = MONOREPO_ROOT / "agents"


def load_agent(name: str):
    """Load and validate an agent YAML from the agents/ directory."""
    path = AGENTS_DIR / f"{name}.yaml"
    return load_agent_yaml(path, AGENTS_DIR)


# ──────────────────────────────────────────────────────────────────────────────
# B.16 — data-engineer
# ──────────────────────────────────────────────────────────────────────────────


def test_data_engineer_agent_loads():
    agent = load_agent("data-engineer")
    assert agent.name == "data-engineer"


def test_data_engineer_has_description():
    agent = load_agent("data-engineer")
    assert agent.description


def test_data_engineer_has_system_prompt():
    agent = load_agent("data-engineer")
    assert agent.system_prompt.strip()


def test_data_engineer_has_expected_skills():
    agent = load_agent("data-engineer")
    skills = set(agent.skills)
    assert "data-ingestion" in skills, f"Expected data-ingestion skill. Got: {skills}"
    assert "vector-store-ops" in skills, f"Expected vector-store-ops skill. Got: {skills}"
    assert "kubernetes-ops" in skills, f"Expected kubernetes-ops skill. Got: {skills}"


def test_data_engineer_has_mcp_servers():
    agent = load_agent("data-engineer")
    assert agent.mcp_servers, "data-engineer agent must reference at least one MCP server"


def test_data_engineer_runtime_is_n8n():
    agent = load_agent("data-engineer")
    assert agent.runtime == "n8n"


def test_data_engineer_has_agentspec_version():
    agent = load_agent("data-engineer")
    assert agent.agentspec_version


def test_data_engineer_llm_config():
    agent = load_agent("data-engineer")
    assert agent.llm_config.url
    assert agent.llm_config.model_id


# ──────────────────────────────────────────────────────────────────────────────
# B.17 — platform-admin
# ──────────────────────────────────────────────────────────────────────────────


def test_platform_admin_agent_loads():
    agent = load_agent("platform-admin")
    assert agent.name == "platform-admin"


def test_platform_admin_has_description():
    agent = load_agent("platform-admin")
    assert agent.description


def test_platform_admin_has_system_prompt():
    agent = load_agent("platform-admin")
    assert agent.system_prompt.strip()


def test_platform_admin_has_expected_skills():
    agent = load_agent("platform-admin")
    skills = set(agent.skills)
    assert "kubernetes-ops" in skills, f"Expected kubernetes-ops skill. Got: {skills}"
    assert "n8n-workflow-ops" in skills, f"Expected n8n-workflow-ops skill. Got: {skills}"
    assert "gitlab-pipeline-ops" in skills, f"Expected gitlab-pipeline-ops skill. Got: {skills}"


def test_platform_admin_has_mcp_servers():
    agent = load_agent("platform-admin")
    assert agent.mcp_servers, "platform-admin agent must reference at least one MCP server"


def test_platform_admin_runtime_is_n8n():
    agent = load_agent("platform-admin")
    assert agent.runtime == "n8n"


def test_platform_admin_has_agentspec_version():
    agent = load_agent("platform-admin")
    assert agent.agentspec_version


def test_platform_admin_llm_config():
    agent = load_agent("platform-admin")
    assert agent.llm_config.url
    assert agent.llm_config.model_id


# ──────────────────────────────────────────────────────────────────────────────
# B.18 — developer
# ──────────────────────────────────────────────────────────────────────────────


def test_developer_agent_loads():
    agent = load_agent("developer")
    assert agent.name == "developer"


def test_developer_has_description():
    agent = load_agent("developer")
    assert agent.description


def test_developer_has_system_prompt():
    agent = load_agent("developer")
    assert agent.system_prompt.strip()


def test_developer_has_expected_skills():
    agent = load_agent("developer")
    skills = set(agent.skills)
    assert "code-generation" in skills, f"Expected code-generation skill. Got: {skills}"
    assert "documentation" in skills, f"Expected documentation skill. Got: {skills}"
    assert "security-audit" in skills, f"Expected security-audit skill. Got: {skills}"


def test_developer_has_mcp_servers():
    agent = load_agent("developer")
    assert agent.mcp_servers, "developer agent must reference at least one MCP server"


def test_developer_runtime_is_n8n():
    agent = load_agent("developer")
    assert agent.runtime == "n8n"


def test_developer_has_agentspec_version():
    agent = load_agent("developer")
    assert agent.agentspec_version


def test_developer_llm_config():
    agent = load_agent("developer")
    assert agent.llm_config.url
    assert agent.llm_config.model_id

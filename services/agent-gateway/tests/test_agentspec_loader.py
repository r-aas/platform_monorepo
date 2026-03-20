"""Tests for Agent Spec YAML loading and validation."""

from textwrap import dedent

import pytest

from agent_gateway.agentspec.loader import load_agent_yaml, load_agents_dir


@pytest.fixture
def tmp_agents(tmp_path):
    """Create a temporary agents directory with shared components and an agent YAML."""
    shared = tmp_path / "_shared"
    shared.mkdir()

    (shared / "llm-ollama.yaml").write_text(
        dedent("""\
        url: http://litellm:4000/v1
        model_id: qwen2.5:14b
        """)
    )

    (shared / "mcp-genai.yaml").write_text(
        dedent("""\
        url: http://metamcp:12008/metamcp/genai/mcp
        """)
    )

    (tmp_path / "mlops.yaml").write_text(
        dedent("""\
        component_type: Agent
        name: mlops
        description: MLOps assistant
        metadata:
          runtime: n8n
          workflow: chat-v1
          skills:
            - kubernetes-ops
        mcp_servers:
          - url: http://metamcp:12008/metamcp/genai/mcp
        inputs:
          - title: domain
            type: string
            default: machine learning
        llm_config:
          $component_ref: _shared/llm-ollama
        system_prompt: "You are an expert in {{domain}}."
        agentspec_version: "26.2.0"
        """)
    )

    return tmp_path


def test_load_agent_yaml(tmp_agents):
    agent = load_agent_yaml(tmp_agents / "mlops.yaml", tmp_agents)
    assert agent.name == "mlops"
    assert agent.description == "MLOps assistant"
    assert agent.runtime == "n8n"
    assert agent.workflow == "chat-v1"
    assert agent.skills == ["kubernetes-ops"]
    assert len(agent.mcp_servers) == 1
    assert agent.mcp_servers[0].url == "http://metamcp:12008/metamcp/genai/mcp"
    assert "{{domain}}" in agent.system_prompt
    assert agent.llm_config.url == "http://litellm:4000/v1"
    assert agent.llm_config.model_id == "qwen2.5:14b"
    assert agent.agentspec_version == "26.2.0"


def test_load_agent_resolves_component_ref(tmp_agents):
    agent = load_agent_yaml(tmp_agents / "mlops.yaml", tmp_agents)
    assert agent.llm_config.url == "http://litellm:4000/v1"
    assert agent.llm_config.model_id == "qwen2.5:14b"


def test_load_agent_rejects_invalid_yaml(tmp_agents):
    bad = tmp_agents / "bad.yaml"
    bad.write_text("not: valid: yaml: {{{")
    with pytest.raises(Exception):
        load_agent_yaml(bad, tmp_agents)


def test_load_agent_rejects_missing_name(tmp_agents):
    no_name = tmp_agents / "noname.yaml"
    no_name.write_text(
        dedent("""\
        component_type: Agent
        description: No name agent
        system_prompt: hello
        """)
    )
    with pytest.raises(ValueError, match="name"):
        load_agent_yaml(no_name, tmp_agents)


def test_load_agents_dir(tmp_agents):
    agents = load_agents_dir(tmp_agents)
    assert len(agents) == 1
    assert agents[0].name == "mlops"


def test_load_agents_dir_skips_shared(tmp_agents):
    """_shared/ directory should not be loaded as agents."""
    agents = load_agents_dir(tmp_agents)
    names = [a.name for a in agents]
    assert "_shared" not in names

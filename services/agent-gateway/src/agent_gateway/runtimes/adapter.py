"""RuntimeAdapter — converts AgentRunConfig to runtime-specific workspace.

The adapter is the bridge between the runtime-agnostic AgentRunConfig
(WHAT the agent should do) and the runtime-specific configuration (HOW
it gets done). Each runtime subclass implements from_config() to produce
the files, env vars, and commands needed for its execution model.

This enables:
- Same agent spec benchmarked across runtimes
- A/B testing runtime implementations
- Runtime-agnostic eval framework
"""

from __future__ import annotations

import json
import textwrap
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agent_gateway.models import AgentRunConfig


@dataclass
class RuntimeWorkspace:
    """A prepared workspace for a runtime to execute.

    Contains all the files, env vars, and commands needed
    to launch an agent in a specific runtime.
    """

    # Files to write into the workspace (path -> content)
    files: dict[str, str] = field(default_factory=dict)

    # Environment variables to inject
    env: dict[str, str] = field(default_factory=dict)

    # Command to execute (entrypoint + args)
    command: list[str] = field(default_factory=list)

    # Metadata
    runtime_name: str = ""
    agent_name: str = ""


class RuntimeAdapter(ABC):
    """Base class for converting AgentRunConfig to a runtime workspace."""

    @property
    @abstractmethod
    def runtime_name(self) -> str:
        """Unique name for this runtime."""
        ...

    @abstractmethod
    def from_config(self, config: AgentRunConfig) -> RuntimeWorkspace:
        """Convert an AgentRunConfig into a RuntimeWorkspace."""
        ...


class ClaudeCodeAdapter(RuntimeAdapter):
    """Converts AgentRunConfig to a Claude Code workspace.

    Produces:
    - CLAUDE.md from system_prompt + prompt_fragments
    - .claude/skills/*.md from resolved skill definitions
    - .claude/settings.json with MCP server config
    - Environment variables for model, API key, etc.
    """

    @property
    def runtime_name(self) -> str:
        return "claude-code"

    def from_config(self, config: AgentRunConfig) -> RuntimeWorkspace:
        ws = RuntimeWorkspace(runtime_name=self.runtime_name, agent_name=config.agent_name)

        # 1. Build CLAUDE.md from system prompt + prompt fragments
        ws.files["CLAUDE.md"] = self._build_claude_md(config)

        # 2. Build skill files from prompt fragments
        for i, fragment in enumerate(config.prompt_fragments):
            if fragment.strip():
                skill_name = f"skill-{i:02d}"
                ws.files[f".claude/skills/{skill_name}/SKILL.md"] = self._build_skill_md(
                    skill_name, fragment
                )

        # 3. Build MCP settings from registered servers
        if config.mcp_servers:
            ws.files[".claude/settings.json"] = self._build_mcp_settings(config)

        # 4. Environment variables
        # NOTE: Do NOT set ANTHROPIC_BASE_URL or ANTHROPIC_API_KEY here.
        # Claude Code authenticates via OAuth credentials mounted from k8s secret,
        # and talks directly to api.anthropic.com. Template variables like
        # {{llm_base_url}} from agent specs are for LiteLLM/OpenAI-compat runtimes.
        if config.llm_config.model_id and not config.llm_config.model_id.startswith("{{"):
            ws.env["CLAUDE_MODEL"] = config.llm_config.model_id

        # Agent identity
        ws.env["AGENT_NAME"] = config.agent_name
        ws.env["SESSION_ID"] = config.session_id

        # 5. Command — claude query with the user message
        ws.command = ["claude", "--print", "--dangerously-skip-permissions", config.message]

        return ws

    def _build_claude_md(self, config: AgentRunConfig) -> str:
        """Generate CLAUDE.md from agent identity + skill context."""
        sections = []

        # Agent identity
        if config.system_prompt:
            sections.append(config.system_prompt)

        # Skill context fragments
        if config.prompt_fragments:
            sections.append("\n## Skills Context\n")
            for fragment in config.prompt_fragments:
                if fragment.strip():
                    sections.append(fragment.strip())

        # MCP server documentation
        if config.mcp_servers:
            sections.append("\n## Available MCP Servers\n")
            for server in config.mcp_servers:
                name = getattr(server, "name", "") or server.url.split("/")[-1]
                sections.append(f"- **{name}**: `{server.url}`")
                if server.tool_filter:
                    sections.append(f"  - Tools: {', '.join(server.tool_filter)}")

        # Tool restrictions
        if config.allowed_tools:
            sections.append(f"\n## Allowed Tools\n\nOnly use these tools: {', '.join(config.allowed_tools)}")

        # Agent params as context
        if config.agent_params:
            sections.append("\n## Parameters\n")
            for k, v in config.agent_params.items():
                sections.append(f"- `{k}`: {v}")

        return "\n\n".join(sections) + "\n"

    def _build_skill_md(self, name: str, fragment: str) -> str:
        """Generate a Claude Code skill file from a prompt fragment."""
        return textwrap.dedent(f"""\
            ---
            name: {name}
            description: Injected skill from agent registry
            ---

            {fragment}
        """)

    def _build_mcp_settings(self, config: AgentRunConfig) -> str:
        """Generate .claude/settings.json with MCP server configuration."""
        mcp_servers = {}
        for server in config.mcp_servers:
            name = getattr(server, "name", "") or server.url.split("/")[-1]
            # Claude Code MCP config format
            mcp_servers[name] = {
                "type": "url",
                "url": server.url,
            }

        settings = {
            "mcpServers": mcp_servers,
            "permissions": {
                "allow": ["mcp__*"],  # Allow all MCP tool calls
            },
        }
        return json.dumps(settings, indent=2) + "\n"


class SandboxAdapter(RuntimeAdapter):
    """Converts AgentRunConfig to sandbox (k8s Job) config."""

    @property
    def runtime_name(self) -> str:
        return "sandbox"

    def from_config(self, config: AgentRunConfig) -> RuntimeWorkspace:
        ws = RuntimeWorkspace(runtime_name=self.runtime_name, agent_name=config.agent_name)

        # Sandbox uses a ConfigMap with config.json
        task_config = {
            "system_prompt": config.system_prompt,
            "message": config.message,
            "mcp_servers": [
                {"name": getattr(s, "name", ""), "url": s.url}
                for s in config.mcp_servers
            ],
            "allowed_tools": config.allowed_tools,
            "agent_params": config.agent_params,
        }
        ws.files["config.json"] = json.dumps(task_config, indent=2)
        ws.command = ["python", "/usr/local/bin/entrypoint.py"]
        return ws


class N8nAdapter(RuntimeAdapter):
    """Converts AgentRunConfig to n8n webhook payload."""

    @property
    def runtime_name(self) -> str:
        return "n8n"

    def from_config(self, config: AgentRunConfig) -> RuntimeWorkspace:
        ws = RuntimeWorkspace(runtime_name=self.runtime_name, agent_name=config.agent_name)
        # n8n is invoked via webhook, not file-based workspace
        payload = {
            "message": config.message,
            "agent_params": config.agent_params,
            "session_id": config.session_id,
        }
        ws.files["payload.json"] = json.dumps(payload, indent=2)
        ws.env["N8N_WEBHOOK_URL"] = config.workflow
        return ws


class HttpAdapter(RuntimeAdapter):
    """Converts AgentRunConfig to direct LLM API call config."""

    @property
    def runtime_name(self) -> str:
        return "http"

    def from_config(self, config: AgentRunConfig) -> RuntimeWorkspace:
        ws = RuntimeWorkspace(runtime_name=self.runtime_name, agent_name=config.agent_name)
        ws.env["OPENAI_BASE_URL"] = config.llm_config.url
        ws.env["OPENAI_API_KEY"] = config.llm_config.api_key
        ws.env["OPENAI_MODEL"] = config.llm_config.model_id
        ws.command = ["curl", "-X", "POST", f"{config.llm_config.url}/chat/completions"]
        return ws


# Adapter registry
_ADAPTERS: dict[str, type[RuntimeAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "sandbox": SandboxAdapter,
    "n8n": N8nAdapter,
    "http": HttpAdapter,
}


def get_adapter(runtime_name: str) -> RuntimeAdapter:
    """Get a RuntimeAdapter by name."""
    cls = _ADAPTERS.get(runtime_name)
    if not cls:
        raise ValueError(f"No adapter for runtime '{runtime_name}'. Available: {list(_ADAPTERS.keys())}")
    return cls()

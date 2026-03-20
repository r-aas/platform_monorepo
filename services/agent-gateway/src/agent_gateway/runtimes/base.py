from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from agent_gateway.models import AgentRunConfig


class Runtime(ABC):
    """Abstract runtime backend for agent execution."""

    @abstractmethod
    async def invoke(self, config: AgentRunConfig) -> AsyncIterator[str]:
        """Execute agent and yield SSE chunks in OpenAI format."""
        ...

    @abstractmethod
    async def invoke_sync(self, config: AgentRunConfig) -> str:
        """Execute agent and return complete response."""
        ...

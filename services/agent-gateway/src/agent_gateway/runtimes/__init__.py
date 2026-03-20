"""Runtime registry — maps runtime names to implementations."""

from agent_gateway.runtimes.base import Runtime
from agent_gateway.runtimes.n8n import N8nRuntime

_RUNTIMES: dict[str, type[Runtime]] = {
    "n8n": N8nRuntime,
}


def get_runtime(name: str) -> Runtime:
    """Get a runtime instance by name."""
    cls = _RUNTIMES.get(name)
    if not cls:
        raise ValueError(f"Unknown runtime: {name}. Available: {list(_RUNTIMES.keys())}")
    return cls()

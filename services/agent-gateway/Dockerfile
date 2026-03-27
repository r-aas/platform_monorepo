FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/agent-gateway/pyproject.toml services/agent-gateway/uv.lock services/agent-gateway/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/agent-gateway/src/ src/
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY --from=builder /app/src src/

COPY agents/ data/agents/
COPY skills/ data/skills/

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "agent_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]

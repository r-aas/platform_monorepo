FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/agent-gateway/pyproject.toml services/agent-gateway/uv.lock services/agent-gateway/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/agent-gateway/src/ src/
RUN uv sync --frozen --no-dev

# python:3.12-slim
FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY --from=builder /app/src src/

COPY agents/ data/agents/
COPY skills/ data/skills/

RUN adduser --disabled-password --gecos '' --uid 1001 appuser \
    && chown -R 1001:1001 /app
USER 1001

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "agent_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]

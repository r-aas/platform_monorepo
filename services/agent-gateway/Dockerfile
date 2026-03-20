FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm

WORKDIR /app
COPY --from=builder /app/.venv .venv/
COPY --from=builder /app/src src/

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["uvicorn", "agent_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]

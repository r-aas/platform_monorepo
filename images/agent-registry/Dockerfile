# Agent Registry — portable agent/skill/environment registry service
# Build context: ~/work/repos/agent-platform/
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN uv sync --frozen --no-dev

FROM python:3.12-slim

COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "agent_platform.registry.app:app", "--host", "0.0.0.0", "--port", "8080"]

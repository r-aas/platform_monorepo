# Agent Registry — portable agent/skill/environment registry service
# Build context: ~/work/repos/agent-platform/
# python:3.12-slim
FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4 AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN uv sync --frozen --no-dev && uv pip install --no-deps .

# python:3.12-slim
FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4

COPY --from=builder /build/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN adduser --disabled-password --gecos '' --uid 1001 appuser \
    && chown -R 1001:1001 /app
USER 1001

WORKDIR /app
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "agent_platform.registry.app:app", "--host", "0.0.0.0", "--port", "8080"]

# python:3.12-slim
FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl jq && \
    rm -rf /var/lib/apt/lists/*

# Install uv from pinned image — avoids curl|sh supply chain risk
COPY --from=ghcr.io/astral-sh/uv:0.7.12 /uv /usr/local/bin/uv

# Non-root user with writable workspace
RUN useradd -m -s /bin/bash agent
RUN mkdir -p /home/agent/workspace && chown agent:agent /home/agent/workspace
WORKDIR /home/agent/workspace

# Copy entrypoint
COPY entrypoint.py /usr/local/bin/entrypoint.py
RUN chmod +x /usr/local/bin/entrypoint.py

USER agent

ENTRYPOINT ["python", "/usr/local/bin/entrypoint.py"]

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl jq && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

# Non-root user with writable workspace
RUN useradd -m -s /bin/bash agent
RUN mkdir -p /home/agent/workspace && chown agent:agent /home/agent/workspace
WORKDIR /home/agent/workspace

# Copy entrypoint
COPY entrypoint.py /usr/local/bin/entrypoint.py
RUN chmod +x /usr/local/bin/entrypoint.py

USER agent

ENTRYPOINT ["python", "/usr/local/bin/entrypoint.py"]

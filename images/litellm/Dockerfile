ARG LITELLM_VERSION=main-stable
# litellm-database includes Prisma — required for MCP registry, virtual keys, A2A
FROM ghcr.io/berriai/litellm-database:${LITELLM_VERSION}

# mlflow required for success_callback: ["mlflow"]
RUN pip install --no-cache-dir mlflow==3.10.0

ARG LITELLM_VERSION=main-latest
FROM ghcr.io/berriai/litellm:${LITELLM_VERSION}

# mlflow required for success_callback: ["mlflow"]
RUN pip install --no-cache-dir mlflow==3.10.0

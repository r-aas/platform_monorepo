# SECURITY: Pin to exact version. DO NOT use floating tags (main-stable, latest).
# LiteLLM PyPI was compromised on 2026-03-24 (versions 1.82.7, 1.82.8).
# Only upgrade after verifying: (1) version exists as GitHub release tag,
# (2) Docker image matches GitHub release, (3) no .pth files in site-packages.
# See: https://github.com/BerriAI/litellm/issues/24518
ARG LITELLM_VERSION=main-stable
# litellm-database includes Prisma — required for MCP registry, virtual keys, A2A
FROM ghcr.io/berriai/litellm-database:${LITELLM_VERSION}

# mlflow required for success_callback: ["mlflow"]
RUN pip install --no-cache-dir mlflow==3.10.0 && \
    # Supply chain verification: ensure no malicious .pth files exist
    ! find /usr/local/lib -name "litellm_init.pth" -print -quit | grep -q . && \
    python -c "import litellm; v=__import__('importlib.metadata', fromlist=['version']).version('litellm'); assert v.startswith('1.82.'), f'Unexpected litellm version: {v}'"

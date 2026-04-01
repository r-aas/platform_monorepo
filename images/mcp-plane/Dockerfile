# python:3.12-slim
FROM python:3.14-slim@sha256:fb83750094b46fd6b8adaa80f66e2302ecbe45d513f6cece637a841e1025b4ca

WORKDIR /app
COPY server.py .

RUN pip install --no-cache-dir "mcp[cli]==1.9.4" httpx==0.28.1

RUN adduser --disabled-password --gecos '' --uid 1001 appuser \
    && chown -R 1001:1001 /app
USER 1001

EXPOSE 3000
CMD ["python", "server.py"]

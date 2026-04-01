# python:3.12-slim
FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4

WORKDIR /app
COPY server.py .

RUN pip install --no-cache-dir "mcp[cli]==1.9.4" httpx==0.28.1

RUN adduser --disabled-password --gecos '' --uid 1001 appuser \
    && chown -R 1001:1001 /app
USER 1001

EXPOSE 3000
CMD ["python", "server.py"]

###############################################################################
# ODD Platform MCP Server — data catalog, lineage, quality
#
# Wraps ODD Platform REST API as MCP tools via fastmcp
#
# Tools: search_catalog, get_entity, get_upstream/downstream_lineage,
#        get_schema, get_quality_tests, list_tags/terms/namespaces/datasources,
#        list_alerts, get_activity, get_platform_info
#
# Env: ODD_BASE_URL, ODD_API_KEY (optional), PORT (default 3000)
###############################################################################
# python:3.12-slim
FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4

RUN pip install --no-cache-dir "mcp[cli]==1.9.4" httpx==0.28.1 "uvicorn<0.42"

WORKDIR /app
COPY server.py .

RUN adduser --disabled-password --gecos '' --uid 1001 appuser \
    && chown -R 1001:1001 /app
USER 1001

ENV PORT=3000
EXPOSE 3000

CMD ["python", "server.py"]

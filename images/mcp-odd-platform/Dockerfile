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
FROM python:3.12-slim

RUN pip install --no-cache-dir "mcp[cli]" httpx "uvicorn<0.42"

WORKDIR /app
COPY server.py .

ENV PORT=3000
EXPOSE 3000

CMD ["python", "server.py"]

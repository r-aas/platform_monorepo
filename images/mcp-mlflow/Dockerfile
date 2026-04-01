###############################################################################
# MLflow MCP Server — experiment tracking, run analysis, model registry
#
# Uses mcp-proxy to bridge mlflow-mcp (stdio) → streamable HTTP
# so kmcp controller can serve it as a RemoteMCPServer.
#
# Tools: get_experiments, get_runs, get_run, query_runs, get_run_artifacts,
#        get_run_metrics, get_best_run, compare_runs, get_registered_models,
#        get_model_versions, search_runs_by_tags, health
#
# Env: MLFLOW_TRACKING_URI, PORT (default 3000)
###############################################################################
# python:3.12-slim
FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4

RUN pip install --no-cache-dir mlflow-mcp==0.2.0 mcp-proxy==0.4.0

RUN adduser --disabled-password --gecos '' --uid 1001 appuser
USER 1001

ENV PORT=3000
EXPOSE 3000

CMD ["sh", "-c", "mcp-proxy --pass-environment --transport streamablehttp --host 0.0.0.0 --port ${PORT} -- mlflow-mcp"]

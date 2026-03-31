###############################################################################
# MLflow MCP Server — experiment tracking, run analysis, model registry
#
# Uses supergateway to bridge mlflow-mcp (stdio) → streamable HTTP
# so kmcp controller can serve it as a RemoteMCPServer.
#
# Tools: get_experiments, get_runs, get_run, query_runs, get_run_artifacts,
#        get_run_metrics, get_best_run, compare_runs, get_registered_models,
#        get_model_versions, search_runs_by_tags, health
#
# Env: MLFLOW_TRACKING_URI, PORT (default 3000)
###############################################################################
FROM python:3.12-slim

RUN apt-get update -qq && apt-get install -y -qq curl nodejs npm > /dev/null \
    && pip install --no-cache-dir mlflow-mcp \
    && npm install -g supergateway \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PORT=3000
EXPOSE 3000

CMD supergateway --stdio "mlflow-mcp" --outputTransport sse --port ${PORT}

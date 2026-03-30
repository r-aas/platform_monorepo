###############################################################################
# MLflow MCP Server — experiment tracking, run analysis, model registry
#
# Runs mlflow-mcp in stdio mode. The MCP gateway manages container lifecycle,
# transport (SSE/streaming), and health monitoring.
#
# Tools: get_experiments, get_runs, get_run, query_runs, get_run_artifacts,
#        get_run_metrics, get_best_run, compare_runs, get_registered_models,
#        get_model_versions, search_runs_by_tags, health
#
# Requires env: MLFLOW_TRACKING_URI
#
# Build: docker build -t genai-mcp-mlflow -f mlflow.Dockerfile .
###############################################################################
FROM python:3.12-slim

RUN pip install --no-cache-dir mlflow-mcp

CMD ["mlflow-mcp"]

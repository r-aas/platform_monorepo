---
name: mlflow-tracking
version: 1.0.0
description: MLflow experiment tracking and model registry
tags:
- mlops
- tracking
operations:
- mlflow_search_experiments
- mlflow_search_runs
- mlflow_get_run
- mlflow_log_metric
- mlflow_create_experiment
- mlflow_list_registered_models
---

When working with MLflow:
- Search experiments before creating new ones to avoid duplicates
- Use descriptive experiment names with project prefix
- Log all relevant metrics and parameters
- Compare runs side-by-side when evaluating models


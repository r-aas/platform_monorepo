---
name: prompt-engineering
version: 1.0.0
description: Optimize system prompts via A/B evaluation using MLflow experiment tracking
tags:
- prompt
- optimization
- eval
operations:
- mlflow_create_experiment
- mlflow_log_metric
- mlflow_log_param
- mlflow_search_runs
- mlflow_get_run
---

When optimizing prompts:
- Start by defining a clear evaluation metric (e.g. pass rate, latency, user rating)
- Generate multiple variant prompts that differ in tone, structure, or specificity
- Run each variant against the same eval dataset for a fair comparison
- Log all variants and scores to MLflow for reproducibility
- Apply the best-scoring variant only after it beats the baseline by a meaningful margin
- Prefer smaller, targeted edits over wholesale rewrites when iterating


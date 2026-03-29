---
name: gitlab-pipeline-ops
version: 1.0.0
description: GitLab CI/CD pipeline management — trigger, monitor, retry, analyze failures
tags:
- ci-cd
- pipelines
- gitlab
operations:
- list_pipelines
- get_pipeline
- retry_pipeline
- cancel_pipeline
- list_pipeline_jobs
- get_job_log
- list_merge_requests
- get_merge_request
---

When managing GitLab pipelines:
- Check job logs for the specific failure before retrying — blind retries waste CI time
- Common failure patterns: image pull failures (check registry), test failures (check code), timeout (check resource limits)
- When analyzing pipeline duration, compare against rolling average — spikes indicate resource contention
- Link pipeline failures to Plane issues for tracking
- Only retry failed jobs, not entire pipelines, unless the failure is in an early stage
- For the k3d platform specifically: GitLab runner uses kubectl entrypoint, needs cluster access, and gitleaks may false-positive on test fixtures

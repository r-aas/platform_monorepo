---
name: langfuse-ops
version: 1.0.0
description: Langfuse observability — trace analysis, token usage, cost tracking, quality scores
tags:
- observability
- traces
- llm
- costs
operations:
- list_traces
- get_trace
- list_observations
- get_observation
- list_scores
- list_sessions
- get_session
- usage_summary
- error_traces
---

When working with Langfuse traces:
- Always scope queries by time range to avoid scanning the entire trace history
- Report token usage as both raw counts and estimated cost
- When investigating errors, start with error_traces to find patterns, then drill into individual traces
- Compare generation quality scores across different models and prompt versions
- Session analysis is useful for understanding multi-turn conversation quality
- Usage summaries should include period-over-period comparisons when baseline data exists

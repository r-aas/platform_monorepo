---
name: test-generation
version: 1.0.0
description: Generate test cases from specs, measure coverage, identify gaps
tags:
- testing
- qa
- coverage
operations:
- gitlab_get_file
- gitlab_list_files
- gitlab_create_file
- gitlab_create_merge_request
- run_benchmark
- list_benchmark_results
---

When generating tests:
- Read the spec or user story first — tests validate requirements, not implementation details
- Cover happy path, edge cases, error conditions, and boundary values
- For agent benchmarks, test cases should have: input message, expected behavior, evaluation rubric
- Name test cases descriptively: "should_reject_empty_input" not "test_1"
- Track coverage gaps: which agent skills have no test cases? Which edge cases are untested?
- When creating benchmark cases, include both simple (sanity check) and complex (multi-step reasoning) scenarios
- Test generation should produce machine-readable YAML/JSON, not just documentation

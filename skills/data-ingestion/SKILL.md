---
name: data-ingestion
version: 1.0.0
description: Read data from S3/GCS, transform, and load to postgres or vector store
tags:
- data
- etl
- ingestion
operations:
- postgres_query
- postgres_execute
- s3_get_object
- s3_list_objects
- gcs_read_object
- gcs_list_objects
---

When ingesting data:
- List available objects before reading to understand the source structure
- Validate schema before loading to avoid corrupt records
- Prefer batch inserts over row-by-row for postgres targets
- For vector store targets, generate embeddings before upsert
- Report row counts and any skipped/errored records


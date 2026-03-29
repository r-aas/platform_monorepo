---
name: artifact-ops
version: 1.0.0
description: MinIO/S3 artifact management — buckets, objects, lifecycle, storage stats
tags:
- storage
- artifacts
- s3
operations:
- list_buckets
- create_bucket
- delete_bucket
- list_objects
- get_object_info
- get_object_text
- put_object
- delete_object
- bucket_stats
---

When managing artifacts:
- Use consistent bucket naming: {service}-{purpose} (e.g. mlflow-artifacts, agent-outputs, benchmark-results)
- Before deleting objects, check if they're referenced by MLflow runs or agent memory
- Use get_object_info (HEAD request) to check metadata without downloading large files
- Report storage stats in human-readable units (MB/GB) with object counts
- Text files under 64KB can be read directly via get_object_text; larger files need presigned URLs
- When cleaning up, prioritize old benchmark artifacts and temporary agent outputs over model artifacts

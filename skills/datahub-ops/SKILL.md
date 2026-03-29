---
name: datahub-ops
version: 1.0.0
description: DataHub catalog operations — entity search, lineage, quality assertions, domain tagging
tags:
- data
- catalog
- lineage
- quality
operations:
- search_entities
- get_entity
- get_lineage
- list_datasets
- get_dataset_schema
- run_assertions
- get_assertion_results
- list_domains
- tag_dataset_domain
- list_ingestion_sources
- get_ingestion_status
---

When working with DataHub:
- Search entities before creating new ones to avoid duplicates
- Use domain tagging to organize datasets by ownership (agent, eval, trace, workflow, research)
- When checking lineage, trace both upstream and downstream — changes propagate in both directions
- Quality assertions should have clear thresholds based on historical baselines, not arbitrary numbers
- Ingestion failures should be diagnosed by checking source connectivity, then schema compatibility, then resource limits
- Report dataset freshness relative to expected update frequency, not just absolute timestamps

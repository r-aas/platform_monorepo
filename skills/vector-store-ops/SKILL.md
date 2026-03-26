---
name: vector-store-ops
version: 1.0.0
description: pgvector and qdrant index management, similarity search, and vector lifecycle
tags:
- vector-db
- embeddings
- search
operations:
- postgres_query
- postgres_execute
- qdrant_search
- qdrant_upsert
- qdrant_create_collection
- qdrant_delete_collection
---

When working with vector stores:
- Verify the collection or index exists before querying
- Use cosine similarity for text embeddings unless instructed otherwise
- Limit similarity search results to 10 unless the user specifies more
- Report similarity scores alongside results
- Always confirm before deleting an index or collection


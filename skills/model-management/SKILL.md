---
name: model-management
version: 1.0.0
description: Ollama model lifecycle — pull, delete, inspect, monitor VRAM, test inference
tags:
- llm
- models
- ollama
operations:
- list_models
- show_model
- running_models
- pull_model
- delete_model
- copy_model
- ollama_status
- generate_test
---

When managing Ollama models:
- Check running_models before pulling new ones — VRAM is limited (128GB shared with system)
- After pulling a model, always run generate_test to verify it loads and responds correctly
- Before deleting a model, verify no agent config references it (check agent.yaml files)
- Report model sizes in GB, VRAM usage in GB, and quantization level
- When recommending models, consider the trade-off: parameter count → quality, quantization → speed/VRAM
- Keep at least one small model (3b) available for fast operations and one large model (14b+) for quality tasks

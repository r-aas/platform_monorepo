---
name: kubernetes-ops
version: 1.0.0
description: Kubernetes cluster operations and deployment management
tags:
- infrastructure
- deployment
operations:
- kubectl_get
- kubectl_apply
- kubectl_logs
- kubectl_describe
---

When performing Kubernetes operations:
- Always check current state before making changes
- Use kubectl_get to inspect resources before applying
- Verify deployments succeed with kubectl_describe after applying
- Report pod status and any errors clearly


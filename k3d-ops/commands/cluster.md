---
description: Quick k3d cluster status overview — pods, services, ingresses across all namespaces
allowed-tools: mcp__Kubernetes_MCP_Server__kubectl_get, mcp__Kubernetes_MCP_Server__kubectl_context, Bash
---

# Cluster Status Overview

Run a quick health check of the mewtwo k3d cluster. Show:

1. Current kubectl context (verify it's `k3d-mewtwo`)
2. All pods across namespaces `dev`, `stage`, `prod`, `platform` — flag any not Running/Completed
3. All services in those namespaces
4. All ingresses with their hosts
5. Node status

Use the Kubernetes MCP Server tools (kubectl_get, kubectl_context) for all queries. Present results in a clean summary table format, highlighting any issues.

If the cluster isn't reachable, suggest: `cd ~/work && task k3d:cluster-up`

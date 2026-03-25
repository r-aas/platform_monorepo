# Architecture Diagrams

> Auto-generated index. Run `task arch:index` to rebuild.
> Run `task arch:regenerate` after shipping a spec that changes platform services.

**Drift**: 0 stale, 0 undocumented

| Diagram | C4 Level | Last Generated | Lines |
|---------|----------|---------------|-------|
| [c4-components-agent-gateway](./c4-components-agent-gateway.mmd) | Component | 2026-03-25 | 27 |
| [c4-containers-genai](./c4-containers-genai.mmd) | Container | 2026-03-25 | 33 |
| [c4-containers-ingress-nginx](./c4-containers-ingress-nginx.mmd) | Container | 2026-03-25 | 13 |
| [c4-containers-platform](./c4-containers-platform.mmd) | Container | 2026-03-25 | 16 |
| [c4-context](./c4-context.mmd) | Context | 2026-03-25 | 26 |

## Regeneration

```bash
task arch:all          # Regenerate all diagrams + verify + rebuild index
task arch:context      # C4 Context only
task arch:containers   # C4 Container diagrams (all namespaces)
task arch:components   # C4 Component diagram (default: agent-gateway)
task arch:verify       # Drift detection
task arch:test         # Connectivity tests from container diagrams
```

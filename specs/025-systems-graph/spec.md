<!-- status: shipped -->
# Feature Specification: Connected Systems Graph

**Feature Branch**: `025-systems-graph`
**Created**: 2026-03-25

## User Scenarios & Testing

### User Story 1 - Universal Metadata Registry (Priority: P1)

As a platform engineer, I have a single catalog (DataHub) that indexes every component in my platform — agents, skills, prompts, models, datasets, n8n workflows, Helm releases, k8s services, and GitLab repos — so I can search, browse, and understand the entire system from one place.

**Why this priority**: Without a registry, knowledge lives in scattered YAML files, CLAUDE.md sections, and memory. DataHub unifies it. The MLflow native connector makes this the lowest-effort first step.

**Independent Test**: Deploy DataHub, run MLflow ingestion, verify all 42 prompts and 5 agents appear as searchable entities.

**Acceptance Scenarios**:

1. **Given** DataHub is deployed in k3d, **When** MLflow ingestion runs, **Then** all registered models, prompts, and experiments appear in the DataHub search UI
2. **Given** the n8n-DataHub bridge is running, **When** a workflow executes, **Then** it appears as a DataJob entity with execution metadata
3. **Given** an agent queries DataHub via MCP, **When** it asks "what models do we have?", **Then** it receives a structured list of all registered models with lineage

---

### User Story 2 - Issue Tracking via GitLab + Speckit (Priority: P2)

As a developer, spec tasks are automatically converted to GitLab Issues via `/speckit.taskstoissues`, linked to their parent spec and branch — so I have Jira-like tracking without a separate tool.

**Why this priority**: We already have GitLab CE and speckit. The integration exists (`/speckit.taskstoissues`). Just need to wire it up and make it the default workflow.

**Independent Test**: Run `/speckit.taskstoissues` on spec 024, verify GitLab Issues are created with correct labels and links.

**Acceptance Scenarios**:

1. **Given** a spec has tasks.md, **When** `/speckit.taskstoissues` runs, **Then** GitLab Issues are created with spec number as label and task ID in title
2. **Given** a task is completed, **When** the commit references the issue, **Then** the issue auto-closes
3. **Given** DataHub indexes GitLab, **When** browsing an entity, **Then** related issues are discoverable

---

### User Story 3 - Knowledge Base via Obsidian + DataHub (Priority: P2)

As a developer, my Obsidian vault (~/work/vault/) is indexed in DataHub as documentation entities — so specs, architecture decisions, meeting notes, and project docs are searchable alongside code and data assets.

**Why this priority**: The vault exists and is maintained. Indexing it in DataHub connects human knowledge to system metadata.

**Independent Test**: Run a custom DataHub ingestion source that indexes vault markdown files, verify they appear in search.

**Acceptance Scenarios**:

1. **Given** the Obsidian vault has project notes, **When** the vault ingestion recipe runs, **Then** notes appear as Documentation entities in DataHub
2. **Given** a note references a spec number, **When** viewing it in DataHub, **Then** lineage connects the note to the spec's artifacts

---

### User Story 4 - Zoomable Systems Graph (Priority: P3)

As a platform engineer, I can view a visual graph of my entire platform — from high-level service topology down to individual prompt versions and dataset lineage — and zoom into any layer for detail.

**Why this priority**: DataHub provides lineage graphs natively. The gap is a custom topology view that shows the platform-specific layers (agents → skills → MCP → runtimes → infrastructure).

**Independent Test**: Open DataHub lineage view for an agent, verify it shows the full chain: agent → skill → prompt → model → dataset.

**Acceptance Scenarios**:

1. **Given** DataHub has full metadata, **When** viewing the lineage graph for agent:mlops, **Then** the graph shows: mlops agent → mlops.SYSTEM prompt → qwen2.5:14b model → LiteLLM proxy → Ollama
2. **Given** a workflow depends on MLflow and LiteLLM, **When** viewing its lineage, **Then** both upstream dependencies are visible

---

### Edge Cases

- DataHub deployed but no metadata ingested yet → UI shows empty state with ingestion guidance
- Obsidian vault has thousands of notes → Ingestion must be incremental (only changed files)
- GitLab Issues exceed 100 per spec → Pagination and label filtering
- DataHub lineage graph too large to render → Collapse nodes by domain

## Requirements

### Functional Requirements

- **FR-001**: DataHub MUST be deployed to k3d genai namespace via ArgoCD-managed Helm chart
- **FR-002**: MLflow metadata MUST be ingested via native DataHub connector (models, experiments, prompts)
- **FR-003**: n8n workflow metadata MUST be ingested via custom bridge service (DataJob/DataProcessInstance entities)
- **FR-004**: `/speckit.taskstoissues` MUST create GitLab Issues with spec labels and task IDs
- **FR-005**: Obsidian vault MUST be indexable in DataHub as Documentation entities
- **FR-006**: DataHub MCP server MUST be registered in agent-gateway MCP mesh
- **FR-007**: DataHub MUST be included in `task up` bootstrap and `task smoke` health checks
- **FR-008**: DataHub lineage graph MUST show agent → prompt → model → dataset chains
- **FR-009**: All DataHub deployment MUST be ArgoCD-managed via GitOps
- **FR-010**: The systems graph MUST be browsable via DataHub's native UI at `datahub.platform.127.0.0.1.nip.io`

### Key Entities

- **DataHub**: Metadata graph service + UI + ingestion framework
- **Ingestion Recipe**: YAML config for each metadata source (MLflow, n8n bridge, Obsidian vault)
- **n8n-DataHub Bridge**: FastAPI sidecar translating n8n events into DataHub MCPs
- **DataHub MCP Server**: AI agent access to metadata graph
- **GitLab Issues**: Task tracking linked to specs via labels
- **Obsidian Vault**: Knowledge base at ~/work/vault/ indexed in DataHub

## Success Criteria

### Measurable Outcomes

- **SC-001**: All 42 MLflow prompts and 5 agents appear in DataHub within 5 minutes of ingestion
- **SC-002**: n8n workflow executions generate DataHub entities within 30 seconds
- **SC-003**: `/speckit.taskstoissues` creates GitLab Issues for 100% of tasks in a spec
- **SC-004**: Obsidian vault notes are searchable in DataHub after ingestion
- **SC-005**: An AI agent can query DataHub metadata via MCP in under 5 seconds
- **SC-006**: DataHub total resource usage stays under 8Gi RAM
- **SC-007**: `task smoke` includes DataHub GMS + frontend health checks

## Assumptions

- DataHub Helm chart v0.8.24 with ARM64 native images (confirmed)
- Prerequisites chart provides Kafka + Elasticsearch (not sharing existing postgres)
- GitLab CE API is accessible for issue creation via PAT
- Obsidian vault is a local directory of markdown files (no sync conflicts)

## Dependencies

- Spec 022 (DataHub integration) — provides the core DataHub deployment
- Spec 023 (autonomous agents) — provides the agent MCP mesh for DataHub MCP server
- GitLab CE running in k3d with API access
- Obsidian vault at ~/work/vault/

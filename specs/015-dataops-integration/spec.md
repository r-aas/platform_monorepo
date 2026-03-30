<!-- status: shipped -->
# Spec 015: DataOps Integration (Airflow + OpenMetadata)

## Problem

The genai-mlops stack lacked data pipeline orchestration and data catalog capabilities. MLOps without DataOps means no structured way to manage training data pipelines, feature extraction workflows, or data quality monitoring. Adding Airflow 3 and OpenMetadata completes the DataOps pillar of the platform.

## Dependencies

- **Spec 010** (shipped): `config.yaml` for centralized service configuration
- **Spec 014** (shipped): Observatory dashboard displays DataOps group status

## Requirements

### FR-001: Airflow 3 Service

Apache Airflow 3.0.1 deployed via Docker Compose with a `dataops` profile:

- **Image**: `apache/airflow:3.0.1` (ARM64-native)
- **Database**: Dedicated PostgreSQL 16.8 (`airflow-postgres`) with Docker secrets for password
- **Ports**: 8080 (web UI)
- **Health endpoint**: `/heartbeat` (Airflow 3 changed from `/health`)
- **Volumes**: `airflow-dags`, `airflow-logs` for DAG persistence
- **Init**: `airflow db migrate` + admin user creation on startup
- **Auth**: Basic auth backend (`airflow.api.auth.backend.basic_auth`)

### FR-002: Airflow Database Secret Handling

The `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` connection string MUST be assembled in the `command:` block (shell context), not `environment:` block. Docker Compose `environment:` does not perform shell expansion — `$(cat /run/secrets/...)` is treated as a literal string.

Pattern:
```yaml
entrypoint: /bin/bash
command:
  - -c
  - |
    export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="postgresql+psycopg2://user:$(cat /run/secrets/airflow_postgres_password)@host:5432/db"
    airflow db migrate
    exec airflow standalone
```

### FR-003: OpenMetadata Service

OpenMetadata 1.6.4 deployed via Docker Compose with a `dataops` profile:

- **Image**: `docker.getcollate.io/openmetadata/server:1.6.4`
- **Database**: Dedicated PostgreSQL 16.8 (`openmetadata-postgres`) with Docker secrets
- **Search**: OpenSearch 2.18.0 (see FR-004)
- **Ports**: 8585 (web UI)
- **Health endpoint**: `/api/v1/system/version`
- **Config**: `SEARCH_TYPE=opensearch`, pipeline service URL, log level

### FR-004: OpenSearch for OpenMetadata (ARM64 Workaround)

OpenMetadata requires a search backend. Elasticsearch 8.x crashes on Apple Silicon M4 due to SVE instruction incompatibility in bundled OpenJDK 21.0.3–21.0.5 (`SIGILL` in `java.lang.System.registerNatives()`).

**Solution**: OpenSearch 2.18.0 with `platform: linux/amd64` (QEMU emulation):

```yaml
openmetadata-search:
  image: opensearchproject/opensearch:2.18.0
  platform: linux/amd64
  environment:
    discovery.type: single-node
    plugins.security.disabled: "true"
    OPENSEARCH_JAVA_OPTS: "-Xms512m -Xmx512m"
    DISABLE_INSTALL_DEMO_CONFIG: "true"
    bootstrap.system_call_filter: "false"  # seccomp unavailable under QEMU
  healthcheck:
    start_period: 120s  # QEMU emulation is 3-5x slower
```

**Known limitation**: OpenSearch under QEMU is slow to start (~90-120s). The healthcheck `start_period` is set to 120s to accommodate this. OpenMetadata may be non-functional for local development on Apple Silicon until a native ARM64 search backend is available.

### FR-005: Docker Compose Profile

Both Airflow and OpenMetadata services use the `dataops` profile:

```yaml
profiles: ["dataops"]
```

This means they are NOT started by default with `docker compose up`. Start explicitly:
```bash
docker compose --profile dataops up -d
```

### FR-006: Config.yaml Entries

Both services are registered in `config.yaml`:

```yaml
services:
  airflow:
    version: "3.0.1"
    port: 8080
    health: /heartbeat
    postgres: { version: "16.8", user: airflow, db: airflow }

  openmetadata:
    version: "1.6.4"
    port: 8585
    health: /api/v1/system/version
    postgres: { version: "16.8", user: openmetadata, db: openmetadata }
```

### FR-007: Dashboard Integration

The Observatory Dashboard (Spec 014) includes:
- Airflow and OpenMetadata as service cards on the Services tab
- "DataOps" ops group in the summary bar (healthy/degraded/down based on member services)
- Airflow and OpenMetadata nodes in the topology view (DataOps group)

## Acceptance Scenarios

### SC-001: Airflow Startup
Given `docker compose --profile dataops up -d`, Airflow web UI is accessible at `http://localhost:8080` within 60 seconds. Admin login with `admin/admin` succeeds.

### SC-002: Airflow Health
`curl -sf http://localhost:8080/heartbeat` returns 200.

### SC-003: OpenMetadata Startup (with QEMU)
Given `docker compose --profile dataops up -d`, OpenMetadata web UI is accessible at `http://localhost:8585` within 3 minutes (QEMU overhead).

### SC-004: Dashboard Reflects DataOps
With DataOps profile running, the dashboard Services tab shows both Airflow and OpenMetadata with green status. The DataOps ops group shows "healthy".

### SC-005: DataOps Down Gracefully
With DataOps profile NOT running, the dashboard shows Airflow and OpenMetadata as "down" but all other services and tabs function normally.

## Non-Functional Requirements

### NFR-001: ARM64 Compatibility
Airflow image (`apache/airflow:3.0.1`) MUST be ARM64-native. OpenSearch uses QEMU emulation (`platform: linux/amd64`) as documented workaround.

### NFR-002: Resource Budget
- Airflow: ~1GB RAM, 0.5 CPU
- Airflow PostgreSQL: ~100MB RAM
- OpenMetadata: ~1.5GB RAM, 1 CPU
- OpenMetadata PostgreSQL: ~100MB RAM
- OpenSearch (QEMU): ~1GB RAM, 1 CPU (emulated)
- Total DataOps: ~4GB RAM — significant addition to the stack

### NFR-003: Optional Profile
DataOps services MUST NOT start by default. They are gated behind the `dataops` Docker Compose profile to keep the core stack lightweight.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  DataOps Profile                                │
│                                                  │
│  ┌─────────────┐       ┌──────────────────┐     │
│  │  Airflow 3   │       │  OpenMetadata    │     │
│  │  :8080       │       │  :8585           │     │
│  │  /heartbeat  │       │  /api/v1/system  │     │
│  └──────┬──────┘       └────┬──────┬──────┘     │
│         │                    │      │             │
│  ┌──────▼──────┐  ┌────────▼──┐ ┌─▼──────────┐ │
│  │ airflow-pg  │  │ omd-pg    │ │ OpenSearch  │ │
│  │ :5432       │  │ :5432     │ │ :9200       │ │
│  │ (ARM64)     │  │ (ARM64)   │ │ (QEMU/x86) │ │
│  └─────────────┘  └───────────┘ └─────────────┘ │
└─────────────────────────────────────────────────┘
```

## Files

| File | Action |
|------|--------|
| `docker-compose.yml` | Updated — added airflow, airflow-postgres, openmetadata, openmetadata-postgres, openmetadata-search services |
| `config.yaml` | Updated — added airflow and openmetadata entries |
| `scripts/dashboard.py` | Updated — added DataOps services to health targets |
| `scripts/dashboard-static/topology.js` | Updated — added DataOps group nodes |

## Known Issues

1. **OpenSearch QEMU performance**: 3-5x slower than native. Start time ~90-120s. May timeout on cold start.
2. **Elasticsearch SVE crash**: ES 8.x and OpenSearch ARM64-native both crash with `SIGILL` due to bundled OpenJDK 21.0.3–21.0.5 SVE incompatibility on M4. Fixed in Temurin 21.0.10+ but not yet bundled by ES/OpenSearch.
3. **OpenMetadata may be non-functional**: Depends on OpenSearch being healthy. If OpenSearch fails under QEMU, OpenMetadata won't start. Acceptable limitation for local dev.

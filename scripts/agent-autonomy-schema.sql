-- Agent Autonomy Runtime Schema
-- Database: kagent (pgvector)
-- Run: kubectl exec -n genai genai-pgvector-0 -- psql -U pgvector -d kagent -f /dev/stdin < scripts/agent-autonomy-schema.sql

-- ── Signals ─────────────────────────────────────────────
-- Events collected from platform services that can trigger agent runs.
-- Signal collector n8n workflow writes here; task router reads.

CREATE TABLE IF NOT EXISTS signals (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_type     TEXT NOT NULL,          -- pod_crash, metric_drift, pipeline_failure, etc.
    source          TEXT NOT NULL,          -- kubernetes, mlflow, argocd, gitlab, plane
    priority        TEXT NOT NULL DEFAULT 'P2',  -- P0, P1, P2, P3
    payload         JSONB NOT NULL,         -- signal-specific data
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT,                   -- agent name that handled it
    run_id          TEXT                    -- links to agent_runs.id
);

CREATE INDEX IF NOT EXISTS idx_signals_unresolved ON signals (priority, created_at) WHERE NOT resolved;
CREATE INDEX IF NOT EXISTS idx_signals_type ON signals (signal_type, created_at);

-- ── Agent Memory ────────────────────────────────────────
-- Persistent memory that survives across agent runs.
-- Agents read/write via agent-gateway /v1/agents/{name}/memory API.

CREATE TABLE IF NOT EXISTS agent_memory (
    id              BIGSERIAL PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    category        TEXT NOT NULL,          -- decisions, observations, patterns, incidents, etc.
    content         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    embedding       vector(1024),           -- for semantic recall
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,            -- NULL = never expires
    superseded_by   BIGINT REFERENCES agent_memory(id)  -- newer memory replaces this
);

CREATE INDEX IF NOT EXISTS idx_memory_agent ON agent_memory (agent_name, category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_embedding ON agent_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
CREATE INDEX IF NOT EXISTS idx_memory_active ON agent_memory (agent_name, expires_at) WHERE superseded_by IS NULL;

-- ── Agent Runs ──────────────────────────────────────────
-- Tracks every autonomous agent execution for audit and learning.

CREATE TABLE IF NOT EXISTS agent_runs (
    id              TEXT PRIMARY KEY,       -- UUID
    agent_name      TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running',  -- running, success, failed, rolled_back
    trigger_type    TEXT NOT NULL,          -- schedule, signal, delegation, manual
    trigger_detail  JSONB DEFAULT '{}',    -- signal ID, cron expression, delegating agent, etc.
    actions_taken   JSONB DEFAULT '[]',    -- [{action, target, result, timestamp}]
    commits         TEXT[] DEFAULT '{}',    -- git commit SHAs
    verification    JSONB DEFAULT '{}',    -- {smoke: pass, benchmark: pass, ...}
    cost_usd        NUMERIC(8,4) DEFAULT 0,
    tokens_used     INTEGER DEFAULT 0,
    error           TEXT,
    learnings       TEXT[]  DEFAULT '{}',  -- extracted patterns for memory
    delegated_to    TEXT[],                 -- agents this run delegated work to
    delegated_from  TEXT                    -- agent that triggered this run (if delegation)
);

CREATE INDEX IF NOT EXISTS idx_runs_agent ON agent_runs (agent_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON agent_runs (status) WHERE status = 'running';

-- ── Task Queue ──────────────────────────────────────────
-- Dynamic task queue fed by signals and manual entries.
-- Replaces static BACKLOG.md for autonomous operations.

CREATE TABLE IF NOT EXISTS task_queue (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    priority        TEXT NOT NULL DEFAULT 'P2',
    task_type       TEXT NOT NULL,          -- fix, investigate, tune, improve, review
    title           TEXT NOT NULL,
    description     TEXT,
    target_agent    TEXT,                   -- preferred agent, NULL = any
    signal_id       BIGINT REFERENCES signals(id),
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending, claimed, running, done, failed, blocked
    claimed_by      TEXT,                   -- agent name
    claimed_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    run_id          TEXT REFERENCES agent_runs(id),
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    cooldown_until  TIMESTAMPTZ,           -- don't retry before this time
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_tasks_pending ON task_queue (priority, created_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON task_queue (target_agent, status);

-- ── Views ───────────────────────────────────────────────

-- Active unresolved signals
CREATE OR REPLACE VIEW v_active_signals AS
SELECT * FROM signals WHERE NOT resolved ORDER BY
    CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
    created_at;

-- Next task for an agent (respects cooldown)
CREATE OR REPLACE VIEW v_next_tasks AS
SELECT * FROM task_queue
WHERE status = 'pending'
  AND (cooldown_until IS NULL OR cooldown_until < NOW())
ORDER BY
    CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
    created_at;

-- Agent run stats (last 24h)
CREATE OR REPLACE VIEW v_agent_stats AS
SELECT
    agent_name,
    COUNT(*) AS total_runs,
    COUNT(*) FILTER (WHERE status = 'success') AS success,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
    COUNT(*) FILTER (WHERE status = 'rolled_back') AS rolled_back,
    ROUND(AVG(cost_usd)::numeric, 4) AS avg_cost,
    ROUND(AVG(tokens_used)::numeric, 0) AS avg_tokens,
    MAX(finished_at) AS last_run
FROM agent_runs
WHERE started_at > NOW() - INTERVAL '24 hours'
GROUP BY agent_name;

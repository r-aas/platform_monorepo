-- YouTube pipeline schema for pgvector
-- Applied to genai-pgvector database

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS yt_videos (
    id              SERIAL PRIMARY KEY,
    video_id        TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    channel         TEXT,
    channel_id      TEXT,
    published_at    DATE,
    duration_seconds INTEGER,
    view_count      INTEGER,
    description     TEXT,
    tags            TEXT[],
    url             TEXT NOT NULL,
    playlist        TEXT,
    thumbnail       TEXT,
    extracted_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS yt_transcripts (
    id              SERIAL PRIMARY KEY,
    video_id        TEXT UNIQUE NOT NULL REFERENCES yt_videos(video_id),
    transcript      TEXT,
    language        TEXT,
    error           TEXT,
    fetched_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS yt_analysis (
    id                    SERIAL PRIMARY KEY,
    video_id              TEXT UNIQUE NOT NULL REFERENCES yt_videos(video_id),
    technologies          TEXT[],
    tools                 TEXT[],
    frameworks            TEXT[],
    relevance_score       REAL,
    integration_potential TEXT CHECK (integration_potential IN ('high', 'medium', 'low', 'none')),
    summary               TEXT,
    key_takeaways         TEXT[],
    platform_relevance    TEXT,
    model_used            TEXT,
    analyzed_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS yt_embeddings (
    id              SERIAL PRIMARY KEY,
    video_id        TEXT UNIQUE NOT NULL REFERENCES yt_videos(video_id),
    embedding       vector(1024),
    model_used      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_yt_videos_playlist ON yt_videos(playlist);
CREATE INDEX IF NOT EXISTS idx_yt_videos_channel ON yt_videos(channel);
CREATE INDEX IF NOT EXISTS idx_yt_analysis_relevance ON yt_analysis(relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_yt_analysis_potential ON yt_analysis(integration_potential);
CREATE INDEX IF NOT EXISTS idx_yt_embeddings_vector ON yt_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- Pipeline run tracking
CREATE TABLE IF NOT EXISTS yt_pipeline_runs (
    id              SERIAL PRIMARY KEY,
    run_id          TEXT UNIQUE NOT NULL,
    playlists       TEXT[],
    total_videos    INTEGER,
    new_videos      INTEGER,
    transcripts_ok  INTEGER,
    analyzed        INTEGER,
    status          TEXT CHECK (status IN ('running', 'completed', 'failed')),
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    mlflow_run_id   TEXT
);

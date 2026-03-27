"""Database schema and connection management."""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from agent_gateway.config import settings

EMBEDDING_DIM = settings.embedding_dim


class Base(DeclarativeBase):
    pass


class AgentRow(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    version = Column(String, nullable=False, default="0.1.0")
    spec = Column(JSON, nullable=False)
    system_prompt = Column(Text)
    capabilities = Column(ARRAY(String), default=[])
    skills = Column(ARRAY(String), default=[])
    runtime = Column(String, default="n8n")
    tags = Column(ARRAY(String), default=[])
    embedding = Column(Vector(EMBEDDING_DIM))
    git_sha = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SkillRow(Base):
    __tablename__ = "skills"

    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    version = Column(String, nullable=False, default="1.0.0")
    description = Column(Text, nullable=False, default="")
    tags = Column(ARRAY(String), default=[])
    capabilities = Column(ARRAY(String), default=[])
    operations = Column(ARRAY(String), default=[])
    manifest = Column(Text, nullable=False)
    advertise = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM))
    git_sha = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EnvironmentBindingRow(Base):
    __tablename__ = "environment_bindings"

    id = Column(String, primary_key=True)
    environment = Column(String, unique=True, nullable=False)
    config = Column(JSON, nullable=False)
    capabilities = Column(JSON, nullable=False)
    llm_config = Column(JSON, nullable=False)
    runtimes = Column(JSON, nullable=False, default={})


class DeploymentRow(Base):
    __tablename__ = "deployments"

    id = Column(String, primary_key=True)
    agent_name = Column(String, nullable=False)
    environment = Column(String, nullable=False)
    gateway_url = Column(String, nullable=False)
    agent_version = Column(String, default="")
    status = Column(String, default="unknown")
    last_heartbeat = Column(DateTime)
    last_invocation = Column(DateTime)
    error_count_1h = Column(Integer, default=0)
    metadata_ = Column("metadata", JSON, default={})

    __table_args__ = (
        UniqueConstraint("agent_name", "environment", "gateway_url"),
    )


class CapabilityRow(Base):
    __tablename__ = "capabilities"

    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, default="")
    operations = Column(JSON, default=[])
    providers = Column(JSON, default=[])
    embedding = Column(Vector(EMBEDDING_DIM))


class EvalRunRow(Base):
    __tablename__ = "eval_runs"

    id = Column(String, primary_key=True)
    agent_name = Column(String, nullable=False)
    agent_version = Column(String, nullable=False)
    environment = Column(String, nullable=False)
    model = Column(String, nullable=False)
    skill = Column(String)
    task = Column(String)
    pass_rate = Column(Float)
    avg_latency_ms = Column(Float)
    results = Column(JSON)
    run_at = Column(DateTime, default=datetime.utcnow)


class McpServerRow(Base):
    __tablename__ = "mcp_servers"

    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    url = Column(String, nullable=False)
    transport = Column(String, default="streamable-http")
    namespace = Column(String, default="default")
    description = Column(Text, default="")
    auth_token = Column(String, default="")
    health_status = Column(String, default="unknown")
    last_health_check = Column(DateTime)
    tools_cache = Column(JSON, default=[])
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create all tables (idempotent) and run lightweight migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Lightweight column migrations — add missing columns to existing tables
    _migrations = [
        ("mcp_servers", "auth_token", "VARCHAR DEFAULT ''"),
    ]
    async with engine.begin() as conn:
        for table, col, col_type in _migrations:
            try:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}")
                )
            except Exception:
                pass  # Column already exists or table doesn't exist

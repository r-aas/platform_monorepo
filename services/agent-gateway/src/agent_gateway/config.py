from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "AGW_"}

    # MLflow (kept for factory/benchmark evals)
    mlflow_tracking_uri: str = "http://genai-mlflow.genai.svc.cluster.local:80"

    # n8n runtime
    n8n_base_url: str = "http://genai-n8n.genai.svc.cluster.local:5678"
    n8n_api_key: str = ""

    # LiteLLM
    litellm_base_url: str = "http://genai-litellm.genai.svc.cluster.local:4000"
    litellm_api_key: str = ""

    # Server
    gateway_port: int = 8000

    # Local file dirs (used during image build for baked-in agent/skill YAMLs)
    agents_dir: str = "agents"
    skills_dir: str = "skills"
    workflows_dir: str = "workflows"

    # Embeddings
    ollama_base_url: str = "http://192.168.5.2:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # Gateway MCP identity
    gateway_mcp_name: str = "agent-gateway"
    gateway_mcp_url: str = "http://genai-agent-gateway.genai.svc.cluster.local:8000/gateway-mcp"

    # PostgreSQL (primary backing store)
    database_url: str = "postgresql+asyncpg://pgvector:pgvector@genai-pgvector:5432/agent_registry"

    # External URL (for A2A agent cards)
    gateway_external_url: str = "http://agent-gateway.genai.127.0.0.1.nip.io"

    # A2A protocol
    a2a_protocol_version: str = "0.2.5"


settings = Settings()

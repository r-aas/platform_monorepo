from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "AGW_"}

    mlflow_tracking_uri: str = "http://genai-mlflow.genai.svc.cluster.local:80"
    n8n_base_url: str = "http://genai-n8n.genai.svc.cluster.local:5678"
    n8n_api_key: str = ""
    litellm_base_url: str = "http://genai-litellm.genai.svc.cluster.local:4000"
    litellm_api_key: str = ""
    gateway_port: int = 8000
    agents_dir: str = "agents"
    skills_dir: str = "skills"
    workflows_dir: str = "workflows"
    ollama_base_url: str = "http://192.168.5.2:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    # MetaMCP admin registration
    metamcp_admin_url: str = "http://genai-metamcp.genai.svc.cluster.local:12009"
    metamcp_user_email: str = ""
    metamcp_user_password: str = ""
    metamcp_namespace: str = "genai"
    gateway_mcp_name: str = "agent-gateway"
    gateway_mcp_url: str = "http://genai-agent-gateway.genai.svc.cluster.local:8000/gateway-mcp"


settings = Settings()

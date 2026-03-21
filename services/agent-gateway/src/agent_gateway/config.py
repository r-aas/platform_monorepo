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


settings = Settings()

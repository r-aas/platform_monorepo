from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    datahub_gms_url: str = "http://datahub-datahub-gms.genai.svc.cluster.local:8080"
    datahub_token: str = ""
    service_port: int = 8000

    model_config = {"env_prefix": ""}


settings = Settings()

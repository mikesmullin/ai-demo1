"""Configuration for chat-back."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8100

    # Provider: xAI
    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"

    # Provider: Copilot
    copilot_api_key: str = ""
    copilot_base_url: str = "https://api.githubcopilot.com"

    # OAuth IDP (for JWT validation)
    idp_jwks_url: str = "http://localhost:9000/.well-known/jwks.json"
    idp_issuer: str = "http://localhost:9000"

    # OTEL
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "chat-back"

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}


settings = Settings()

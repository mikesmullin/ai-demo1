"""Configuration for mcp-gw."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    # OAuth IDP (for JWT validation)
    idp_jwks_url: str = "http://localhost:9000/.well-known/jwks.json"
    idp_issuer: str = "http://localhost:9000"

    # OTEL
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "mcp-gw"

    # Server
    port: int = 8200


settings = Settings()

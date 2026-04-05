"""Configuration for chat-front."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    # chat-back (LLM proxy)
    chat_back_url: str = "http://localhost:8100"
    default_model: str = "xai:grok-4-1-fast-reasoning"

    # mcp-gw
    mcp_gw_url: str = "http://localhost:8200"

    # oauth-idp
    idp_url: str = "http://localhost:9000"
    client_id: str = "chat-front"
    client_secret: str = "chat-front-secret"
    redirect_uri: str = "http://localhost:8300/callback"

    # Server
    port: int = 8300

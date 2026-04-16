"""Configuration for chat-front."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    # Envoy AI Gateway (OpenAI-compatible inference + MCP)
    envoy_base_url: str = "http://localhost:30080"
    envoy_model: str = "gpt-5.1"

    # Prompt to run on startup
    user_prompt: str = "What is the weather like in London, UK?"

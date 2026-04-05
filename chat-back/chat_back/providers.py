"""AI provider routing and abstraction layer.

Model string format: <provider>:<model_name>
Examples:
  - copilot:claude-sonnet-4.6  -> Copilot provider
  - xai:grok-fast-1            -> xAI provider
  - grok-3 (no prefix)         -> defaults to xAI
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import json as _json
import logging

import httpx

from chat_back.config import settings
from chat_back.models import ChatCompletionRequest, ChatCompletionResponse

logger = logging.getLogger(__name__)


# --- Provider base ---


class BaseProvider(ABC):
    """Abstract base for AI providers."""

    name: str
    base_url: str

    @abstractmethod
    async def chat_completion(self, request: ChatCompletionRequest, model: str) -> ChatCompletionResponse:
        ...


# --- xAI Provider ---


class XAIProvider(BaseProvider):
    name = "x_ai"
    base_url = settings.xai_base_url

    async def chat_completion(self, request: ChatCompletionRequest, model: str) -> ChatCompletionResponse:
        return await _proxy_openai_compatible(
            base_url=self.base_url,
            api_key=settings.xai_api_key,
            request=request,
            model=model,
        )


# --- Copilot Provider ---


class CopilotProvider(BaseProvider):
    name = "copilot"
    base_url = settings.copilot_base_url

    async def chat_completion(self, request: ChatCompletionRequest, model: str) -> ChatCompletionResponse:
        return await _proxy_openai_compatible(
            base_url=self.base_url,
            api_key=settings.copilot_api_key,
            request=request,
            model=model,
            extra_headers={
                "Editor-Version": "vscode/1.85.1",
                "Editor-Plugin-Version": "copilot/1.155.0",
                "Copilot-Integration-Id": "vscode-chat",
                "OpenAI-Intent": "conversation-panel",
            },
        )


# --- Provider registry and routing ---

_PROVIDERS: dict[str, type[BaseProvider]] = {
    "xai": XAIProvider,
    "copilot": CopilotProvider,
}

_DEFAULT_PROVIDER = "xai"


def parse_model_string(model_str: str) -> tuple[str, str]:
    """Parse 'provider:model_name' -> (provider_key, model_name).

    If no prefix, defaults to xAI.
    """
    if ":" in model_str:
        parts = model_str.split(":", 1)
        provider_key = parts[0].lower()
        model_name = parts[1].strip()
        return provider_key, model_name
    return _DEFAULT_PROVIDER, model_str


def get_provider(provider_key: str) -> BaseProvider:
    """Get a provider instance by key."""
    cls = _PROVIDERS.get(provider_key)
    if cls is None:
        available = ", ".join(_PROVIDERS.keys())
        raise ValueError(f"Unknown provider: {provider_key}. Available: {available}")
    return cls()


# --- Shared OpenAI-compatible proxy logic ---


async def _proxy_openai_compatible(
    base_url: str,
    api_key: str,
    request: ChatCompletionRequest,
    model: str,
    extra_headers: dict[str, str] | None = None,
) -> ChatCompletionResponse:
    """Forward the request to an OpenAI-compatible API and return the response."""
    url = f"{base_url.rstrip('/')}/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if extra_headers:
        headers.update(extra_headers)

    # Build the outgoing payload
    payload = {
        "model": model,
        "messages": [m.model_dump(exclude_none=True) for m in request.messages],
        "stream": False,
    }
    if request.tools:
        payload["tools"] = [t.model_dump() for t in request.tools]
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.stop is not None:
        payload["stop"] = request.stop

    async with httpx.AsyncClient(timeout=120.0) as client:
        logger.info(">>> %s %s  model=%s  tools=%d  messages=%d",
                     "POST", url, model,
                     len(payload.get("tools", [])),
                     len(payload.get("messages", [])))
        logger.debug(">>> payload: %s", _json.dumps(payload, default=str)[:2000])

        resp = await client.post(url, json=payload, headers=headers)

        logger.info("<<< %s %s  status=%d  len=%d",
                     "POST", url, resp.status_code, len(resp.content))
        if resp.status_code >= 400:
            logger.error("<<< error body: %s", resp.text[:2000])

        resp.raise_for_status()

    return ChatCompletionResponse.model_validate(resp.json())

"""
Smoke tests for chat-back.

Tests provider routing, OpenAI-compatible request/response format,
auth validation, and OTEL tracing attributes.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import respx
import httpx
from fastapi.testclient import TestClient

from chat_back.app import app
from chat_back.auth import clear_jwks_cache, validate_token
from chat_back.providers import parse_model_string


# --- Fixtures ---

@pytest.fixture(autouse=True)
def _clear_caches():
    clear_jwks_cache()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def authed_client():
    """Client with auth dependency overridden."""
    async def _mock_validate_token():
        return {"sub": "test-user-123", "scope": ""}

    app.dependency_overrides[validate_token] = _mock_validate_token
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _mock_upstream_response(model: str = "grok-3") -> dict:
    """A minimal valid OpenAI chat completion response."""
    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! I'm a test response.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "total_tokens": 18,
        },
    }


def _mock_tool_call_response(model: str = "grok-3") -> dict:
    """An upstream response with tool_calls."""
    return {
        "id": "chatcmpl-tool456",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"location": "Paris"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 20,
            "total_tokens": 35,
        },
    }


# --- Unit tests: model parsing ---


class TestModelParsing:
    def test_xai_prefix(self):
        provider, model = parse_model_string("xai:grok-fast-1")
        assert provider == "xai"
        assert model == "grok-fast-1"

    def test_copilot_prefix(self):
        provider, model = parse_model_string("copilot:claude-sonnet-4.6")
        assert provider == "copilot"
        assert model == "claude-sonnet-4.6"

    def test_no_prefix_defaults_to_xai(self):
        provider, model = parse_model_string("grok-3")
        assert provider == "xai"
        assert model == "grok-3"

    def test_case_insensitive_provider(self):
        provider, model = parse_model_string("COPILOT:gpt-4")
        assert provider == "copilot"
        assert model == "gpt-4"


# --- Unit tests: health ---


class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_list_models(self, client):
        r = client.get("/v1/models")
        assert r.status_code == 200
        data = r.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 2


# --- Integration tests: auth enforcement ---


class TestAuth:
    def test_no_token_rejected(self, client):
        r = client.post("/v1/chat/completions", json={
            "model": "xai:grok-3",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert r.status_code == 401

    @respx.mock
    def test_bad_token_rejected(self, client):
        # Mock JWKS endpoint so auth can attempt validation
        respx.get("http://localhost:9000/.well-known/jwks.json").mock(
            return_value=httpx.Response(200, json={"keys": []})
        )
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "xai:grok-3",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"Authorization": "Bearer garbage-token"},
        )
        assert r.status_code == 401


# --- Integration tests: proxy with mocked upstream ---


class TestChatCompletions:
    """Test the full inference proxy path with mocked upstream + mocked auth."""

    @respx.mock
    def test_xai_proxy(self, authed_client):
        # Mock the upstream xAI endpoint
        respx.post("https://api.x.ai/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_mock_upstream_response("grok-3"))
        )

        r = authed_client.post(
            "/v1/chat/completions",
            json={
                "model": "xai:grok-3",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer mock-token"},
        )

        assert r.status_code == 200
        data = r.json()
        assert data["object"] == "chat.completion"
        assert data["model"] == "grok-3"
        assert data["choices"][0]["message"]["content"] == "Hello! I'm a test response."
        assert data["usage"]["total_tokens"] == 18

    @respx.mock
    def test_copilot_proxy(self, authed_client):
        respx.post("https://api.githubcopilot.com/chat/completions").mock(
            return_value=httpx.Response(200, json=_mock_upstream_response("claude-sonnet-4.6"))
        )

        r = authed_client.post(
            "/v1/chat/completions",
            json={
                "model": "copilot:claude-sonnet-4.6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer mock-token"},
        )

        assert r.status_code == 200
        assert r.json()["model"] == "claude-sonnet-4.6"

    @respx.mock
    def test_tool_call_response(self, authed_client):
        respx.post("https://api.x.ai/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_mock_tool_call_response("grok-3"))
        )

        r = authed_client.post(
            "/v1/chat/completions",
            json={
                "model": "xai:grok-3",
                "messages": [{"role": "user", "content": "What's the weather?"}],
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get weather for a location",
                        "parameters": {
                            "type": "object",
                            "properties": {"location": {"type": "string"}},
                            "required": ["location"],
                        },
                    },
                }],
            },
            headers={"Authorization": "Bearer mock-token"},
        )

        assert r.status_code == 200
        data = r.json()
        assert data["choices"][0]["finish_reason"] == "tool_calls"
        tool_calls = data["choices"][0]["message"]["tool_calls"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "get_weather"

    def test_unknown_provider(self, authed_client):
        r = authed_client.post(
            "/v1/chat/completions",
            json={
                "model": "badprovider:model-x",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"Authorization": "Bearer mock-token"},
        )
        assert r.status_code == 400
        assert "Unknown provider" in r.json()["detail"]

    @respx.mock
    def test_default_provider_no_prefix(self, authed_client):
        respx.post("https://api.x.ai/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_mock_upstream_response("grok-3"))
        )

        r = authed_client.post(
            "/v1/chat/completions",
            json={
                "model": "grok-3",
                "messages": [{"role": "user", "content": "no prefix"}],
            },
            headers={"Authorization": "Bearer mock-token"},
        )

        assert r.status_code == 200
        assert r.json()["model"] == "grok-3"

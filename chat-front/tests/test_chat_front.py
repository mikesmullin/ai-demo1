"""Tests for chat-front."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from chat_front.app import app, settings


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ── Health ───────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── OAuth unit tests ────────────────────────────────────────────────

@pytest.mark.anyio
async def test_login_endpoint_failure(client):
    """Login should fail gracefully when IDP is not available."""
    r = await client.post("/login", json={
        "username": "testuser",
        "password": "testpass",
    })
    # IDP not running → should get 400
    assert r.status_code == 400


# ── Chat endpoint (mocked LLM) ──────────────────────────────────────

@pytest.mark.anyio
async def test_chat_endpoint_mocked():
    """Test /chat with a mocked pydantic-ai agent run."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Mock agent.run to avoid needing a real LLM
        mock_result = AsyncMock()
        mock_result.output = "The weather in London is sunny and 20°C."

        with patch("chat_front.app.agent") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            r = await client.post("/chat", json={
                "message": "What's the weather in London?",
                "access_token": "fake-token",
            })
            assert r.status_code == 200
            body = r.json()
            assert "sunny" in body["reply"].lower() or "weather" in body["reply"].lower() or "London" in body["reply"]

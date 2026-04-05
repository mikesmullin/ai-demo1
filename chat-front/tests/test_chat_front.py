"""Tests for chat-front."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from chat_front.app import app, settings
from chat_front.mcp_bridge import McpToolBridge


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


# ── MCP Bridge unit tests ───────────────────────────────────────────

@pytest.mark.anyio
async def test_mcp_bridge_list_tools():
    """Test McpToolBridge.list_tools with mocked HTTP."""
    import respx
    import httpx

    mock_tools = [{"name": "get_weather", "description": "Get weather"}]
    with respx.mock:
        respx.get("http://fake-mcp:8200/tools").mock(
            return_value=httpx.Response(200, json={"tools": mock_tools})
        )
        bridge = McpToolBridge(mcp_gw_url="http://fake-mcp:8200")
        tools = await bridge.list_tools()
        assert tools == mock_tools


@pytest.mark.anyio
async def test_mcp_bridge_call_tool():
    """Test McpToolBridge.call_tool with mocked HTTP."""
    import respx
    import httpx

    with respx.mock:
        respx.post("http://fake-mcp:8200/tools/call").mock(
            return_value=httpx.Response(200, json={"result": {"lat": 1.0, "lng": 2.0}})
        )
        bridge = McpToolBridge(mcp_gw_url="http://fake-mcp:8200")
        result = await bridge.call_tool("get_lat_lng", {"location_description": "NYC"})
        assert result == {"lat": 1.0, "lng": 2.0}


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


# ── Agent tool tests ────────────────────────────────────────────────

@pytest.mark.anyio
async def test_agent_get_lat_lng_tool():
    """Test get_lat_lng tool function directly."""
    from chat_front.agent import get_lat_lng, Deps
    from unittest.mock import MagicMock

    mock_mcp = AsyncMock(spec=McpToolBridge)
    mock_mcp.call_tool.return_value = {"lat": 51.5, "lng": -0.12}

    deps = Deps(access_token="test", mcp=mock_mcp)
    ctx = MagicMock()
    ctx.deps = deps

    result = await get_lat_lng(ctx, location_description="London, UK")
    assert "51.5" in result
    assert "-0.12" in result
    mock_mcp.call_tool.assert_called_once_with(
        "get_lat_lng", {"location_description": "London, UK"}
    )


@pytest.mark.anyio
async def test_agent_get_weather_tool():
    """Test get_weather tool function directly."""
    from chat_front.agent import get_weather, Deps
    from unittest.mock import MagicMock

    mock_mcp = AsyncMock(spec=McpToolBridge)
    mock_mcp.call_tool.return_value = {
        "temperature": "20 °C",
        "description": "sunny",
        "humidity": "45%",
        "wind_speed": "10 km/h",
    }

    deps = Deps(access_token="test", mcp=mock_mcp)
    ctx = MagicMock()
    ctx.deps = deps

    result = await get_weather(ctx, lat=51.5, lng=-0.12)
    assert "20 °C" in result
    assert "sunny" in result
    mock_mcp.call_tool.assert_called_once_with(
        "get_weather", {"lat": 51.5, "lng": -0.12}
    )

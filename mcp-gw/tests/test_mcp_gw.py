"""Tests for mcp-gw."""

import pytest
from httpx import ASGITransport, AsyncClient

from mcp_gw.app import app
from mcp_gw.tools import call_get_lat_lng, call_get_weather, execute_tool


# ── Unit tests for tools ─────────────────────────────────────────────

def test_get_lat_lng_deterministic():
    r1 = call_get_lat_lng({"location_description": "London, UK"})
    r2 = call_get_lat_lng({"location_description": "London, UK"})
    assert r1 == r2
    assert "lat" in r1 and "lng" in r1


def test_get_lat_lng_varies_by_input():
    r1 = call_get_lat_lng({"location_description": "London, UK"})
    r2 = call_get_lat_lng({"location_description": "Tokyo, Japan"})
    assert r1 != r2


def test_get_weather_deterministic():
    r1 = call_get_weather({"lat": 51.5, "lng": -0.12})
    r2 = call_get_weather({"lat": 51.5, "lng": -0.12})
    assert r1 == r2
    assert "temperature" in r1 and "description" in r1


def test_execute_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        execute_tool("no_such_tool", {})


# ── API tests (async with httpx) ────────────────────────────────────

@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.anyio
async def test_rest_list_tools(client):
    r = await client.get("/tools")
    assert r.status_code == 200
    tools = r.json()["tools"]
    names = {t["name"] for t in tools}
    assert "get_lat_lng" in names
    assert "get_weather" in names


@pytest.mark.anyio
async def test_rest_call_tool(client):
    r = await client.post("/tools/call", json={
        "name": "get_lat_lng",
        "arguments": {"location_description": "Paris, France"},
    })
    assert r.status_code == 200
    result = r.json()["result"]
    assert "lat" in result and "lng" in result


@pytest.mark.anyio
async def test_rest_call_unknown_tool(client):
    r = await client.post("/tools/call", json={
        "name": "not_real",
        "arguments": {},
    })
    assert r.status_code == 400


# ── Native MCP transport tests ──────────────────────────────────────

def test_mcp_app_has_mcp_route():
    """Verify the FastMCP app has /mcp route."""
    from mcp_gw.app import app
    route_paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/mcp" in route_paths

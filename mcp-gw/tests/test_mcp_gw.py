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


# ── MCP JSON-RPC tests ──────────────────────────────────────────────

def _rpc(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


@pytest.mark.anyio
async def test_mcp_initialize(client):
    r = await client.post("/mcp", json=_rpc("initialize"))
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["protocolVersion"] == "2024-11-05"
    assert body["result"]["serverInfo"]["name"] == "mcp-gw"


@pytest.mark.anyio
async def test_mcp_tools_list(client):
    r = await client.post("/mcp", json=_rpc("tools/list"))
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert len(tools) == 2


@pytest.mark.anyio
async def test_mcp_tools_call(client):
    r = await client.post("/mcp", json=_rpc("tools/call", {
        "name": "get_weather",
        "arguments": {"lat": 48.8, "lng": 2.35},
    }))
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    content = body["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"


@pytest.mark.anyio
async def test_mcp_unknown_method(client):
    r = await client.post("/mcp", json=_rpc("bogus/method"))
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None
    assert body["error"]["code"] == -32602


@pytest.mark.anyio
async def test_mcp_tools_call_missing_name(client):
    r = await client.post("/mcp", json=_rpc("tools/call", {"arguments": {}}))
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None

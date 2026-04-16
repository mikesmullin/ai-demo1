#!/usr/bin/env python3
"""
Integration tests for the Envoy AI Gateway lab.

Requires the KIND cluster (ai-gw-lab) running with Envoy AI Gateway,
mcp-server, oauth-idp, and Azure AI Foundry configured. Tests target
Envoy at localhost:30080 (NodePort) and oauth-idp at localhost:30300.

Uses only stdlib — no pip install needed.

Usage:
    python3 tests/test_integration.py
"""

import json
import sys
import urllib.parse
import urllib.request
import urllib.error

ENVOY_URL = "http://localhost:30080"
IDP_URL = "http://localhost:30300"

passed = 0
failed = 0


def req(method, url, data=None, headers=None, json_body=None):
    """Minimal HTTP helper using only stdlib."""
    hdrs = headers or {}
    body = None

    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()

    r = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    opener = urllib.request.build_opener()

    try:
        resp = opener.open(r, timeout=60)
        return resp.status, resp.read().decode(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body_text = ""
        if e.fp:
            try:
                body_text = e.fp.read().decode()
            except Exception:
                pass
        return e.code, body_text, dict(e.headers)


def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  ✓ {name}")
        passed += 1
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        failed += 1


def _parse_sse_json(body):
    """Extract JSON from an SSE event stream body."""
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    # Try parsing as plain JSON (some responses are not SSE)
    return json.loads(body)


# ─── State shared across tests ──────────────────────────────────────

state = {}


def _get_token():
    """Mint a test token from the oauth-idp /admin/token endpoint."""
    code, body, _ = req("POST", f"{IDP_URL}/admin/token",
        json_body={"sub": "integration-test-user"})
    assert code == 200, f"Failed to mint token: {code} {body[:200]}"
    return json.loads(body)["access_token"]


def _auth(token):
    """Return Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}


# ─── 0. Auth enforcement tests ──────────────────────────────────────

def test_inference_requires_token():
    """Inference without token must be rejected (401)."""
    code, body, _ = req("POST", f"{ENVOY_URL}/v1/chat/completions",
        json_body={
            "model": "gpt-5.1",
            "messages": [{"role": "user", "content": "hi"}],
            "max_completion_tokens": 10,
        },
        headers={"x-ai-eg-model": "gpt-5.1"},
    )
    assert code == 401, f"Expected 401, got {code}: {body[:200]}"


def test_mcp_requires_token():
    """MCP without token must be rejected (401)."""
    code, body, _ = req("POST", f"{ENVOY_URL}/mcp",
        json_body={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1.0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert code == 401, f"Expected 401, got {code}: {body[:200]}"


# ─── 1. Inference tests (Azure AI Foundry via Envoy) ────────────────

def test_inference_simple():
    """Basic inference request through Envoy → Azure AI Foundry."""
    token = state["token"]
    code, body, _ = req("POST", f"{ENVOY_URL}/v1/chat/completions",
        json_body={
            "model": "gpt-5.1",
            "messages": [
                {"role": "system", "content": "Respond in exactly one short sentence."},
                {"role": "user", "content": "What is 2+2?"},
            ],
            "max_completion_tokens": 50,
        },
        headers={
            "x-ai-eg-model": "gpt-5.1",
            **_auth(token),
        },
    )
    assert code == 200, f"Expected 200, got {code}: {body[:200]}"
    data = json.loads(body)
    assert data["object"] == "chat.completion"
    assert len(data["choices"]) > 0
    content = data["choices"][0]["message"]["content"]
    assert len(content) > 0, "Empty response content"
    print(f"       LLM response: {content.strip()[:80]}")


def test_inference_with_model_header():
    """Request with x-ai-eg-model header routes to Azure AI Foundry."""
    token = state["token"]
    code, body, _ = req("POST", f"{ENVOY_URL}/v1/chat/completions",
        json_body={
            "model": "gpt-5.1",
            "messages": [{"role": "user", "content": "Say hello in one word."}],
            "max_completion_tokens": 10,
        },
        headers={"x-ai-eg-model": "gpt-5.1", **_auth(token)},
    )
    assert code == 200, f"Expected 200, got {code}: {body[:200]}"
    data = json.loads(body)
    assert len(data["choices"]) > 0


# ─── 2. MCP tests (mcp-server via Envoy MCPRoute) ───────────────────────

def test_mcp_initialize():
    """MCP initialize via Envoy /mcp endpoint."""
    token = state["token"]
    code, body, hdrs = req("POST", f"{ENVOY_URL}/mcp",
        json_body={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "integration-test", "version": "0.1.0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream", **_auth(token)},
    )
    assert code == 200, f"Expected 200, got {code}: {body[:200]}"
    data = _parse_sse_json(body)
    server_name = data.get("result", {}).get("serverInfo", {}).get("name", "")
    assert server_name, f"No serverInfo.name in response: {data}"
    session_id = hdrs.get("Mcp-Session-Id", hdrs.get("mcp-session-id", ""))
    assert session_id, f"No Mcp-Session-Id header: {hdrs}"
    state["mcp_session_id"] = session_id


def test_mcp_tools_list():
    """List tools via MCP Streamable HTTP through Envoy."""
    token = state["token"]
    session_id = state.get("mcp_session_id")
    assert session_id, "No MCP session — initialize test must pass first"

    # Send initialized notification
    req("POST", f"{ENVOY_URL}/mcp",
        json_body={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Mcp-Session-Id": session_id, **_auth(token)},
    )

    # List tools
    code, body, _ = req("POST", f"{ENVOY_URL}/mcp",
        json_body={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers={
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
            **_auth(token),
        },
    )
    assert code == 200, f"Expected 200, got {code}: {body[:200]}"
    data = _parse_sse_json(body)
    tools = data.get("result", {}).get("tools", [])
    names = {t["name"] for t in tools}
    assert "mcp-server__get_lat_lng" in names, f"mcp-server__get_lat_lng not found in: {names}"
    assert "mcp-server__get_weather" in names, f"mcp-server__get_weather not found in: {names}"


def test_mcp_tool_call_get_lat_lng():
    """Call get_lat_lng via MCP through Envoy."""
    token = state["token"]
    session_id = state.get("mcp_session_id")
    assert session_id, "No MCP session"

    code, body, _ = req("POST", f"{ENVOY_URL}/mcp",
        json_body={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "mcp-server__get_lat_lng",
                "arguments": {"location_description": "London, UK"},
            },
        },
        headers={
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
            **_auth(token),
        },
    )
    assert code == 200, f"Expected 200, got {code}: {body[:200]}"
    data = _parse_sse_json(body)
    content = data.get("result", {}).get("content", [])
    assert len(content) > 0, f"Empty content: {data}"
    text = content[0].get("text", "")
    result = json.loads(text)
    assert "lat" in result and "lng" in result, f"Missing lat/lng: {result}"
    state["lat"] = result["lat"]
    state["lng"] = result["lng"]
    print(f"       get_lat_lng → lat={result['lat']}, lng={result['lng']}")


def test_mcp_tool_call_get_weather():
    """Call get_weather via MCP through Envoy."""
    token = state["token"]
    session_id = state.get("mcp_session_id")
    assert session_id, "No MCP session"

    lat = state.get("lat", 51.5)
    lng = state.get("lng", -0.12)

    code, body, _ = req("POST", f"{ENVOY_URL}/mcp",
        json_body={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "mcp-server__get_weather",
                "arguments": {"lat": lat, "lng": lng},
            },
        },
        headers={
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
            **_auth(token),
        },
    )
    assert code == 200, f"Expected 200, got {code}: {body[:200]}"
    data = _parse_sse_json(body)
    content = data.get("result", {}).get("content", [])
    assert len(content) > 0, f"Empty content: {data}"
    text = content[0].get("text", "")
    result = json.loads(text)
    assert "temperature" in result, f"Missing temperature: {result}"
    assert "description" in result, f"Missing description: {result}"
    print(f"       get_weather → {result['temperature']}, {result['description']}")


# ─── Runner ──────────────────────────────────────────────────────────

def main():
    print()
    print("═══ Auth enforcement tests ═══")
    test("inference rejects missing token (401)", test_inference_requires_token)
    test("MCP rejects missing token (401)", test_mcp_requires_token)

    # Mint a token for remaining tests
    print()
    print("    Minting test token from oauth-idp ...")
    state["token"] = _get_token()
    print("    ✓ Token acquired")

    print()
    print("═══ Inference tests (Envoy → Azure AI Foundry) ═══")
    test("simple inference (gpt-5.1)", test_inference_simple)
    test("inference with model header", test_inference_with_model_header)

    print()
    print("═══ MCP tests (Envoy → mcp-server) ═══")
    test("MCP initialize", test_mcp_initialize)
    test("MCP tools/list", test_mcp_tools_list)
    test("MCP tools/call get_lat_lng", test_mcp_tool_call_get_lat_lng)
    test("MCP tools/call get_weather", test_mcp_tool_call_get_weather)

    print()
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

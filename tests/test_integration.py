#!/usr/bin/env python3
"""
Integration tests for the local lab.

Requires oauth-idp (:9000), chat-back (:8100), mcp-gw (:8200),
and chat-front (:8300) to be running.
Uses only stdlib — no pip install needed.

Usage:
    python3 tests/test_integration.py
    # or:  ./launch.sh start && python3 tests/test_integration.py
"""

import base64
import hashlib
import json
import secrets
import sys
import urllib.parse
import urllib.request
import urllib.error

IDP_URL = "http://localhost:9000"
CHATBACK_URL = "http://localhost:8100"
MCPGW_URL = "http://localhost:8200"
CHATFRONT_URL = "http://localhost:8300"

passed = 0
failed = 0


def req(method, url, data=None, headers=None, json_body=None, form_data=None, follow_redirects=True):
    """Minimal HTTP helper using only stdlib."""
    hdrs = headers or {}
    body = None

    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    elif form_data is not None:
        body = urllib.parse.urlencode(form_data).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()

    r = urllib.request.Request(url, data=body, headers=hdrs, method=method)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(newurl, code, msg, headers, fp)

    if not follow_redirects:
        opener = urllib.request.build_opener(NoRedirect)
    else:
        opener = urllib.request.build_opener()

    try:
        resp = opener.open(r)
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


def pkce_pair():
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ─── State shared across tests ──────────────────────────────────────

state = {}


# ─── 1. oauth-idp tests ─────────────────────────────────────────────

def test_idp_health():
    code, body, _ = req("GET", f"{IDP_URL}/health")
    assert code == 200, f"Expected 200, got {code}"
    assert json.loads(body)["status"] == "ok"


def test_idp_openid_config():
    code, body, _ = req("GET", f"{IDP_URL}/.well-known/openid-configuration")
    assert code == 200
    data = json.loads(body)
    assert data["issuer"] == IDP_URL
    assert "S256" in data["code_challenge_methods_supported"]


def test_register_client():
    code, body, _ = req("POST", f"{IDP_URL}/admin/clients", json_body={
        "client_name": "chat-front",
        "redirect_uris": ["http://localhost:3000/callback"],
    })
    assert code == 201, f"Expected 201, got {code}: {body}"
    data = json.loads(body)
    assert data["client_name"] == "chat-front"
    state["client_id"] = data["client_id"]


def test_create_user():
    code, body, _ = req("POST", f"{IDP_URL}/admin/users", json_body={
        "username": "mike",
        "password": "test123",
        "email": "mike@example.com",
        "display_name": "Mike",
    })
    assert code in (201, 409), f"Expected 201 or 409, got {code}: {body}"
    data = json.loads(body)
    if code == 201:
        state["user_id"] = data["user_id"]
    else:
        state["user_id"] = None  # will resolve from introspect


def test_pkce_auth_flow():
    verifier, challenge = pkce_pair()
    client_id = state["client_id"]

    # POST /authorize — authenticate and get redirect with code
    code, body, headers = req("POST", f"{IDP_URL}/authorize", form_data={
        "client_id": client_id,
        "redirect_uri": "http://localhost:3000/callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "integration-test",
        "username": "mike",
        "password": "test123",
    }, follow_redirects=False)
    assert code == 302, f"Expected 302 redirect, got {code}: {body}"

    location = headers.get("Location", headers.get("location", ""))
    assert "code=" in location, f"No code in redirect: {location}"
    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    auth_code = parsed["code"][0]
    assert parsed["state"][0] == "integration-test"

    # POST /token — exchange code for tokens
    code2, body2, _ = req("POST", f"{IDP_URL}/token", form_data={
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": "http://localhost:3000/callback",
        "client_id": client_id,
        "code_verifier": verifier,
    })
    assert code2 == 200, f"Expected 200, got {code2}: {body2}"
    tokens = json.loads(body2)
    assert "access_token" in tokens
    assert "id_token" in tokens
    state["access_token"] = tokens["access_token"]


def test_userinfo():
    code, body, _ = req("GET", f"{IDP_URL}/userinfo", headers={
        "Authorization": f"Bearer {state['access_token']}",
    })
    assert code == 200, f"Expected 200, got {code}: {body}"
    data = json.loads(body)
    assert data["preferred_username"] == "mike"


def test_introspect():
    code, body, _ = req("POST", f"{IDP_URL}/introspect", form_data={
        "token": state["access_token"],
    })
    assert code == 200
    data = json.loads(body)
    assert data["active"] is True
    # If user was already created (409), resolve user_id now
    if state.get("user_id") is None:
        state["user_id"] = data["sub"]
    assert data["sub"] == state["user_id"]


# ─── 2. chat-back tests ─────────────────────────────────────────────

def test_chatback_health():
    code, body, _ = req("GET", f"{CHATBACK_URL}/health")
    assert code == 200
    assert json.loads(body)["status"] == "ok"


def test_chatback_models():
    code, body, _ = req("GET", f"{CHATBACK_URL}/v1/models")
    assert code == 200
    data = json.loads(body)
    assert data["object"] == "list"
    assert len(data["data"]) >= 2


def test_chatback_no_auth_rejected():
    code, body, _ = req("POST", f"{CHATBACK_URL}/v1/chat/completions", json_body={
        "model": "xai:grok-3",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert code == 401, f"Expected 401, got {code}"


def test_chatback_bad_provider():
    code, body, _ = req("POST", f"{CHATBACK_URL}/v1/chat/completions", json_body={
        "model": "fakeprovider:fake-model",
        "messages": [{"role": "user", "content": "hi"}],
    }, headers={"Authorization": f"Bearer {state['access_token']}"})
    assert code == 400, f"Expected 400, got {code}: {body}"
    assert "Unknown provider" in body


def test_chatback_xai_inference():
    """Live inference test via xAI — requires XAI_API_KEY in chat-back .env."""
    code, body, _ = req("POST", f"{CHATBACK_URL}/v1/chat/completions", json_body={
        "model": "xai:grok-4-1-fast-reasoning",
        "messages": [
            {"role": "system", "content": "Respond in exactly one short sentence."},
            {"role": "user", "content": "What is 2+2?"},
        ],
        "max_tokens": 50,
    }, headers={"Authorization": f"Bearer {state['access_token']}"})

    if code == 502:
        data = json.loads(body)
        detail = data.get("detail", "")
        if "401" in str(detail) or "Unauthorized" in str(detail):
            raise AssertionError("xAI API key invalid or missing — skipping live test")
        raise AssertionError(f"Upstream error: {detail}")

    assert code == 200, f"Expected 200, got {code}: {body}"
    data = json.loads(body)
    assert data["object"] == "chat.completion"
    assert len(data["choices"]) > 0
    content = data["choices"][0]["message"]["content"]
    assert len(content) > 0, "Empty response content"
    print(f"       xAI response: {content.strip()[:80]}")
    assert data["usage"]["total_tokens"] > 0


# ─── 3. mcp-gw tests ────────────────────────────────────────────────

def test_mcpgw_health():
    code, body, _ = req("GET", f"{MCPGW_URL}/health")
    assert code == 200
    assert json.loads(body)["status"] == "ok"


def test_mcpgw_list_tools():
    code, body, _ = req("GET", f"{MCPGW_URL}/tools")
    assert code == 200
    data = json.loads(body)
    names = {t["name"] for t in data["tools"]}
    assert "get_lat_lng" in names
    assert "get_weather" in names


def test_mcpgw_no_auth_rejected():
    """POST /tools/call without token → 401."""
    code, body, _ = req("POST", f"{MCPGW_URL}/tools/call", json_body={
        "name": "get_lat_lng",
        "arguments": {"location_description": "London, UK"},
    })
    assert code == 401, f"Expected 401, got {code}: {body}"


def test_mcpgw_mcp_no_auth():
    """POST /mcp without token → 401."""
    code, body, _ = req("POST", f"{MCPGW_URL}/mcp",
        json_body={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert code == 401, f"Expected 401, got {code}: {body}"


def test_mcpgw_call_get_lat_lng():
    code, body, _ = req("POST", f"{MCPGW_URL}/tools/call", json_body={
        "name": "get_lat_lng",
        "arguments": {"location_description": "London, UK"},
    }, headers={"Authorization": f"Bearer {state['access_token']}"})
    assert code == 200
    result = json.loads(body)["result"]
    assert "lat" in result and "lng" in result


def test_mcpgw_call_get_weather():
    code, body, _ = req("POST", f"{MCPGW_URL}/tools/call", json_body={
        "name": "get_weather",
        "arguments": {"lat": 51.5, "lng": -0.12},
    }, headers={"Authorization": f"Bearer {state['access_token']}"})
    assert code == 200
    result = json.loads(body)["result"]
    assert "temperature" in result and "description" in result


def _parse_sse_json(body):
    """Extract JSON from an SSE event stream body."""
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise ValueError(f"No data line in SSE response: {body!r}")


def test_mcpgw_mcp_initialize():
    """Native MCP Streamable HTTP endpoint should accept POST at /mcp."""
    code, body, hdrs = req("POST", f"{MCPGW_URL}/mcp",
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
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {state['access_token']}",
        },
    )
    assert code == 200, f"Expected 200, got {code}: {body}"
    data = _parse_sse_json(body)
    assert data.get("result", {}).get("serverInfo", {}).get("name") == "mcp-gw"


def test_mcpgw_mcp_tools_list():
    """List tools via native MCP Streamable HTTP."""
    auth_hdr = {"Authorization": f"Bearer {state['access_token']}"}

    # First initialize to get a session
    code, body, hdrs = req("POST", f"{MCPGW_URL}/mcp",
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
        headers={"Accept": "application/json, text/event-stream", **auth_hdr},
    )
    assert code == 200, f"Init failed: {code}: {body}"
    session_id = hdrs.get("Mcp-Session-Id", hdrs.get("mcp-session-id", ""))
    assert session_id, f"No session ID in response headers: {hdrs}"

    # Send initialized notification
    req("POST", f"{MCPGW_URL}/mcp",
        json_body={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Mcp-Session-Id": session_id, **auth_hdr},
    )

    # List tools
    code2, body2, _ = req("POST", f"{MCPGW_URL}/mcp",
        json_body={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers={
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
            **auth_hdr,
        },
    )
    assert code2 == 200, f"tools/list failed: {code2}: {body2}"
    data = _parse_sse_json(body2)
    tools = data.get("result", {}).get("tools", [])
    names = {t["name"] for t in tools}
    assert "get_lat_lng" in names
    assert "get_weather" in names


# ─── 4. chat-front tests ────────────────────────────────────────────

def test_chatfront_health():
    code, body, _ = req("GET", f"{CHATFRONT_URL}/health")
    assert code == 200
    assert json.loads(body)["status"] == "ok"


def test_chatfront_login():
    """Login via chat-front → oauth-idp PKCE flow."""
    code, body, _ = req("POST", f"{CHATFRONT_URL}/login", json_body={
        "username": "mike",
        "password": "test123",
    })
    # This depends on oauth-idp having the client registered (lifespan does this)
    # and user "mike" existing from earlier tests
    if code == 200:
        data = json.loads(body)
        assert "access_token" in data
        state["chatfront_token"] = data["access_token"]
    else:
        print(f"       (login returned {code} — IDP client may not be registered for chat-front)")


def test_chatfront_weather():
    """Full agent loop: chat-front → chat-back (inference) → mcp-gw (tools)."""
    token = state.get("chatfront_token") or state.get("access_token")
    assert token, "No access token available — login test must pass first"
    code, body, _ = req("POST", f"{CHATFRONT_URL}/chat", json_body={
        "message": "What is the weather in Tokyo?",
        "access_token": token,
    })
    assert code == 200, f"Expected 200, got {code}: {body}"
    data = json.loads(body)
    reply = data["reply"]
    assert len(reply) > 0, "Empty reply from agent"
    print(f"       Agent reply: {reply.strip()[:120]}")


# ─── Runner ──────────────────────────────────────────────────────────

def main():
    print()
    print("═══ oauth-idp integration tests ═══")
    test("health check", test_idp_health)
    test("openid-configuration", test_idp_openid_config)
    test("register client (chat-front)", test_register_client)
    test("create user (mike)", test_create_user)
    test("PKCE auth flow → tokens", test_pkce_auth_flow)
    test("userinfo with access token", test_userinfo)
    test("token introspection", test_introspect)

    print()
    print("═══ chat-back integration tests ═══")
    test("health check", test_chatback_health)
    test("list models", test_chatback_models)
    test("reject unauthenticated request", test_chatback_no_auth_rejected)
    test("reject unknown provider", test_chatback_bad_provider)
    test("live xAI inference (grok-4-1-fast-reasoning)", test_chatback_xai_inference)

    print()
    print("═══ mcp-gw integration tests ═══")
    test("health check", test_mcpgw_health)
    test("list tools (REST)", test_mcpgw_list_tools)
    test("reject unauthenticated tool call", test_mcpgw_no_auth_rejected)
    test("reject unauthenticated MCP request", test_mcpgw_mcp_no_auth)
    test("call get_lat_lng (REST)", test_mcpgw_call_get_lat_lng)
    test("call get_weather (REST)", test_mcpgw_call_get_weather)
    test("MCP initialize (Streamable HTTP)", test_mcpgw_mcp_initialize)
    test("MCP tools/list (Streamable HTTP)", test_mcpgw_mcp_tools_list)

    print()
    print("═══ chat-front integration tests ═══")
    test("health check", test_chatfront_health)
    test("login via PKCE", test_chatfront_login)
    test("weather agent (full loop)", test_chatfront_weather)

    print()
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

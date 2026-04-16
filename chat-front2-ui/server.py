"""chat-front2-ui — Browser chat UI with server-side Envoy AI Gateway proxy.

The server:
 1. Serves the static HTML/CSS/JS chat UI
 2. Proxies /api/chat → Envoy AI Gateway /v1/chat/completions
 3. Proxies /api/mcp  → Envoy AI Gateway /mcp
 4. Handles OAuth token acquisition from oauth-idp
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Configuration ────────────────────────────────────────────────────

ENVOY_BASE_URL = os.environ.get("ENVOY_BASE_URL", "http://localhost:30080")
ENVOY_MODEL = os.environ.get("ENVOY_MODEL", "gpt-5.1")
IDP_URL = os.environ.get("IDP_URL", "http://localhost:30300")

# ── HTTP client (shared, connection-pooled) ──────────────────────────

_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(timeout=120.0)
    # Pre-fetch a token from the mock IDP at startup
    await _refresh_token()
    yield
    await _client.aclose()

_token: str = ""


async def _refresh_token() -> str:
    """Mint a fresh token from oauth-idp /admin/token."""
    global _token
    resp = await _client.post(
        f"{IDP_URL}/admin/token",
        json={"sub": "chat-front2-ui", "expires_in": 3600},
    )
    resp.raise_for_status()
    _token = resp.json()["access_token"]
    return _token


# ── App ──────────────────────────────────────────────────────────────

app = FastAPI(title="chat-front2-ui", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: Request):
    """Proxy chat completions to Envoy AI Gateway."""
    body = await request.json()

    # Ensure model and required headers
    body.setdefault("model", ENVOY_MODEL)

    resp = await _client.post(
        f"{ENVOY_BASE_URL}/v1/chat/completions",
        json=body,
        headers={
            "x-ai-eg-model": ENVOY_MODEL,
            "Authorization": f"Bearer {_token}",
            "Content-Type": "application/json",
        },
    )

    if resp.status_code == 401:
        # Token may have expired — refresh and retry once
        await _refresh_token()
        resp = await _client.post(
            f"{ENVOY_BASE_URL}/v1/chat/completions",
            json=body,
            headers={
                "x-ai-eg-model": ENVOY_MODEL,
                "Authorization": f"Bearer {_token}",
                "Content-Type": "application/json",
            },
        )

    return JSONResponse(content=resp.json(), status_code=resp.status_code)


@app.post("/api/mcp")
async def mcp_proxy(request: Request):
    """Proxy MCP JSON-RPC requests to Envoy AI Gateway."""
    body = await request.json()
    headers = {
        "Authorization": f"Bearer {_token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    # Forward Mcp-Session-Id if present
    session_id = request.headers.get("mcp-session-id")
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    resp = await _client.post(
        f"{ENVOY_BASE_URL}/mcp",
        json=body,
        headers=headers,
    )

    # Build response, forwarding Mcp-Session-Id back
    resp_headers = {}
    if "mcp-session-id" in resp.headers:
        resp_headers["Mcp-Session-Id"] = resp.headers["mcp-session-id"]

    # MCP responses may be plain JSON or SSE (event: message\ndata: {...})
    # Notifications return an empty body. Handle all three cases.
    raw = resp.content.strip()
    if not raw:
        content = None
    elif raw.startswith(b"event:") or raw.startswith(b"data:"):
        # SSE: extract the JSON from the first data: line
        content = None
        for line in raw.splitlines():
            if line.startswith(b"data:"):
                content = json.loads(line[len(b"data:"):].strip())
                break
    else:
        content = resp.json()

    return JSONResponse(
        content=content,
        status_code=resp.status_code,
        headers=resp_headers,
    )


# ── Static files (HTML/CSS/JS) — mounted last so /api takes priority ─

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

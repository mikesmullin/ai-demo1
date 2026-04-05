"""MCP Gateway — FastMCP server with auth, OTEL tracing, and REST helpers.

Supports:
  - POST /mcp  (MCP Streamable HTTP transport via FastMCP — native protocol)
  - GET  /health
  - GET  /tools            (REST convenience, public)
  - POST /tools/call       (REST convenience, auth required)

All tool executions are traced via OpenTelemetry with user attribution.
"""

from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_gw.auth import JWTAuthMiddleware
from mcp_gw.tools import TOOL_DEFINITIONS, execute_tool, mcp_server
from mcp_gw.tracing import setup_tracing


# ── Custom routes on the FastMCP server ──────────────────────────────

@mcp_server.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@mcp_server.custom_route("/tools", methods=["GET"])
async def list_tools(request: Request) -> JSONResponse:
    return JSONResponse({"tools": TOOL_DEFINITIONS})


@mcp_server.custom_route("/tools/call", methods=["POST"])
async def call_tool(request: Request) -> JSONResponse:
    body = await request.json()
    name = body.get("name")
    arguments = body.get("arguments", {})
    if not name:
        return JSONResponse({"detail": "Missing 'name'"}, status_code=400)
    try:
        result = execute_tool(name, arguments)
        return JSONResponse({"result": result})
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)


# ── Build the ASGI app ──────────────────────────────────────────────

# Initialize OTEL before the first request
setup_tracing()

# FastMCP Starlette app (handles /mcp + custom routes)
_inner_app = mcp_server.streamable_http_app()

# Wrap with JWT auth middleware (public paths: /health, /tools)
app = JWTAuthMiddleware(_inner_app)

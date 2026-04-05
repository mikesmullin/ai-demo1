"""MCP Gateway — FastMCP server with custom REST/health routes.

Supports:
  - POST /mcp  (MCP Streamable HTTP transport via FastMCP — native protocol)
  - GET  /health
  - GET  /tools            (REST convenience)
  - POST /tools/call       (REST convenience)
"""

from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_gw.tools import TOOL_DEFINITIONS, execute_tool, mcp_server


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


# The ASGI app served by uvicorn — uses FastMCP's Streamable HTTP transport
app = mcp_server.streamable_http_app()

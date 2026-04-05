"""MCP Gateway — FastAPI server implementing the MCP protocol over HTTP.

Supports:
  - POST /mcp  (JSON-RPC 2.0 endpoint for MCP messages)
  - tools/list  — list available tools
  - tools/call  — execute a tool
  - initialize  — MCP handshake

Also exposes simple REST endpoints for direct tool invocation.
"""

from __future__ import annotations

import json
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mcp_gw.tools import TOOL_DEFINITIONS, execute_tool

app = FastAPI(
    title="mcp-gw",
    version="0.1.0",
    description="MCP server with mock tool implementations",
)


# ── Health ───────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── JSON-RPC 2.0 / MCP endpoint ─────────────────────────────────────

class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict | None = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: dict | list | None = None
    error: dict | None = None


@app.post("/mcp")
def mcp_endpoint(req: JsonRpcRequest) -> JsonRpcResponse:
    """Handle MCP JSON-RPC requests."""
    try:
        result = _handle_mcp_method(req.method, req.params or {})
        return JsonRpcResponse(id=req.id, result=result)
    except ValueError as e:
        return JsonRpcResponse(
            id=req.id,
            error={"code": -32602, "message": str(e)},
        )
    except Exception as e:
        return JsonRpcResponse(
            id=req.id,
            error={"code": -32603, "message": f"Internal error: {e}"},
        )


def _handle_mcp_method(method: str, params: dict) -> dict | list:
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": "mcp-gw",
                "version": "0.1.0",
            },
        }

    if method == "notifications/initialized":
        return {}

    if method == "tools/list":
        return {"tools": TOOL_DEFINITIONS}

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not tool_name:
            raise ValueError("Missing 'name' in tools/call params")
        result = execute_tool(tool_name, arguments)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result),
                }
            ],
        }

    raise ValueError(f"Unknown method: {method}")


# ── REST convenience endpoints ───────────────────────────────────────

@app.get("/tools")
def list_tools():
    """List available tools (REST)."""
    return {"tools": TOOL_DEFINITIONS}


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict = {}


@app.post("/tools/call")
def call_tool(req: ToolCallRequest):
    """Call a tool directly (REST)."""
    try:
        result = execute_tool(req.name, req.arguments)
        return {"result": result}
    except ValueError as e:
        raise HTTPException(400, str(e))

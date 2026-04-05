"""MCP tool bridge — discovers and wraps mcp-gw tools for Pydantic AI."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx


@dataclass
class McpToolBridge:
    """Bridges mcp-gw REST endpoints into callable functions."""

    mcp_gw_url: str
    _tools: list[dict] | None = None

    async def list_tools(self) -> list[dict]:
        """Fetch tool definitions from mcp-gw."""
        if self._tools is None:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{self.mcp_gw_url}/tools")
                r.raise_for_status()
                self._tools = r.json()["tools"]
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Execute a tool on mcp-gw and return the result."""
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.mcp_gw_url}/tools/call",
                json={"name": name, "arguments": arguments},
            )
            r.raise_for_status()
            return r.json()["result"]

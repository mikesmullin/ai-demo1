"""Pydantic AI agent — uses chat-back as LLM backend, mcp-gw for tools via native MCP."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent


@dataclass
class Deps:
    access_token: str


agent = Agent(
    system_prompt=(
        "You are a helpful assistant. You have access to tools for looking up "
        "locations and weather. Use them when the user asks about weather."
    ),
    deps_type=Deps,
)

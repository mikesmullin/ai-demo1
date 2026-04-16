"""Pydantic AI agent — uses Envoy AI Gateway for inference and MCP tools."""

from __future__ import annotations

from pydantic_ai import Agent

agent = Agent(
    instructions=(
        "You are a helpful assistant. You have access to tools for looking up "
        "locations and weather. When asked about weather, ALWAYS use the tools: "
        "first call get_lat_lng to geocode the location, then call get_weather "
        "with the returned coordinates. Report the result to the user."
    ),
)

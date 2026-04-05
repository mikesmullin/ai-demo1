"""Pydantic AI agent — uses chat-back as LLM backend, mcp-gw for tools."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent, RunContext

from chat_front.mcp_bridge import McpToolBridge


@dataclass
class Deps:
    access_token: str
    mcp: McpToolBridge


agent = Agent(
    system_prompt=(
        "You are a helpful assistant. You have access to tools for looking up "
        "locations and weather. Use them when the user asks about weather."
    ),
    deps_type=Deps,
)


@agent.tool
async def get_lat_lng(ctx: RunContext[Deps], location_description: str) -> str:
    """Get the latitude and longitude of a location."""
    result = await ctx.deps.mcp.call_tool("get_lat_lng", {
        "location_description": location_description,
    })
    return f"lat={result['lat']}, lng={result['lng']}"


@agent.tool
async def get_weather(ctx: RunContext[Deps], lat: float, lng: float) -> str:
    """Get the current weather at a location given latitude and longitude."""
    result = await ctx.deps.mcp.call_tool("get_weather", {
        "lat": lat,
        "lng": lng,
    })
    return f"{result['temperature']}, {result['description']}, humidity {result['humidity']}, wind {result['wind_speed']}"

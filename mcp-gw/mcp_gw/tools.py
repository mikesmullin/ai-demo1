"""Mock tool implementations for the MCP gateway.

These return deterministic fake data so the lab works without external APIs.
Tools are registered with both FastMCP (native MCP transport) and a plain
dispatch dict (REST convenience endpoints).
"""

from __future__ import annotations

import hashlib
import json
import random

from mcp.server.fastmcp import FastMCP

mcp_server = FastMCP("mcp-gw")

# ── Helpers ──────────────────────────────────────────────────────────


def _seeded_random(seed_str: str) -> random.Random:
    """Create a deterministic Random from a string seed."""
    h = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    return random.Random(h)


_WEATHER_CONDITIONS = [
    "sunny", "partly cloudy", "overcast", "light rain",
    "heavy rain", "thunderstorms", "snow", "foggy", "windy", "clear skies",
]

# ── Tool definitions (kept for REST /tools endpoint) ─────────────────

TOOL_DEFINITIONS = [
    {
        "name": "get_lat_lng",
        "description": "Get the latitude and longitude of a location.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "location_description": {
                    "type": "string",
                    "description": "A description of a location, e.g. 'London, UK'.",
                },
            },
            "required": ["location_description"],
        },
    },
    {
        "name": "get_weather",
        "description": "Get the current weather at a location given latitude and longitude.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude"},
                "lng": {"type": "number", "description": "Longitude"},
            },
            "required": ["lat", "lng"],
        },
    },
]

# ── Tool implementations (registered with FastMCP) ───────────────────


@mcp_server.tool()
def get_lat_lng(location_description: str) -> str:
    """Get the latitude and longitude of a location."""
    result = call_get_lat_lng({"location_description": location_description})
    return json.dumps(result)


@mcp_server.tool()
def get_weather(lat: float, lng: float) -> str:
    """Get the current weather at a location given latitude and longitude."""
    result = call_get_weather({"lat": lat, "lng": lng})
    return json.dumps(result)


# ── Raw implementations (used by REST endpoints + unit tests) ────────


def call_get_lat_lng(arguments: dict) -> dict:
    location = arguments.get("location_description", "unknown")
    rng = _seeded_random(location.lower().strip())
    return {
        "lat": round(rng.uniform(-90, 90), 4),
        "lng": round(rng.uniform(-180, 180), 4),
    }


def call_get_weather(arguments: dict) -> dict:
    lat = arguments.get("lat", 0)
    lng = arguments.get("lng", 0)
    rng = _seeded_random(f"{lat},{lng}")
    return {
        "temperature": f"{rng.randint(-10, 40)} °C",
        "description": rng.choice(_WEATHER_CONDITIONS),
        "humidity": f"{rng.randint(20, 100)}%",
        "wind_speed": f"{rng.randint(0, 50)} km/h",
    }


_TOOL_HANDLERS = {
    "get_lat_lng": call_get_lat_lng,
    "get_weather": call_get_weather,
}


def execute_tool(name: str, arguments: dict) -> dict:
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return handler(arguments)

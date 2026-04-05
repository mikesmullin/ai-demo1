# mcp-gw

MCP (Model Context Protocol) gateway server with mock tool implementations. Provides tools that LLMs can invoke during chat conversations — currently `get_lat_lng` and `get_weather` with deterministic fake data.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/mcp` | MCP Streamable HTTP transport (native protocol via FastMCP) |
| `GET` | `/tools` | List available tools (REST convenience) |
| `POST` | `/tools/call` | Execute a tool directly (REST convenience) |

## Tools

- **get_lat_lng** — returns latitude/longitude for a location description
- **get_weather** — returns temperature, conditions, humidity, and wind speed for a lat/lng pair

Both tools return deterministic results seeded from the input, so the same query always gives the same answer.

## Running

```bash
cd mcp-gw
uv sync
uv run uvicorn mcp_gw.app:app --port 8200
```

Or via the workspace launcher:

```bash
./launch.sh mcp-gw
```

## Tests

```bash
cd mcp-gw
uv run pytest tests/ -v
```

## MCP Streamable HTTP example

```bash
curl -s http://localhost:8200/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{
  "jsonrpc": "2.0", "id": 1, "method": "initialize",
  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
             "clientInfo": {"name": "curl", "version": "0.1"}}
}'
```

The response is delivered as an SSE event stream. Pydantic AI's `MCPServerStreamableHTTP` handles this automatically.
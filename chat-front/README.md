# chat-front

AI chat frontend powered by [Pydantic AI](https://ai.pydantic.dev/). Authenticates users via oauth-idp, sends LLM inference requests through chat-back, and calls tools on mcp-gw.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/chat` | Send a message to the AI agent, get a response |
| `POST` | `/login` | Perform OAuth PKCE login, returns an access token |

## Architecture

```
User ──POST /chat──▶ chat-front (Pydantic AI agent)
                        │
                        ├──▶ chat-back /v1/chat/completions (LLM inference)
                        │
                        └──▶ mcp-gw /tools/call (tool execution)
```

The agent is configured with two tools (`get_lat_lng`, `get_weather`) that bridge to mcp-gw over HTTP. The LLM backend is chat-back, which proxies to xAI or Copilot depending on the model prefix.

## Configuration

Environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `CHAT_BACK_URL` | `http://localhost:8100` | chat-back base URL |
| `MCP_GW_URL` | `http://localhost:8200` | mcp-gw base URL |
| `IDP_URL` | `http://localhost:9000` | oauth-idp base URL |
| `DEFAULT_MODEL` | `xai:grok-4-1-fast-reasoning` | Model string (provider:model) |
| `PORT` | `8300` | Server port |

## Running

```bash
cd chat-front
uv sync
uv run uvicorn chat_front.app:app --port 8300
```

Or via the workspace launcher:

```bash
./launch.sh chat-front
```

## Tests

```bash
cd chat-front
uv run pytest tests/ -v
```
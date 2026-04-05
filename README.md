# GenAI Info+Tool Decen Arch Demo 001

A local development lab that replicates a production AI chat stack end-to-end: OAuth authentication, LLM inference proxying, tool-calling via MCP, and OpenTelemetry tracing — all running on localhost with no external dependencies beyond an xAI API key.

## Motivation

The goal is to give developers a self-contained environment where every piece of the AI inference pipeline is visible and debuggable locally. Instead of pointing at shared staging services, each component runs as its own process with its own logs:

- **Understand the full request lifecycle** — from OAuth token issuance, through the chat agent, to the upstream LLM provider and back.
- **Develop and test in isolation** — each service has its own unit tests; the integration suite exercises the whole chain.
- **Experiment with provider routing** — chat-back routes to xAI or Copilot based on a model-name prefix (`xai:grok-4-1-fast-reasoning`, `copilot:claude-sonnet-4.6`), making it easy to compare providers.
- **Prototype tool-calling flows** — mcp-gw provides mock MCP tools so the agent can exercise tool_call round-trips without external APIs.

## Services

| Service | Port | Description |
|---------|------|-------------|
| [oauth-idp](oauth-idp/) | 9000 | Custom OAuth2 IDP (Authorization Code + PKCE, RS256 JWTs) |
| [chat-back](chat-back/) | 8100 | AI inference proxy — OpenAI-compatible API, routes to xAI or Copilot |
| [mcp-gw](mcp-gw/) | 8200 | MCP tool server with mock implementations (get_lat_lng, get_weather) |
| [chat-front](chat-front/) | 8300 | Pydantic AI chat agent — authenticates via OAuth, calls LLM + tools |

## End-to-end flow

```
                         PKCE
  ┌────────────┐  ◀──────────────▶  ┌───────────┐
  │ chat-front │        tokens        │ oauth-idp │
  │   :8300    │                      │   :9000   │
  └──┬─────┬───┘                      └───────────┘
     │     │
     │     │  tool_call (MCP over HTTP)
     │     ▼
     │   ┌──────────┐
     │   │  mcp-gw  │  ← one of potentially many MCP servers
     │   │  :8200   │
     │   └──────────┘
     │
     │  /v1/chat/completions - inference
     ▼
  ┌───────────┐   upstream   ┌──────────────┐
  │ chat-back │────────────▶│ xAI / Copilot│
  │   :8100   │              └──────────────┘
  └───────────┘
```

The Pydantic AI agent in chat-front owns the tool-calling loop: it sends inference requests to chat-back, receives assistant responses (which may include `tool_call` requests), executes those tools against mcp-gw (or any other connected MCP server), and feeds the results back to the LLM. chat-back is a pure inference proxy — it never calls mcp-gw.

## Quick start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- An xAI API key in `chat-back/.env`:
  ```
  XAI_API_KEY=xai-...
  ```

### launch.sh

The workspace launcher builds, starts, and manages all services in dependency order.

```bash
# Start everything
./launch.sh

# Start a single service
./launch.sh oauth-idp

# Check what's running
./launch.sh status

# Tail logs (all services, or a specific one)
./launch.sh logs
./launch.sh logs chat-back

# Stop everything
./launch.sh stop
```

Services are started in order (oauth-idp → chat-back → mcp-gw → chat-front) and each is health-checked before the next one starts. PIDs are stored in `.pids/` and logs in `.logs/`.

### Integration tests

The integration test suite lives in `tests/test_integration.py`. It uses **only the Python stdlib** (no pip install needed) and exercises the full chain:

```bash
# Start all services first
./launch.sh

# Run the tests
python3 tests/test_integration.py
```

The suite runs 21 tests covering:

- **oauth-idp** — health, OIDC discovery, client registration, user creation, full PKCE flow, userinfo, token introspection
- **chat-back** — health, model listing, auth rejection, unknown-provider rejection, live xAI inference
- **mcp-gw** — health, REST tool listing, REST tool calls, MCP initialize (Streamable HTTP), MCP tools/list (Streamable HTTP)
- **chat-front** — health, login via PKCE, weather agent full loop

### Unit tests

Each service has its own test suite runnable via pytest:

```bash
cd oauth-idp && uv run pytest tests/ -v
cd chat-back && uv run pytest tests/ -v
cd mcp-gw   && uv run pytest tests/ -v
cd chat-front && uv run pytest tests/ -v
```

## Tech stack

- **Python 3.12** + **uv** for package/project management
- **FastAPI** + **uvicorn** for most HTTP services
- **FastMCP** (from the `mcp` SDK) + **uvicorn** for mcp-gw
- **Pydantic AI** for the chat agent (chat-front), with `MCPServerStreamableHTTP` for native MCP tool discovery
- **OpenAI Chat Completions API** format for inference
- **MCP** (Model Context Protocol) Streamable HTTP transport for tool calls
- **OTEL** GenAI semantic conventions for tracing (chat-back)
- **bcrypt** + **python-jose** for password hashing and JWT signing (oauth-idp)

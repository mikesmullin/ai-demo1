# chat-back

AI inference proxy that accepts **OpenAI Chat Completions API** requests and routes them to the correct upstream provider based on a model name prefix.

## Model Routing

| Prefix | Provider | Example |
|---|---|---|
| `xai:` | xAI (Grok) | `xai:grok-fast-1` |
| `copilot:` | GitHub Copilot | `copilot:claude-sonnet-4.6` |
| *(none)* | xAI (default) | `grok-3` |

## Quick Start

```bash
cd chat-back
cp .env.example .env  # configure API keys
uv sync
uv run uvicorn chat_back.app:app --port 8100
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `XAI_API_KEY` | xAI API key | |
| `XAI_BASE_URL` | xAI base URL | `https://api.x.ai/v1` |
| `COPILOT_API_KEY` | Copilot API key | |
| `COPILOT_BASE_URL` | Copilot base URL | `https://api.githubcopilot.com` |
| `IDP_JWKS_URL` | oauth-idp JWKS URL | `http://localhost:9000/.well-known/jwks.json` |
| `IDP_ISSUER` | oauth-idp issuer | `http://localhost:9000` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP gRPC endpoint | `http://localhost:4317` |

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/v1/models` | GET | List available provider prefixes |
| `/v1/chat/completions` | POST | OpenAI-compatible chat completions (requires Bearer token) |

## OTEL Tracing

Every inference request emits a span following the [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/) with attributes including `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.provider.name`, token usage, and finish reasons. Traces export via OTLP gRPC to Grafana Tempo (or any OTEL collector).

If the incoming request includes a W3C `traceparent` header, the inference span joins that distributed trace — allowing a single trace to cover the full agent loop across chat-back and mcp-gw.

## Tests

```bash
uv run pytest tests/ -v
```
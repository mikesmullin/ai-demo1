# chat-front1-py

Headless [Pydantic AI](https://ai.pydantic.dev/) agent that runs one inference + tool-call loop on startup, logs every step to stdout, then idles. Restart the pod to trigger another run.

## How It Works

On startup the agent:

1. Connects to Envoy AI Gateway for both LLM inference (OpenAI-compatible `/v1/chat/completions`) and MCP tools (`/mcp`)
2. Sends a user prompt (default: *"What is the weather like in London, UK?"*)
3. The LLM calls `mcp-server__get_lat_lng` → gets coordinates
4. The LLM calls `mcp-server__get_weather` → gets weather data
5. The LLM composes a final answer from the tool results
6. All messages are logged to stdout, then the process idles

## Architecture

```
chat-front pod
  │
  ├── inference ──▶ Envoy AI Gateway ──▶ Azure AI Foundry (gpt-5.1)
  │
  └── tool calls ──▶ Envoy AI Gateway (/mcp) ──▶ mcp-server (FastMCP)
```

## Configuration

Environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVOY_BASE_URL` | `http://localhost:30080` | Envoy AI Gateway base URL |
| `ENVOY_MODEL` | `gpt-5.1` | Model name (must match AIGatewayRoute) |
| `USER_PROMPT` | `What is the weather like in London, UK?` | Prompt to run |

## Running Locally

```bash
cd chat-front
uv sync
ENVOY_BASE_URL=http://localhost:30080 python -m chat_front.app
```

## Running in Kubernetes

```bash
# Build and load image
cd chat-front
podman build -t chat-front:latest .
podman save chat-front:latest -o /tmp/chat-front.tar
kind load image-archive /tmp/chat-front.tar --name ai-gw-lab
rm /tmp/chat-front.tar

# Deploy
kubectl apply -f k8s/chat-front.yaml

# Check logs
kubectl logs -l app=chat-front

# Re-run (restart the pod)
kubectl rollout restart deploy/chat-front
```

## Sample Output

Below is the exact log output from a successful run inside the KIND cluster:

```
[03:00:05] [INIT] Envoy base URL: http://envoy-default-ai-gw-lab-82528b23.envoy-gateway-system.svc:80
[03:00:05] [INIT] Model: gpt-5.1
[03:00:05] [INIT] Prompt: What is the weather like in London, UK?
[03:00:05] [RUN] Starting agent run...
[03:00:38] [RESULT] Agent reply: Here's the current weather for London, UK:

- **Conditions:** Thunderstorms  
- **Temperature:** 2 °C  
- **Humidity:** 47%  
- **Wind speed:** 44 km/h  

If you tell me what you're planning (sightseeing, commuting, running, etc.), I can suggest what to wear or whether to bring any specific gear.
[03:00:38] [TRACE] --- Message history ---
[03:00:38] [TRACE]   [0] request: UserPromptPart(content='What is the weather like in London, UK?')
[03:00:38] [TRACE]   [1] response: ToolCallPart(tool_name='mcp-server__get_lat_lng', args='{"location_description":"London, UK"}')
[03:00:38] [TRACE]   [2] request: ToolReturnPart(tool_name='mcp-server__get_lat_lng', content='{"lat": -29.8725, "lng": 151.0152}')
[03:00:38] [TRACE]   [3] response: ToolCallPart(tool_name='mcp-server__get_weather', args='{"lng":151.0152,"lat":-29.8725}')
[03:00:38] [TRACE]   [4] request: ToolReturnPart(tool_name='mcp-server__get_weather', content='{"temperature": "2 °C", "description": "thunderstorms", "humidity": "47%", "wind_speed": "44 km/h"}')
[03:00:38] [TRACE]   [5] response: TextPart(content='Here\'s the current weather for London, UK: ...')
[03:00:38] [TRACE] --- End ---
[03:00:38] [DONE] Run complete. Pod idling.
[03:00:38] [IDLE] Sleeping. Restart pod to run again.
```

The trace shows the full agentic loop: user prompt → LLM tool call → geocode → LLM tool call → weather → LLM final answer.
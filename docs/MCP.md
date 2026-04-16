# MCP Server Integration

This document describes how the MCP tool server (`mcp-server`) is
containerized, deployed into Kubernetes, and exposed through Envoy AI
Gateway's `MCPRoute` CRD.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Client (curl, chat-front1-py, MCP SDK)                  │
│  POST http://localhost:30080/mcp                     │
└──────────────────┬───────────────────────────────────┘
                   │
          ┌────────▼────────┐
          │  Envoy Gateway  │  (NodePort 30080)
          │  MCPRoute CRD   │
          │  path: /mcp     │
          └────────┬────────┘
                   │  Aggregation layer:
                   │  • prefixes tool names with backend name
                   │  • manages MCP sessions
                   │  • routes tools/call to correct backend
                   │
          ┌────────▼────────┐
          │  mcp-server:8200 │  (ClusterIP Service)
          │  FastMCP server │
          │  /mcp endpoint  │
          └─────────────────┘
```

Envoy AI Gateway acts as an **MCP aggregation proxy**. It presents a
single `/mcp` endpoint to clients and fans out to one or more backend
MCP servers. Tool names are automatically namespaced
(`<backend>__<tool>`) to prevent collisions when multiple backends are
registered.

## Components

### Container Image

| Item | Value |
|------|-------|
| Dockerfile | `mcp-server/Dockerfile` |
| Base image | `python:3.12-slim` |
| Entrypoint | `uvicorn mcp_server.app:app --host 0.0.0.0 --port 8200` |
| Exposed port | 8200 |

Build and load into KIND:

```bash
cd mcp-server
podman build -t mcp-server:latest .
podman save mcp-server:latest -o /tmp/mcp-server.tar
kind load image-archive /tmp/mcp-server.tar --name ai-gw-lab
rm /tmp/mcp-server.tar
```

### Kubernetes Resources

All manifests live in `k8s/`.

| Manifest | Resource | Purpose |
|----------|----------|---------|
| `k8s/mcp-server.yaml` | Deployment `mcp-server` | Runs the FastMCP server (1 replica) |
| `k8s/mcp-server.yaml` | Service `mcp-server` | ClusterIP on port 8200 |
| `k8s/mcp-route.yaml` | MCPRoute `mcp-tools` | Wires Envoy `/mcp` → `mcp-server:8200/mcp` |

Deploy:

```bash
kubectl apply -f k8s/mcp-server.yaml
kubectl apply -f k8s/mcp-route.yaml
kubectl rollout status deployment/mcp-server --timeout=60s
```

### MCPRoute

```yaml
apiVersion: aigateway.envoyproxy.io/v1alpha1
kind: MCPRoute
metadata:
  name: mcp-tools
spec:
  parentRefs:
    - name: ai-gw-lab
      sectionName: http
  path: /mcp
  backendRefs:
    - name: mcp-server
      port: 8200
      path: /mcp
```

The `parentRefs` attaches this route to the `ai-gw-lab` Gateway's
`http` listener. The `backendRefs` points to the `mcp-server` Service.
Envoy discovers the backend's tools at startup and merges them into its
aggregated tool list.

### Application Endpoints

The FastMCP server exposes:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/mcp` | configurable | MCP Streamable HTTP transport (JSON-RPC over HTTP) |
| GET | `/health` | public | Liveness/readiness check |
| GET | `/tools` | public | REST convenience — list tool definitions |
| POST | `/tools/call` | configurable | REST convenience — invoke a tool |

### Mock Tools

Both tools return **deterministic fake data** seeded from the input so
tests are reproducible without external APIs.

| Tool | Description | Inputs |
|------|-------------|--------|
| `get_lat_lng` | Geocode a location description | `location_description` (string) |
| `get_weather` | Weather at a coordinate | `lat` (number), `lng` (number) |

### Auth Configuration

The server wraps the ASGI app with `JWTAuthMiddleware`. Inside the
cluster, JWT auth is **disabled** via the `AUTH_ENABLED=false` env var
so the server is reachable without an IDP. When `oauth-idp` is deployed,
set `AUTH_ENABLED=true` and configure `IDP_JWKS_URL` /
`IDP_ISSUER` accordingly.

## Testing

All tests hit the gateway at `http://localhost:30080`.

### Test 1 — MCP Initialize

Open a session:

```bash
curl -s -D - http://localhost:30080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "initialize",
    "id": 1,
    "params": {
      "protocolVersion": "2025-03-26",
      "capabilities": {},
      "clientInfo": {"name": "test", "version": "1.0"}
    }
  }'
```

**Expected:** HTTP 200 with a `Mcp-Session-Id` response header and:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "capabilities": {"prompts": {}, "resources": {}, "tools": {}},
    "protocolVersion": "2025-06-18",
    "serverInfo": {"name": "envoy-ai-gateway", "version": "dev"}
  }
}
```

Save the `Mcp-Session-Id` header value for subsequent requests.

### Test 2 — List Tools

```bash
curl -s http://localhost:30080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2}'
```

**Expected:** SSE response containing the two tools with namespaced
names:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {"name": "mcp-server__get_lat_lng", "description": "Get the latitude and longitude of a location.", "...": "..."},
      {"name": "mcp-server__get_weather", "description": "Get the current weather at a location given latitude and longitude.", "...": "..."}
    ]
  }
}
```

### Test 3 — Call a Tool

```bash
curl -s http://localhost:30080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": 3,
    "params": {
      "name": "mcp-server__get_lat_lng",
      "arguments": {"location_description": "London, UK"}
    }
  }'
```

**Expected:** SSE response with deterministic coordinates:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [{"type": "text", "text": "{\"lat\": -29.8725, \"lng\": 151.0152}"}],
    "isError": false
  }
}
```

### Test 4 — Chain Both Tools

```bash
# Get coordinates for Paris
curl -s http://localhost:30080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": 4,
    "params": {
      "name": "mcp-server__get_lat_lng",
      "arguments": {"location_description": "Paris, France"}
    }
  }'

# Use those coordinates to get weather
curl -s http://localhost:30080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": 5,
    "params": {
      "name": "mcp-server__get_weather",
      "arguments": {"lat": 51.5074, "lng": -0.1278}
    }
  }'
```

### Test 5 — Direct Backend Health Check

Bypass Envoy and hit the pod directly:

```bash
kubectl run curl-test --image=curlimages/curl --rm -it --restart=Never \
  -- curl -s http://mcp-server:8200/health
```

**Expected:** `{"status":"ok"}`

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| MCPRoute status not `Accepted` | Gateway reference mismatch | Check `parentRefs.name` matches the Gateway name |
| `tools/list` returns empty array | Backend pod not ready | `kubectl rollout status deploy/mcp-server` |
| 502 on `/mcp` | Pod crash or image not loaded | `kubectl describe pod -l app=mcp-server` / reload image |
| Tool names not prefixed | Using direct backend URL | This is expected — prefixing only happens through Envoy |

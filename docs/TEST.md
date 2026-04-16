# Testing the Azure AI Foundry Integration

This document describes how to test the Envoy AI Gateway ↔ Azure AI
Foundry integration from a developer workstation.

## Access Methods

The Envoy proxy runs inside the KIND cluster. Two methods expose it to
the host.

### Method 1: NodePort (recommended)

The KIND cluster maps container port 30080 to host port 30080. The Envoy
service's NodePort is patched to 30080 during setup:

```bash
kubectl patch svc -n envoy-gateway-system \
  "$(kubectl get svc -n envoy-gateway-system -o name | grep 'ai-gw-lab')" \
  --type='json' \
  -p='[{"op":"replace","path":"/spec/ports/0/nodePort","value":30080}]'
```

After patching, the gateway is available at `http://localhost:30080`.

### Method 2: kubectl port-forward

Forward directly to the Envoy deployment:

```bash
kubectl port-forward -n envoy-gateway-system \
  deploy/envoy-default-ai-gw-lab-82528b23 8080:80
```

The gateway is then available at `http://localhost:8080`.

> **Note:** Port-forward can be flaky under rootless Podman + KIND. If
> connections drop, prefer the NodePort method.

## Test 1: Basic Chat Completion

Send a minimal chat completion request through the gateway:

```bash
curl -s http://localhost:30080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "x-ai-eg-model: gpt-5.1" \
  -d '{
    "model": "gpt-5.1",
    "messages": [{"role": "user", "content": "Say hi"}],
    "max_completion_tokens": 10
  }'
```

**Expected response** (HTTP 200):

```json
{
  "choices": [
    {
      "finish_reason": "length",
      "index": 0,
      "message": {
        "content": "...",
        "role": "assistant"
      }
    }
  ],
  "model": "gpt-5.1-2025-11-13",
  "object": "chat.completion",
  "usage": {
    "completion_tokens": 10,
    "prompt_tokens": 8,
    "total_tokens": 18
  }
}
```

Key things to check:

- HTTP status is **200**
- `model` field shows the deployed model version
- `choices[0].message.content` contains generated text
- `usage` shows token counts

## Test 2: Verify Header Routing

The `x-ai-eg-model` header selects which backend handles the request.
Omitting it should return an error (no matching route):

```bash
curl -s -w '\nHTTP_CODE: %{http_code}\n' http://localhost:30080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-5.1", "messages": [{"role": "user", "content": "hi"}]}'
```

**Expected:** HTTP 404 (no route matched).

## Test 3: Verbose Output with Timing

Use curl's verbose and timing features to inspect the full request:

```bash
curl -v -w '\n\ntime_total: %{time_total}s\n' \
  http://localhost:30080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "x-ai-eg-model: gpt-5.1" \
  -d '{
    "model": "gpt-5.1",
    "messages": [{"role": "user", "content": "What is 2+2?"}],
    "max_completion_tokens": 50
  }' 2>&1
```

Check the response headers for:

- `server: envoy` — confirms the request went through Envoy
- `x-envoy-upstream-service-time` — time Envoy waited for Azure
- `content-type: application/json` — Azure responded with JSON

## Test 4: Direct Azure Comparison

To verify the Azure endpoint itself works, bypass Envoy and call Azure
directly:

```bash
AZURE_HOST="daemon-resource.services.ai.azure.com"
API_KEY="<your-api-key>"

curl -s "https://${AZURE_HOST}/openai/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_KEY}" \
  -d '{
    "model": "gpt-5.1",
    "messages": [{"role": "user", "content": "Say hi"}],
    "max_completion_tokens": 10
  }'
```

This uses the same OpenAI-compatible endpoint and auth that Envoy uses
internally. If this works but the gateway test fails, the issue is in
the Envoy configuration.

## Test 5: Check Resource Status

Verify all Kubernetes resources are healthy:

```bash
# All should show "Accepted"
kubectl get aigatewayroute,aiservicebackend,backendsecuritypolicy,backend,backendtlspolicy

# Patch should show ACCEPTED=True PROGRAMMED=True
kubectl get envoypatchpolicy

# Envoy pod should be 3/3 Running
kubectl get pods -n envoy-gateway-system
```

## Test 6: Envoy Admin Interface

The Envoy admin is available inside the cluster on port 19000. Use a
temporary pod to query it:

```bash
# Get the Envoy pod IP
ENVOY_IP=$(kubectl get pods -n envoy-gateway-system \
  -l gateway.envoyproxy.io/owning-gateway-name=ai-gw-lab \
  -o jsonpath='{.items[0].status.podIP}')

# Check readiness
kubectl run --rm -it admin-check --image=curlimages/curl --restart=Never -- \
  curl -s http://${ENVOY_IP}:19000/ready

# View upstream cluster stats
kubectl run --rm -it admin-stats --image=curlimages/curl --restart=Never -- \
  curl -s "http://${ENVOY_IP}:19000/stats?filter=upstream_rq"

# Dump full config (large output)
kubectl run --rm -it admin-dump --image=curlimages/curl --restart=Never -- \
  curl -s http://${ENVOY_IP}:19000/config_dump
```

Useful stats to look for:

| Stat | Meaning |
|------|---------|
| `upstream_rq_total` | Total requests sent upstream |
| `upstream_rq_completed` | Requests that got a response |
| `upstream_rq_502` | Requests that got 502 (should be 0) |
| `upstream_cx_total` | Total upstream connections opened |

## Common Errors

### 502 `protocol_error`

```json
{"type":"error","error":{"type":"OpenAIBackendError","code":"502",
  "message":"upstream connect error or disconnect/reset before headers. reset reason: protocol error"}}
```

The `EnvoyPatchPolicy` that forces HTTP/1.1 upstream is missing or not
programmed. Check:

```bash
kubectl get envoypatchpolicy azure-force-alpn
```

### 400 `unsupported_parameter`

```json
{"error":{"message":"Unsupported parameter: 'max_tokens' is not supported with this model.
  Use 'max_completion_tokens' instead."}}
```

This is an Azure model-level error, not a gateway issue. Use
`max_completion_tokens` instead of `max_tokens` in your request body.

### 404 Not Found

No route matched. Ensure the `x-ai-eg-model` header matches the value
in your `AIGatewayRoute` rule (e.g., `gpt-5.1`).

### Connection refused on localhost:30080

The KIND NodePort mapping or service patch may be missing. Verify:

```bash
kubectl get svc -n envoy-gateway-system | grep ai-gw-lab
```

The `PORT(S)` column should show `80:30080/TCP`.

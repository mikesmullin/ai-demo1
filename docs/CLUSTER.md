# Cluster Architecture

This document describes the Kubernetes cluster running Envoy AI Gateway
with Azure AI Foundry as the inference backend.

## Infrastructure

| Component | Version / Detail |
|-----------|-----------------|
| Host OS | Arch Linux |
| Container runtime | Podman 5.8.2 (rootless) |
| Cluster tool | KIND v0.31.0 |
| Kubernetes | v1.35.0 (single control-plane node) |
| Helm | v3.17.3 |
| kubectl | v1.35.4 |

The KIND cluster is named **`ai-gw-lab`** and runs a single control-plane
node. Two host ports are mapped through KIND for local access:

| Host Port | Purpose |
|-----------|---------|
| 30080 | Envoy AI Gateway (NodePort) |
| 30300 | Grafana (reserved, not yet deployed) |

## Namespaces

| Namespace | Contents |
|-----------|----------|
| `envoy-gateway-system` | Envoy Gateway controller, Envoy proxy pods |
| `envoy-ai-gateway-system` | AI Gateway controller |
| `default` | Application resources (routes, backends, secrets) |
| `kube-system` | CoreDNS, etcd, API server, scheduler, etc. |

## Helm Releases

| Release | Namespace | Chart |
|---------|-----------|-------|
| `eg` | `envoy-gateway-system` | `gateway-helm` v0.0.0-latest |
| `aieg-crd` | `envoy-ai-gateway-system` | `ai-gateway-crds-helm` v0.0.0-latest |
| `aieg` | `envoy-ai-gateway-system` | `ai-gateway-helm` v0.0.0-latest |

## Kubernetes Resources

### Gateway API

- **GatewayClass** `ai-gw-lab` — controller `gateway.envoyproxy.io/gatewayclass-controller`
- **Gateway** `ai-gw-lab` — HTTP listener on port 80

### Envoy Gateway

- **EnvoyProxy** `ai-gw-lab` — custom bootstrap with admin interface on port 19000, debug logging, no resource limits (lab environment)
- **ClientTrafficPolicy** `ai-gw-lab-buffer` — raises the default 32 KB connection buffer to 50 MB for large AI payloads
- **EnvoyPatchPolicy** `azure-force-alpn` — JSON patches the generated Envoy cluster config to force HTTP/1.1 upstream (see [Workaround](#http11-workaround) below)

### AI Gateway

- **AIGatewayRoute** `azure-ai-foundry` — routes requests with header `x-ai-eg-model: gpt-5.1` to the Azure backend
- **AIServiceBackend** `azure-ai-foundry` — OpenAI-compatible schema with prefix `/openai/v1`
- **BackendSecurityPolicy** `azure-ai-foundry-apikey` — injects the Azure API key via `Authorization: Bearer` header
- **Backend** `azure-ai-foundry` — FQDN endpoint `daemon-resource.services.ai.azure.com:443`
- **BackendTLSPolicy** `azure-ai-foundry-tls` — system CA bundle, SNI validation for the Azure hostname

### Secrets

- **Secret** `azure-ai-foundry-apikey` — Azure AI Foundry API key (Opaque, `stringData.apiKey`)

## Request Flow

```
Client (curl)
  │
  ▼  HTTP :30080 (NodePort)
┌─────────────────────────────────┐
│  KIND Node                      │
│  ┌───────────────────────────┐  │
│  │ Envoy Proxy Pod           │  │
│  │  ├─ Listener :80          │  │
│  │  ├─ ext_proc (AI Gateway) │  │
│  │  │   ├─ header mutation   │  │
│  │  │   ├─ body rewrite      │  │
│  │  │   └─ auth injection    │  │
│  │  └─ upstream cluster      │  │
│  └───────────┬───────────────┘  │
│              │ TLS :443         │
└──────────────┼──────────────────┘
               ▼
     Azure AI Foundry
     daemon-resource.services.ai.azure.com
     Model: gpt-5.1
```

1. Client sends `POST /v1/chat/completions` with header `x-ai-eg-model: gpt-5.1`.
2. Envoy matches the `AIGatewayRoute` rule and selects the `azure-ai-foundry` backend.
3. The AI Gateway ext_proc filter rewrites the path to `/openai/v1/chat/completions`, injects the API key, and may rewrite the request body.
4. Envoy opens a TLS connection to Azure (HTTP/1.1, system CA validation, SNI).
5. Azure returns the chat completion; Envoy proxies the response back.

## Azure AI Foundry Backend

| Setting | Value |
|---------|-------|
| Resource | `daemon-resource` (CognitiveServices) |
| Resource Group | `rg-daemon` |
| Region | Central US |
| Endpoint | `daemon-resource.services.ai.azure.com` |
| Model deployment | `gpt-5.1` (v2025-11-13, GlobalStandard SKU) |
| API version | 2025-01-01-preview (via OpenAI-compatible `/openai/v1` prefix) |

## HTTP/1.1 Workaround

The AI Gateway controller generates an Envoy cluster with `auto_config`
(automatic HTTP/1.1 vs HTTP/2 detection). A known issue causes HTTP/2
upstream connections to fail with `protocol_error` when the ext_proc
filter rewrites the request body — a stale `content-length` header is
injected by an upstream `header_mutation` filter after the body has
already been resized by ext_proc.

The `EnvoyPatchPolicy` in `k8s/envoy-patch-alpn.yaml` works around this
by:

1. Setting `alpn_protocols: ["http/1.1"]` on the TLS context so Azure
   negotiates HTTP/1.1.
2. Replacing `auto_config` with `explicit_http_config.http_protocol_options`
   so Envoy always speaks HTTP/1.1 upstream.

HTTP/1.1 is more lenient about content-length mismatches and the request
succeeds. This workaround should be removed once the upstream bug is
fixed in Envoy AI Gateway.

## Files

| File | Purpose |
|------|---------|
| `k8s/kind-cluster.yaml` | KIND cluster definition |
| `k8s/base-gateway.yaml` | GatewayClass, Gateway, EnvoyProxy, ClientTrafficPolicy |
| `k8s/azure-ai-foundry.yaml` | AIGatewayRoute, AIServiceBackend, Backend, TLS, Secret |
| `k8s/envoy-patch-alpn.yaml` | EnvoyPatchPolicy workaround for HTTP/1.1 |

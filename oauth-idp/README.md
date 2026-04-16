# oauth-idp

Local development / mock OAuth2 Identity Provider supporting **Authorization Code + PKCE**.
Designed as a temporary stand-in for a real IDP (e.g. Okta, Entra ID) in the lab environment.
**Not for production use.**

## Quick Start

### Local (outside cluster)

```bash
cd oauth-idp
uv sync
uv run uvicorn oauth_idp.app:app --port 9000
```

### Kubernetes (KIND cluster)

```bash
# Build and load image
podman build -t localhost/oauth-idp:latest .
podman save localhost/oauth-idp:latest -o /tmp/oauth-idp.tar
kind load image-archive /tmp/oauth-idp.tar --name ai-gw-lab

# Deploy
kubectl apply -f k8s/oauth-idp.yaml
```

The service is exposed at **NodePort 30300** for external access (integration tests)
and at `oauth-idp.default.svc:9000` inside the cluster.

## Configuration

| Env Var | Default | Description |
|---|---|---|
| `ISSUER` | `http://localhost:9000` | JWT issuer claim and OIDC discovery base URL |

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/.well-known/openid-configuration` | GET | OIDC discovery document |
| `/.well-known/jwks.json` | GET | Public signing keys (RS256) |
| `/admin/clients` | GET, POST | List / register OAuth clients |
| `/admin/clients/{id}` | GET, DELETE | Get / remove a client |
| `/admin/users` | GET, POST | List / create users |
| `/admin/users/{id}` | GET, DELETE | Get / remove a user |
| `/admin/token` | POST | Mint a test token directly (no PKCE flow) |
| `/authorize` | GET, POST | Authorization Code + PKCE flow (login form) |
| `/token` | POST | Exchange auth code + PKCE verifier for tokens |
| `/userinfo` | GET | User claims (requires Bearer token) |
| `/introspect` | POST | RFC 7662 token introspection |

## Envoy AI Gateway Integration

The Envoy AI Gateway `SecurityPolicy` (JWT authentication) uses this IDP's JWKS
endpoint to validate Bearer tokens on **all** incoming requests — both inference
(AIGatewayRoute) and MCP (MCPRoute). See `k8s/security-policy-jwt.yaml`.

```yaml
# SecurityPolicy points Envoy at the in-cluster JWKS
remoteJWKS:
  uri: http://oauth-idp.default.svc:9000/.well-known/jwks.json
```

## Usage Examples

### 1. Mint a test token (for integration tests / curl)

```bash
curl -s -X POST http://localhost:30300/admin/token \
  -H "Content-Type: application/json" \
  -d '{"sub": "test-user"}'
```

### 2. Use the token with Envoy

```bash
TOKEN=$(curl -s -X POST http://localhost:30300/admin/token \
  -H "Content-Type: application/json" \
  -d '{"sub":"test-user"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl http://localhost:30080/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-ai-eg-model: gpt-5.1" \
  -d '{"model":"gpt-5.1","messages":[{"role":"user","content":"hi"}],"max_completion_tokens":50}'
```

### 3. Full PKCE flow (register client → create user → authorize → exchange)

```bash
# Register a client
curl -s -X POST http://localhost:9000/admin/clients \
  -H "Content-Type: application/json" \
  -d '{"client_name": "chat-front1-py", "redirect_uris": ["http://localhost:3000/callback"]}'

# Create a user
curl -s -X POST http://localhost:9000/admin/users \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret", "email": "alice@example.com"}'
```

The `/authorize` endpoint renders a login form. After successful login it redirects
to the client's `redirect_uri` with an authorization `code`. Exchange that code at
`/token` with the PKCE `code_verifier` to receive an `access_token` and `id_token`.

## Tests

```bash
uv run pytest tests/ -v
```

12 smoke tests cover admin CRUD, OIDC discovery, the full PKCE flow, token introspection, and error cases.
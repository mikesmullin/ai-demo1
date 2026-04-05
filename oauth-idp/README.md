# oauth-idp

Local development OAuth2 Identity Provider supporting **Authorization Code + PKCE**. Designed to mimic an Okta-like IDP for the local lab environment.

## Quick Start

```bash
cd oauth-idp
uv sync
uv run uvicorn oauth_idp.app:app --port 9000
```

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
| `/authorize` | GET, POST | Authorization Code + PKCE flow (login form) |
| `/token` | POST | Exchange auth code + PKCE verifier for tokens |
| `/userinfo` | GET | User claims (requires Bearer token) |
| `/introspect` | POST | RFC 7662 token introspection |

## Usage Example

### 1. Register a client

```bash
curl -s -X POST http://localhost:9000/admin/clients \
  -H "Content-Type: application/json" \
  -d '{"client_name": "chat-front", "redirect_uris": ["http://localhost:3000/callback"]}'
```

### 2. Create a user

```bash
curl -s -X POST http://localhost:9000/admin/users \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret", "email": "alice@example.com"}'
```

### 3. OAuth flow

The `/authorize` endpoint renders a login form. After successful login it redirects to the client's `redirect_uri` with an authorization `code`. Exchange that code at `/token` with the PKCE `code_verifier` to receive an `access_token` and `id_token`.

## Tests

```bash
uv run pytest tests/ -v
```

12 smoke tests cover admin CRUD, OIDC discovery, the full PKCE flow, token introspection, and error cases.
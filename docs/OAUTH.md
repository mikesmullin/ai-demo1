# OAuth IdP (Mock Okta)

This document describes the `oauth-idp` service — a local-dev OAuth 2.0
Identity Provider that mimics the Okta authorization flow using
Authorization Code + PKCE.

## Purpose

The IdP provides JWT-based authentication for the platform without
requiring an external Okta tenant. It is a **development-only** component
that runs in-memory with ephemeral RSA keys. Every restart generates a
fresh key pair and clears all registered clients, users, and auth codes.

## Architecture

```
┌─────────────┐       ┌──────────────┐       ┌──────────────┐
│ chat-front1-py  │──(1)──│  oauth-idp   │──(3)──│  mcp-server / │
│ (browser)   │       │  :9000       │       │   chat-back  │
└──────┬──────┘       └──────────────┘       └──────────────┘
       │                     │
       │  (2) redirect       │  (4) validate JWT
       │  with auth code     │  via JWKS endpoint
       └─────────────────────┘
```

1. Browser redirects to `/authorize` with PKCE challenge
2. User signs in, IdP redirects back with an authorization code
3. Client exchanges code + PKCE verifier for access/ID tokens at `/token`
4. Downstream services validate the JWT by fetching the IdP's JWKS

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |
| GET | `/.well-known/openid-configuration` | OIDC discovery document |
| GET | `/.well-known/jwks.json` | JSON Web Key Set (RS256 public key) |
| GET | `/authorize` | Renders a login form |
| POST | `/authorize` | Validates credentials, issues auth code, redirects |
| POST | `/token` | Exchanges auth code + PKCE verifier for tokens |
| GET | `/userinfo` | Returns user claims from a Bearer token |
| POST | `/introspect` | RFC 7662 token introspection |
| POST | `/admin/clients` | Register an OAuth client |
| GET | `/admin/clients` | List registered clients |
| GET | `/admin/clients/{id}` | Get a client by ID |
| DELETE | `/admin/clients/{id}` | Delete a client |
| POST | `/admin/users` | Create a user |
| GET | `/admin/users` | List users |
| GET | `/admin/users/{id}` | Get a user by ID |
| DELETE | `/admin/users/{id}` | Delete a user |

## Configuration

The IdP is a FastAPI application in `oauth-idp/oauth_idp/`. Key files:

| File | Purpose |
|------|---------|
| `app.py` | FastAPI app, OIDC discovery, JWKS endpoint |
| `crypto.py` | Ephemeral RSA key pair, JWT signing, PKCE verification |
| `models.py` | Pydantic models for clients, users, auth codes, tokens |
| `store.py` | In-memory store (clients, users, auth codes) |
| `routes_oauth.py` | `/authorize`, `/token`, `/userinfo`, `/introspect` |
| `routes_admin.py` | `/admin/clients`, `/admin/users` CRUD |

### Token Details

| Field | Value |
|-------|-------|
| Algorithm | RS256 |
| Key ID | `oauth-idp-dev-key` |
| Issuer | `http://localhost:9000` |
| Access token audience | `http://localhost:9000` |
| ID token audience | `<client_id>` |
| Default expiry | 3600 seconds |
| PKCE method | S256 only |

## Running Locally

```bash
cd oauth-idp
uv sync
uv run uvicorn oauth_idp.app:app --host 0.0.0.0 --port 9000
```

## Integration with mcp-server

When `mcp-server` runs with `AUTH_ENABLED=true` (the default outside K8s),
it validates Bearer tokens by fetching the JWKS from the IdP:

| mcp-server Setting | Default | Description |
|----------------|---------|-------------|
| `IDP_JWKS_URL` | `http://localhost:9000/.well-known/jwks.json` | JWKS endpoint |
| `IDP_ISSUER` | `http://localhost:9000` | Expected `iss` claim |
| `AUTH_ENABLED` | `true` | Set `false` to skip JWT validation |

The middleware checks the `Authorization: Bearer <token>` header on all
paths except `/health` and `/tools`. Valid claims are stored in a
context variable (`current_user`) accessible to tool handlers.

## Testing

### Unit Tests

The `oauth-idp` smoke tests cover the full PKCE flow:

```bash
cd oauth-idp
uv sync --group dev
uv run pytest tests/test_smoke.py -v
```

These tests exercise:

- Health and OIDC discovery endpoints
- JWKS key format
- Admin client and user CRUD
- Full Authorization Code + PKCE flow (authorize → token → userinfo → introspect)
- PKCE verifier mismatch rejection

### Manual Testing — Full PKCE Flow

The steps below demonstrate the complete OAuth flow using `curl`.
Start the IdP first:

```bash
cd oauth-idp
uv run uvicorn oauth_idp.app:app --port 9000
```

#### Step 1 — Register a Client

```bash
curl -s -X POST http://localhost:9000/admin/clients \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "chat-front1-py",
    "redirect_uris": ["http://localhost:3000/callback"]
  }' | python3 -m json.tool
```

Save the returned `client_id`.

#### Step 2 — Create a User

```bash
curl -s -X POST http://localhost:9000/admin/users \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice",
    "password": "secret",
    "email": "alice@example.com",
    "display_name": "Alice Doe"
  }' | python3 -m json.tool
```

#### Step 3 — Generate a PKCE Pair

```bash
CODE_VERIFIER=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
CODE_CHALLENGE=$(echo -n "$CODE_VERIFIER" | openssl dgst -sha256 -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')
echo "Verifier:  $CODE_VERIFIER"
echo "Challenge: $CODE_CHALLENGE"
```

#### Step 4 — Authorize (get the login form)

```bash
CLIENT_ID="<client_id from step 1>"

curl -s "http://localhost:9000/authorize?\
response_type=code&\
client_id=${CLIENT_ID}&\
redirect_uri=http://localhost:3000/callback&\
code_challenge=${CODE_CHALLENGE}&\
code_challenge_method=S256&\
state=test123"
```

This returns an HTML login form. In a real flow the browser would render
it. For testing, submit credentials directly:

#### Step 5 — Submit Credentials (get auth code)

```bash
curl -s -D - -o /dev/null -X POST http://localhost:9000/authorize \
  -d "client_id=${CLIENT_ID}" \
  -d "redirect_uri=http://localhost:3000/callback" \
  -d "code_challenge=${CODE_CHALLENGE}" \
  -d "code_challenge_method=S256" \
  -d "state=test123" \
  -d "username=alice" \
  -d "password=secret"
```

The `Location` header in the 302 redirect contains `code=<auth_code>&state=test123`.
Extract the code:

```bash
AUTH_CODE="<code from Location header>"
```

#### Step 6 — Exchange Code for Tokens

```bash
curl -s -X POST http://localhost:9000/token \
  -d "grant_type=authorization_code" \
  -d "code=${AUTH_CODE}" \
  -d "redirect_uri=http://localhost:3000/callback" \
  -d "client_id=${CLIENT_ID}" \
  -d "code_verifier=${CODE_VERIFIER}" | python3 -m json.tool
```

**Expected response:**

```json
{
  "access_token": "<jwt>",
  "token_type": "Bearer",
  "expires_in": 3600,
  "id_token": "<jwt>",
  "scope": ""
}
```

#### Step 7 — Verify the Token

```bash
ACCESS_TOKEN="<access_token from step 6>"

# Userinfo
curl -s http://localhost:9000/userinfo \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" | python3 -m json.tool

# Introspection
curl -s -X POST http://localhost:9000/introspect \
  -d "token=${ACCESS_TOKEN}" | python3 -m json.tool
```

#### Step 8 — Use the Token with mcp-server

If `mcp-server` is running locally with auth enabled:

```bash
curl -s http://localhost:8200/tools/call \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -d '{"name": "get_lat_lng", "arguments": {"location_description": "Tokyo, Japan"}}'
```

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Missing bearer token` | No `Authorization` header | Include `Bearer <token>` header |
| `401 Invalid token` | Token expired or wrong JWKS | Restart IdP (new keys) → re-issue token |
| `400 Invalid code_verifier (PKCE)` | Verifier doesn't match challenge | Regenerate the PKCE pair and retry |
| `400 Authorization code already used` | Code replayed | Codes are single-use; restart the flow |
| `409 Username already exists` | Duplicate user creation | IdP is in-memory; restart clears all data |

## Security Notes

This IdP is for **local development only**:

- RSA keys are ephemeral (regenerated on every restart)
- All data is in-memory (no persistence)
- The admin API has no authentication
- Passwords are bcrypt-hashed but stored in a Python dict
- HTTPS is not enforced

Do not use in production. Replace with Okta, Auth0, or another
production IdP for real deployments.

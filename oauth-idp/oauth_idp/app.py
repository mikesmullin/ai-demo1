"""OAuth2 IDP — FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI

from oauth_idp.crypto import _ISSUER, get_jwks
from oauth_idp.routes_admin import router as admin_router
from oauth_idp.routes_oauth import router as oauth_router

app = FastAPI(title="oauth-idp", version="0.1.0", description="Local dev OAuth2 IDP (Authorization Code + PKCE)")

app.include_router(admin_router)
app.include_router(oauth_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/.well-known/openid-configuration")
def openid_configuration():
    base = _ISSUER
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "userinfo_endpoint": f"{base}/userinfo",
        "introspection_endpoint": f"{base}/introspect",
        "jwks_uri": f"{base}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


@app.get("/.well-known/jwks.json")
def jwks():
    return get_jwks()

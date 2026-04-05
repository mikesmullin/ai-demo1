"""OAuth2 Authorization Code + PKCE flow routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import bcrypt

from oauth_idp.crypto import create_access_token, create_id_token, verify_pkce
from oauth_idp.models import AuthorizationCode, TokenGrant
from oauth_idp.store import store

router = APIRouter(tags=["oauth"])


# ---- /authorize (GET) — show login form ----


@router.get("/authorize")
def authorize(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    scope: str = Query(""),
    state: str = Query(""),
):
    client = store.get_client(client_id)
    if not client:
        raise HTTPException(400, "Unknown client_id")
    if redirect_uri not in client.redirect_uris:
        raise HTTPException(400, "Invalid redirect_uri")
    if response_type != "code":
        raise HTTPException(400, "Only response_type=code is supported")
    if code_challenge_method != "S256":
        raise HTTPException(400, "Only S256 code_challenge_method is supported")

    # Render a minimal login form
    form_html = f"""<!DOCTYPE html>
<html><head><title>Sign In — oauth-idp</title></head>
<body>
<h2>Sign in to {client.client_name}</h2>
<form method="post" action="/authorize">
  <input type="hidden" name="client_id" value="{client_id}">
  <input type="hidden" name="redirect_uri" value="{redirect_uri}">
  <input type="hidden" name="code_challenge" value="{code_challenge}">
  <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
  <input type="hidden" name="scope" value="{scope}">
  <input type="hidden" name="state" value="{state}">
  <label>Username <input name="username" required></label><br>
  <label>Password <input name="password" type="password" required></label><br>
  <button type="submit">Sign In</button>
</form>
</body></html>"""
    return HTMLResponse(form_html)


# ---- /authorize (POST) — validate credentials, issue auth code ----


@router.post("/authorize")
def authorize_post(
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    scope: str = Form(""),
    state: str = Form(""),
    username: str = Form(...),
    password: str = Form(...),
):
    client = store.get_client(client_id)
    if not client:
        raise HTTPException(400, "Unknown client_id")
    if redirect_uri not in client.redirect_uris:
        raise HTTPException(400, "Invalid redirect_uri")

    user = store.get_user_by_name(username)
    if not user or not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        raise HTTPException(401, "Invalid credentials")

    auth_code = AuthorizationCode(
        client_id=client_id,
        redirect_uri=redirect_uri,
        user_id=user.user_id,
        scope=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    store.add_auth_code(auth_code)

    params = {"code": auth_code.code}
    if state:
        params["state"] = state
    return RedirectResponse(
        url=f"{redirect_uri}?{urlencode(params)}",
        status_code=302,
    )


# ---- /token (POST) — exchange code for tokens ----


@router.post("/token", response_model=TokenGrant)
def token(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: str = Form(...),
    code_verifier: str = Form(...),
):
    if grant_type != "authorization_code":
        raise HTTPException(400, "Unsupported grant_type")

    auth_code = store.get_auth_code(code)
    if not auth_code:
        raise HTTPException(400, "Invalid authorization code")

    if auth_code.used:
        # Code replay — revoke
        store.remove_auth_code(code)
        raise HTTPException(400, "Authorization code already used")

    if datetime.now(timezone.utc) > auth_code.expires_at:
        store.remove_auth_code(code)
        raise HTTPException(400, "Authorization code expired")

    if auth_code.client_id != client_id:
        raise HTTPException(400, "client_id mismatch")

    if auth_code.redirect_uri != redirect_uri:
        raise HTTPException(400, "redirect_uri mismatch")

    if not verify_pkce(code_verifier, auth_code.code_challenge, auth_code.code_challenge_method):
        raise HTTPException(400, "Invalid code_verifier (PKCE)")

    # Mark used and remove
    auth_code.used = True
    store.remove_auth_code(code)

    user = store.get_user(auth_code.user_id)
    if not user:
        raise HTTPException(500, "User not found")

    expires_in = 3600
    access_token = create_access_token(sub=user.user_id, scope=auth_code.scope, expires_in=expires_in)
    id_token = create_id_token(
        sub=user.user_id,
        client_id=client_id,
        username=user.username,
        email=user.email,
        expires_in=expires_in,
    )

    return TokenGrant(
        access_token=access_token,
        expires_in=expires_in,
        id_token=id_token,
        scope=auth_code.scope,
    )


# ---- /userinfo — return user claims from access token ----


@router.get("/userinfo")
def userinfo(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token_str = auth[7:]

    from oauth_idp.crypto import decode_token

    try:
        claims = decode_token(token_str)
    except Exception:
        raise HTTPException(401, "Invalid token")

    user = store.get_user(claims["sub"])
    if not user:
        raise HTTPException(404, "User not found")

    return {
        "sub": user.user_id,
        "preferred_username": user.username,
        "email": user.email,
        "name": user.display_name,
    }


# ---- /introspect — RFC 7662 token introspection ----


@router.post("/introspect")
def introspect(token: str = Form(...)):
    from oauth_idp.crypto import decode_token

    try:
        claims = decode_token(token)
        return {"active": True, **claims}
    except Exception:
        return {"active": False}

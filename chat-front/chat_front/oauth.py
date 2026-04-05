"""OAuth helper — handles PKCE login flow against oauth-idp."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx


def _generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


async def register_client(
    idp_url: str, client_id: str, client_secret: str, redirect_uri: str
) -> dict:
    """Register chat-front as an OAuth client. Returns response with assigned client_id."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{idp_url}/admin/clients",
            json={
                "client_name": client_id,
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code"],
                "token_endpoint_auth_method": "none",
            },
        )
        return r.json()


async def get_token_via_pkce(
    idp_url: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    username: str,
    password: str,
) -> dict:
    """Perform full PKCE flow programmatically and return token response."""
    verifier, challenge = _generate_pkce()

    async with httpx.AsyncClient(follow_redirects=False) as client:
        # 1. Authorize (POST form)
        auth_data = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "openid",
            "username": username,
            "password": password,
        }
        r = await client.post(f"{idp_url}/authorize", data=auth_data)

        # Extract code from redirect Location header
        if r.status_code not in (302, 303):
            raise RuntimeError(f"Expected redirect, got {r.status_code}: {r.text}")
        location = r.headers["location"]
        from urllib.parse import parse_qs, urlparse

        code = parse_qs(urlparse(location).query)["code"][0]

        # 2. Exchange code for token
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        }
        r = await client.post(f"{idp_url}/token", data=token_data)
        r.raise_for_status()
        return r.json()

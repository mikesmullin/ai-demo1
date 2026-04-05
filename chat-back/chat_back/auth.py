"""JWT authentication middleware — validates tokens against oauth-idp."""

from __future__ import annotations

import httpx
from fastapi import HTTPException, Request
from jose import jwt, JWTError

from chat_back.config import settings

_jwks_cache: dict | None = None


async def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(settings.idp_jwks_url)
            resp.raise_for_status()
            _jwks_cache = resp.json()
    return _jwks_cache


def clear_jwks_cache() -> None:
    global _jwks_cache
    _jwks_cache = None


async def validate_token(request: Request) -> dict:
    """Extract and validate the Bearer token from the request.

    Returns the decoded JWT claims.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")

    token = auth[7:]
    jwks = await _get_jwks()

    try:
        # python-jose can accept JWKS directly
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=settings.idp_issuer,
        )
        return claims
    except JWTError as e:
        raise HTTPException(401, f"Invalid token: {e}")

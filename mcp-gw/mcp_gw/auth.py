"""JWT authentication — validates tokens against oauth-idp.

Provides:
  - ASGI middleware that enforces Bearer auth on protected paths
  - A contextvar (`current_user`) so tool handlers can read the caller's identity
"""

from __future__ import annotations

import contextvars
import json

import httpx
from jose import jwt, JWTError
from opentelemetry.propagate import extract

from mcp_gw.config import settings

# ── Contextvar for the authenticated user ────────────────────────────

current_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "current_user", default=None,
)

# ── JWKS cache ───────────────────────────────────────────────────────

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


async def validate_token(token: str) -> dict | None:
    """Decode and validate a JWT.  Returns claims dict or None."""
    jwks = await _get_jwks()
    try:
        return jwt.decode(token, jwks, algorithms=["RS256"], audience=settings.idp_issuer)
    except JWTError:
        return None


# ── Pure-ASGI auth middleware (streaming-safe, no buffering) ─────────

# Paths that do not require authentication
_PUBLIC_PATHS = frozenset({"/health", "/tools"})


class JWTAuthMiddleware:
    """ASGI middleware — validates Bearer token and populates `current_user`."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        # Extract Authorization header from raw ASGI headers
        auth_value = ""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth_value = value.decode()
                break

        if not auth_value.startswith("Bearer "):
            await self._send_json(send, 401, {"error": "Missing bearer token"})
            return

        claims = await validate_token(auth_value[7:])
        if claims is None:
            await self._send_json(send, 401, {"error": "Invalid token"})
            return

        current_user.set(claims)

        # Extract W3C trace context for distributed tracing
        from mcp_gw.tracing import incoming_context
        carrier = {}
        for hdr_name, hdr_value in scope.get("headers", []):
            carrier[hdr_name.decode()] = hdr_value.decode()
        incoming_context.set(extract(carrier))

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_json(send, status: int, body_dict: dict):
        body = json.dumps(body_dict).encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode()],
            ],
        })
        await send({"type": "http.response.body", "body": body})

"""JWT and PKCE crypto utilities."""

from __future__ import annotations

import base64
import hashlib
import os
import time

from jose import jwt

# Simple RSA key for local dev — generated once at startup.
# In production you'd load from env/secrets.
_ALGORITHM = "RS256"
_ISSUER = os.environ.get("ISSUER", "http://localhost:9000")

# We generate an ephemeral RSA key pair at import time for simplicity.
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
_public_key = _private_key.public_key()
_public_pem = _public_key.public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)

# JWK representation for .well-known/jwks.json
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

_pub_numbers: RSAPublicNumbers = _public_key.public_numbers()


def _int_to_base64url(n: int) -> str:
    byte_length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()


KID = "oauth-idp-dev-key"


def get_jwks() -> dict:
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": _ALGORITHM,
                "kid": KID,
                "n": _int_to_base64url(_pub_numbers.n),
                "e": _int_to_base64url(_pub_numbers.e),
            }
        ]
    }


def create_access_token(sub: str, scope: str = "", expires_in: int = 3600) -> str:
    now = int(time.time())
    payload = {
        "iss": _ISSUER,
        "sub": sub,
        "aud": _ISSUER,
        "iat": now,
        "exp": now + expires_in,
        "scope": scope,
    }
    return jwt.encode(payload, _private_pem.decode(), algorithm=_ALGORITHM, headers={"kid": KID})


def create_id_token(
    sub: str,
    client_id: str,
    username: str = "",
    email: str = "",
    expires_in: int = 3600,
) -> str:
    now = int(time.time())
    payload = {
        "iss": _ISSUER,
        "sub": sub,
        "aud": client_id,
        "iat": now,
        "exp": now + expires_in,
        "preferred_username": username,
        "email": email,
    }
    return jwt.encode(payload, _private_pem.decode(), algorithm=_ALGORITHM, headers={"kid": KID})


def decode_token(token: str) -> dict:
    return jwt.decode(token, _public_pem.decode(), algorithms=[_ALGORITHM], audience=_ISSUER)


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    if method != "S256":
        raise ValueError("Only S256 is supported")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return computed == code_challenge

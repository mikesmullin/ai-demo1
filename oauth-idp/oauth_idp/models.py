"""Data models for the OAuth2 IDP."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


# --- Admin request/response models ---


class CreateClientRequest(BaseModel):
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str] = ["authorization_code"]
    token_endpoint_auth_method: str = "none"  # "none" for public clients (PKCE)


class ClientResponse(BaseModel):
    client_id: str
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str]
    token_endpoint_auth_method: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: str = ""
    display_name: str = ""


class UserResponse(BaseModel):
    user_id: str
    username: str
    email: str
    display_name: str


# --- Internal storage models ---


class StoredClient(BaseModel):
    client_id: str = Field(default_factory=lambda: secrets.token_hex(16))
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str]
    token_endpoint_auth_method: str


class StoredUser(BaseModel):
    user_id: str = Field(default_factory=lambda: secrets.token_hex(16))
    username: str
    password_hash: str
    email: str = ""
    display_name: str = ""


class AuthorizationCode(BaseModel):
    code: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    client_id: str
    redirect_uri: str
    user_id: str
    scope: str = ""
    code_challenge: str
    code_challenge_method: str = "S256"
    expires_at: datetime
    used: bool = False


class TokenGrant(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    id_token: str | None = None
    scope: str = ""

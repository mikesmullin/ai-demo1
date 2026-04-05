"""Admin API routes — manage clients and users."""

from __future__ import annotations

import bcrypt
from fastapi import APIRouter, HTTPException

from oauth_idp.models import (
    ClientResponse,
    CreateClientRequest,
    CreateUserRequest,
    StoredClient,
    StoredUser,
    UserResponse,
)
from oauth_idp.store import store

router = APIRouter(prefix="/admin", tags=["admin"])


# --- Client management ---


@router.post("/clients", response_model=ClientResponse, status_code=201)
def create_client(req: CreateClientRequest):
    client = StoredClient(
        client_name=req.client_name,
        redirect_uris=req.redirect_uris,
        grant_types=req.grant_types,
        token_endpoint_auth_method=req.token_endpoint_auth_method,
    )
    store.add_client(client)
    return _client_response(client)


@router.get("/clients", response_model=list[ClientResponse])
def list_clients():
    return [_client_response(c) for c in store.list_clients()]


@router.get("/clients/{client_id}", response_model=ClientResponse)
def get_client(client_id: str):
    client = store.get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return _client_response(client)


@router.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: str):
    if not store.delete_client(client_id):
        raise HTTPException(404, "Client not found")


# --- User management ---


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(req: CreateUserRequest):
    if store.get_user_by_name(req.username):
        raise HTTPException(409, "Username already exists")
    user = StoredUser(
        username=req.username,
        password_hash=bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode(),
        email=req.email,
        display_name=req.display_name,
    )
    store.add_user(user)
    return _user_response(user)


@router.get("/users", response_model=list[UserResponse])
def list_users():
    return [_user_response(u) for u in store.list_users()]


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: str):
    user = store.get_user(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return _user_response(user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str):
    if not store.delete_user(user_id):
        raise HTTPException(404, "User not found")


# --- Helpers ---


def _client_response(c: StoredClient) -> ClientResponse:
    return ClientResponse(
        client_id=c.client_id,
        client_name=c.client_name,
        redirect_uris=c.redirect_uris,
        grant_types=c.grant_types,
        token_endpoint_auth_method=c.token_endpoint_auth_method,
    )


def _user_response(u: StoredUser) -> UserResponse:
    return UserResponse(
        user_id=u.user_id,
        username=u.username,
        email=u.email,
        display_name=u.display_name,
    )

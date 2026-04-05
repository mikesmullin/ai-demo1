"""
Smoke tests for oauth-idp.

Scenario:
  1. Admin registers a new client (chat-front) with a redirect_uri
  2. Admin creates a user
  3. User performs Authorization Code + PKCE flow
  4. Resulting access token is valid and can be introspected
"""

import base64
import hashlib
import secrets

import pytest
from fastapi.testclient import TestClient

from oauth_idp.app import app
from oauth_idp.store import store


@pytest.fixture(autouse=True)
def _clear_store():
    """Reset store between tests."""
    store.clients.clear()
    store.users.clear()
    store.users_by_name.clear()
    store.auth_codes.clear()
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ---------- Helpers ----------

def _pkce_pair():
    """Generate a PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ---------- Tests ----------


class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestWellKnown:
    def test_openid_configuration(self, client):
        r = client.get("/.well-known/openid-configuration")
        assert r.status_code == 200
        data = r.json()
        assert data["issuer"] == "http://localhost:9000"
        assert "authorization_endpoint" in data
        assert "S256" in data["code_challenge_methods_supported"]

    def test_jwks(self, client):
        r = client.get("/.well-known/jwks.json")
        assert r.status_code == 200
        keys = r.json()["keys"]
        assert len(keys) == 1
        assert keys[0]["kty"] == "RSA"


class TestAdminClients:
    def test_create_and_list_client(self, client):
        r = client.post("/admin/clients", json={
            "client_name": "chat-front",
            "redirect_uris": ["http://localhost:3000/callback"],
        })
        assert r.status_code == 201
        data = r.json()
        assert data["client_name"] == "chat-front"
        assert "client_id" in data

        r2 = client.get("/admin/clients")
        assert r2.status_code == 200
        assert len(r2.json()) == 1

    def test_get_client(self, client):
        r = client.post("/admin/clients", json={
            "client_name": "test-app",
            "redirect_uris": ["http://localhost:8080/cb"],
        })
        cid = r.json()["client_id"]
        r2 = client.get(f"/admin/clients/{cid}")
        assert r2.status_code == 200
        assert r2.json()["client_id"] == cid

    def test_delete_client(self, client):
        r = client.post("/admin/clients", json={
            "client_name": "tmp",
            "redirect_uris": ["http://localhost/cb"],
        })
        cid = r.json()["client_id"]
        assert client.delete(f"/admin/clients/{cid}").status_code == 204
        assert client.get(f"/admin/clients/{cid}").status_code == 404


class TestAdminUsers:
    def test_create_and_list_user(self, client):
        r = client.post("/admin/users", json={
            "username": "alice",
            "password": "password123",
            "email": "alice@example.com",
            "display_name": "Alice Doe",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["username"] == "alice"
        assert "user_id" in data

        r2 = client.get("/admin/users")
        assert r2.status_code == 200
        assert len(r2.json()) == 1

    def test_duplicate_username(self, client):
        client.post("/admin/users", json={"username": "bob", "password": "pass"})
        r = client.post("/admin/users", json={"username": "bob", "password": "pass"})
        assert r.status_code == 409


class TestOAuthPKCEFlow:
    """End-to-end Authorization Code + PKCE flow."""

    def _setup(self, client):
        """Register a client and user, return (client_id, user_id)."""
        rc = client.post("/admin/clients", json={
            "client_name": "chat-front",
            "redirect_uris": ["http://localhost:3000/callback"],
        })
        client_id = rc.json()["client_id"]

        ru = client.post("/admin/users", json={
            "username": "alice",
            "password": "secret",
            "email": "alice@test.com",
        })
        user_id = ru.json()["user_id"]
        return client_id, user_id

    def test_full_pkce_flow(self, client):
        client_id, user_id = self._setup(client)
        verifier, challenge = _pkce_pair()

        # Step 1: GET /authorize -> login form HTML
        r = client.get("/authorize", params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "http://localhost:3000/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
        })
        assert r.status_code == 200
        assert "Sign in" in r.text

        # Step 2: POST /authorize -> redirect with code
        r2 = client.post("/authorize", data={
            "client_id": client_id,
            "redirect_uri": "http://localhost:3000/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "username": "alice",
            "password": "secret",
        }, follow_redirects=False)
        assert r2.status_code == 302
        location = r2.headers["location"]
        assert "code=" in location
        assert "state=xyz" in location

        # Extract the code from the redirect URL
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(location)
        code = parse_qs(parsed.query)["code"][0]

        # Step 3: POST /token -> exchange code for tokens
        r3 = client.post("/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:3000/callback",
            "client_id": client_id,
            "code_verifier": verifier,
        })
        assert r3.status_code == 200
        tokens = r3.json()
        assert "access_token" in tokens
        assert "id_token" in tokens
        assert tokens["token_type"] == "Bearer"

        # Step 4: Use access token to get /userinfo
        r4 = client.get("/userinfo", headers={
            "Authorization": f"Bearer {tokens['access_token']}"
        })
        assert r4.status_code == 200
        userinfo = r4.json()
        assert userinfo["preferred_username"] == "alice"
        assert userinfo["email"] == "alice@test.com"

        # Step 5: Introspect the token
        r5 = client.post("/introspect", data={"token": tokens["access_token"]})
        assert r5.status_code == 200
        intro = r5.json()
        assert intro["active"] is True
        assert intro["sub"] == user_id

    def test_wrong_pkce_verifier_rejected(self, client):
        client_id, _ = self._setup(client)
        verifier, challenge = _pkce_pair()

        # Authorize
        r = client.post("/authorize", data={
            "client_id": client_id,
            "redirect_uri": "http://localhost:3000/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "",
            "username": "alice",
            "password": "secret",
        }, follow_redirects=False)
        from urllib.parse import parse_qs, urlparse
        code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

        # Try to exchange with wrong verifier
        r2 = client.post("/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:3000/callback",
            "client_id": client_id,
            "code_verifier": "totally-wrong-verifier",
        })
        assert r2.status_code == 400

    def test_bad_credentials_rejected(self, client):
        client_id, _ = self._setup(client)
        _, challenge = _pkce_pair()

        r = client.post("/authorize", data={
            "client_id": client_id,
            "redirect_uri": "http://localhost:3000/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "",
            "username": "alice",
            "password": "wrong-password",
        })
        assert r.status_code == 401

    def test_invalid_token_introspection(self, client):
        r = client.post("/introspect", data={"token": "garbage-token"})
        assert r.status_code == 200
        assert r.json()["active"] is False

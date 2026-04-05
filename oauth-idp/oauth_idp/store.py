"""In-memory store for the OAuth2 IDP."""

from __future__ import annotations

from oauth_idp.models import AuthorizationCode, StoredClient, StoredUser


class Store:
    """Simple in-memory store for clients, users, and auth codes."""

    def __init__(self) -> None:
        self.clients: dict[str, StoredClient] = {}
        self.users: dict[str, StoredUser] = {}  # keyed by user_id
        self.users_by_name: dict[str, StoredUser] = {}  # keyed by username
        self.auth_codes: dict[str, AuthorizationCode] = {}  # keyed by code

    # --- Clients ---

    def add_client(self, client: StoredClient) -> None:
        self.clients[client.client_id] = client

    def get_client(self, client_id: str) -> StoredClient | None:
        return self.clients.get(client_id)

    def list_clients(self) -> list[StoredClient]:
        return list(self.clients.values())

    def delete_client(self, client_id: str) -> bool:
        return self.clients.pop(client_id, None) is not None

    # --- Users ---

    def add_user(self, user: StoredUser) -> None:
        self.users[user.user_id] = user
        self.users_by_name[user.username] = user

    def get_user(self, user_id: str) -> StoredUser | None:
        return self.users.get(user_id)

    def get_user_by_name(self, username: str) -> StoredUser | None:
        return self.users_by_name.get(username)

    def list_users(self) -> list[StoredUser]:
        return list(self.users.values())

    def delete_user(self, user_id: str) -> bool:
        user = self.users.pop(user_id, None)
        if user:
            self.users_by_name.pop(user.username, None)
            return True
        return False

    # --- Auth codes ---

    def add_auth_code(self, code: AuthorizationCode) -> None:
        self.auth_codes[code.code] = code

    def get_auth_code(self, code: str) -> AuthorizationCode | None:
        return self.auth_codes.get(code)

    def remove_auth_code(self, code: str) -> None:
        self.auth_codes.pop(code, None)


store = Store()

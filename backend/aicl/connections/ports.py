"""SecretStore, ProviderOAuthPort, CredentialBroker and their fakes (connection-network-policy/technical.md).

Contract stubs: signatures, errors and recording fakes only. Only the broker and the revocation path hold a
SecretStore; the web layer, chat and executor never import it.
"""

from __future__ import annotations

from typing import Protocol

from aicl.connections.models import CAPABILITY_SCOPES, Provider, ProviderResult, TokenSet  # noqa: F401
from aicl.creation.service import NOT_IMPLEMENTED


class SecretUnavailable(Exception):
    """get on a destroyed, missing or mismatched reference, or an unavailable store/key. Denies; never retries."""


class ProviderRevokeError(Exception):
    """ProviderOAuthPort.revoke failed or timed out (5 seconds)."""


class SecretStore(Protocol):
    """MVP: AES-256-GCM, key from AICL_SECRET_ENCRYPTION_KEY, random 96-bit nonce, AAD owner_id|connection_id|field."""

    def put(self, owner_id: str, connection_id: str, field: str, plaintext: bytes) -> str: ...

    def get(self, secret_ref: str, owner_id: str, connection_id: str) -> bytes: ...

    def destroy(self, secret_ref: str) -> None: ...


class ProviderOAuthPort(Protocol):
    def authorization_url(self, provider: Provider, scopes: tuple[str, ...], state: str, code_challenge: str,
                          redirect_uri: str) -> str: ...

    def exchange_code(self, provider: Provider, code: str, code_verifier: str, redirect_uri: str) -> TokenSet: ...

    def refresh(self, provider: Provider, refresh_token: str) -> TokenSet: ...

    def revoke(self, provider: Provider, token: str) -> None:
        """Raises ProviderRevokeError."""
        ...

    def call(self, provider: Provider, operation: str, access_token: str,
             payload: dict[str, object]) -> ProviderResult: ...


class FakeProviderOAuth:
    """The only enabled ProviderOAuthPort (AICL_PROVIDER_MODE=fake). No network call.

    Contract: authorization URL points at the in-app `/fake-provider/authorize` page (registered only in the
    test and development compositions); accepts codes `fake-code-<scenario>`; scriptable to grant fewer scopes,
    fail a refresh or fail a revoke; records every call (values redacted) for assertions.
    """

    def __init__(self, *, grant_scopes: tuple[str, ...] | None = None, fail_refresh: bool = False,
                 fail_revoke: bool = False) -> None:
        self.grant_scopes = grant_scopes
        self.fail_refresh = fail_refresh
        self.fail_revoke = fail_revoke
        self.calls: list[tuple[str, str]] = []  # (method, provider) only; never a token or code

    def authorization_url(self, provider, scopes, state, code_challenge, redirect_uri):
        raise NotImplementedError(NOT_IMPLEMENTED)

    def exchange_code(self, provider, code, code_verifier, redirect_uri):
        raise NotImplementedError(NOT_IMPLEMENTED)

    def refresh(self, provider, refresh_token):
        raise NotImplementedError(NOT_IMPLEMENTED)

    def revoke(self, provider, token):
        raise NotImplementedError(NOT_IMPLEMENTED)

    def call(self, provider, operation, access_token, payload):
        raise NotImplementedError(NOT_IMPLEMENTED)


class InMemorySecretStore:
    """Minimal fake SecretStore (no encryption; test composition only). Behavior is implemented in slice 2 by
    the AES-256-GCM store; this stub keeps the port importable and failing on use."""

    def put(self, owner_id, connection_id, field, plaintext):
        raise NotImplementedError(NOT_IMPLEMENTED)

    def get(self, secret_ref, owner_id, connection_id):
        raise NotImplementedError(NOT_IMPLEMENTED)

    def destroy(self, secret_ref):
        raise NotImplementedError(NOT_IMPLEMENTED)


class CredentialBroker(Protocol):
    """The only component that sees credentials. Re-checks attachment active and connection `active`
    (connection_unavailable), re-authorizes the endpoint, reads the secret, refreshes an expired token
    (invalid_grant => reauthorization_required), applies it in its own outbound call and returns only a status
    and a bounded redacted summary. Errors: connection_unavailable, secret_unavailable, provider_error,
    endpoint_denied (mapped to denied/unavailable without detail)."""

    def call(self, authorized_work: object, operation: str) -> ProviderResult: ...


class ConnectionService(Protocol):
    """Connections, OAuth and revocation. begin_oauth/callback use `state` (sha256 stored, single use, 600 s),
    S256 PKCE and the exact requested scopes; any mismatch, replay, expiry, provider error or scope shortfall
    creates no connection. revoke_connection is idempotent: transaction A (status, detach, gate, audit), the
    provider revoke outside any transaction, transaction B (destroy secret, secret_ref=None, status)."""

    def begin_oauth(self, auth: object, provider: Provider, capabilities: tuple[str, ...]) -> str: ...

    def complete_oauth(self, auth: object, state: str, code: str) -> object: ...

    def revoke_connection(self, auth: object, connection_id: str) -> object: ...


class RevocationSweeper(Protocol):
    """STARTUP_HOOKS entry (runs before the HoldReconciler): destroys the secrets of every revoked connection
    that still has one and records provider_revoke_status=failed. `run_once()` for tests; a failure fails startup."""

    def run_once(self) -> None: ...

"""SecretStore, ProviderOAuthPort, CredentialBroker and their fakes (connection-network-policy/technical.md).

Contract stubs: signatures, errors and recording fakes only. Only the broker and the revocation path hold a
SecretStore; the web layer, chat and executor never import it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlencode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aicl.connections.models import CAPABILITY_SCOPES, Provider, ProviderResult, TokenSet  # noqa: F401
from aicl.db import to_iso


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


class ProviderGrantError(Exception):
    """refresh failed with invalid_grant: the owner must reauthorize."""


class ProviderExchangeError(Exception):
    """code exchange failed or the provider returned an error."""


FAR_FUTURE = datetime(2100, 1, 1, tzinfo=timezone.utc)


class FakeProviderOAuth:
    """The only enabled ProviderOAuthPort (AICL_PROVIDER_MODE=fake). No network call.

    Authorization URL points at the in-app `/fake-provider/authorize` page (registered only in the test and
    development compositions); accepts codes `fake-code-<scenario>`; scriptable to grant fewer scopes, fail a
    refresh or fail a revoke; records every call (method, provider only) for assertions. Tokens it issues
    expire "far in the future": the connection service caps their lifetime from its own clock.
    """

    def __init__(self, *, grant_scopes: tuple[str, ...] | None = None, fail_refresh: bool = False,
                 fail_revoke: bool = False) -> None:
        self.grant_scopes = grant_scopes
        self.fail_refresh = fail_refresh
        self.fail_revoke = fail_revoke
        self.calls: list[tuple[str, str]] = []  # (method, provider) only; never a token or code
        self._scopes_by_challenge: dict[str, tuple[str, ...]] = {}

    def authorization_url(self, provider, scopes, state, code_challenge, redirect_uri):
        self.calls.append(("authorization_url", provider))
        self._scopes_by_challenge[code_challenge] = tuple(scopes)
        query = urlencode({"provider": provider, "state": state, "code_challenge": code_challenge,
                           "code_challenge_method": "S256", "redirect_uri": redirect_uri,
                           "scope": " ".join(scopes), "response_type": "code"})
        return f"/fake-provider/authorize?{query}"

    def exchange_code(self, provider, code, code_verifier, redirect_uri):
        self.calls.append(("exchange", provider))
        if not code.startswith("fake-code-") or code == "fake-code-error":
            raise ProviderExchangeError("exchange failed")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
        requested = self._scopes_by_challenge.get(challenge)
        if requested is None:
            raise ProviderExchangeError("pkce verification failed")
        granted = self.grant_scopes if self.grant_scopes is not None else requested
        return TokenSet("at-" + secrets.token_urlsafe(18), "rt-" + secrets.token_urlsafe(18), FAR_FUTURE,
                        tuple(granted))

    def refresh(self, provider, refresh_token):
        self.calls.append(("refresh", provider))
        if self.fail_refresh:
            raise ProviderGrantError("invalid_grant")
        return TokenSet("at-" + secrets.token_urlsafe(18), refresh_token, FAR_FUTURE, ())

    def revoke(self, provider, token):
        self.calls.append(("revoke", provider))
        if self.fail_revoke:
            raise ProviderRevokeError("provider revoke failed")

    def call(self, provider, operation, access_token, payload):
        self.calls.append(("call", provider))
        return ProviderResult("ok", {"provider": provider, "operation": operation})


class AesGcmSecretStore:
    """AES-256-GCM SecretStore. AAD `owner_id|connection_id|field`, random 96-bit nonce per value. Persists to
    `secret_blob` when a Database is given, else in memory (tests/seam). `destroy` overwrites the ciphertext."""

    _MEMORY: dict[str, dict] = {}

    def __init__(self, key: bytes, db=None) -> None:  # db: a Database (or LazyDatabase) to persist into
        if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
            raise SecretUnavailable("secret key must be 32 bytes")
        self._aead = AESGCM(bytes(key))
        self._db = db
        self._mem = AesGcmSecretStore._MEMORY  # shared so a wrong key on the same ref fails to decrypt

    @staticmethod
    def _aad(owner_id: str, connection_id: str, field: str) -> bytes:
        return f"{owner_id}|{connection_id}|{field}".encode()

    def put(self, owner_id, connection_id, field, plaintext):
        nonce, ref = os.urandom(12), "sec_" + secrets.token_urlsafe(24)
        ciphertext = self._aead.encrypt(nonce, bytes(plaintext), self._aad(owner_id, connection_id, field))
        if self._db is None:
            self._mem[ref] = {"nonce": nonce, "ciphertext": ciphertext, "field": field, "destroyed": False}
        else:
            with self._db.transaction() as conn:
                conn.execute("INSERT INTO secret_blob (ref, field, nonce, ciphertext) VALUES (?,?,?,?)",
                             (ref, field, nonce, ciphertext))
        return ref

    def _load(self, ref: str):
        if self._db is None:
            item = self._mem.get(ref)
            if item is None or item["destroyed"]:
                raise SecretUnavailable("secret unavailable")
            return item["nonce"], item["ciphertext"], item["field"]
        try:
            with self._db.reader() as conn:
                row = conn.execute("SELECT field, nonce, ciphertext, destroyed_at FROM secret_blob WHERE ref = ?",
                                   (ref,)).fetchone()
        except Exception as exc:
            raise SecretUnavailable("secret unavailable") from exc
        if row is None or row["destroyed_at"] is not None:
            raise SecretUnavailable("secret unavailable")
        return bytes(row["nonce"]), bytes(row["ciphertext"]), row["field"]

    def get(self, secret_ref, owner_id, connection_id):
        nonce, ciphertext, field = self._load(secret_ref)
        try:
            return self._aead.decrypt(nonce, ciphertext, self._aad(owner_id, connection_id, field))
        except Exception as exc:  # wrong key, wrong owner/connection, corruption: never fall back
            raise SecretUnavailable("secret unavailable") from exc

    def destroy(self, secret_ref):
        if self._db is None:
            item = self._mem.get(secret_ref)
            if item is not None:
                item.update(nonce=os.urandom(12), ciphertext=os.urandom(32), destroyed=True)
            return
        with self._db.transaction() as conn:
            conn.execute("UPDATE secret_blob SET ciphertext = ?, nonce = ?, destroyed_at = ? WHERE ref = ? "
                         "AND destroyed_at IS NULL", (os.urandom(32), os.urandom(12),
                                                      to_iso(datetime.now(timezone.utc)), secret_ref))


class InMemorySecretStore(AesGcmSecretStore):
    """Test-composition SecretStore: the same AES-256-GCM store held in memory with a random key."""

    def __init__(self) -> None:
        super().__init__(os.urandom(32))


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

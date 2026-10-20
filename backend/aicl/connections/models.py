"""Connection, ConnectionAttachment, OAuthState, TokenSet, ProviderResult (connection-network-policy/technical.md).

`secret_ref` is an opaque identifier; the credential value is never part of any model, result, audit event or log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Provider = Literal["gmail", "reddit"]
ConnectionStatus = Literal["active", "reauthorization_required", "revoked"]
ProviderRevokeStatus = Literal["not_applicable", "succeeded", "failed"]

# capability -> (provider, required OAuth scope); `inference` and `network.fetch` have no provider.
CAPABILITY_SCOPES: dict[str, tuple[Provider, str]] = {
    "gmail.read": ("gmail", "https://www.googleapis.com/auth/gmail.readonly"),
    "gmail.send": ("gmail", "https://www.googleapis.com/auth/gmail.send"),
    "reddit.read": ("reddit", "read"),
    "reddit.post": ("reddit", "submit"),
}
# Broker operation ids.
PROVIDER_OPERATIONS: tuple[str, ...] = (
    "gmail.messages.list", "gmail.messages.send", "reddit.listing.read", "reddit.submit",
)
SECRET_FIELDS: tuple[str, ...] = ("access_token", "refresh_token", "expires_at")


@dataclass(frozen=True)
class Connection:
    id: str
    owner_id: str
    tenant_id: str
    provider: Provider
    display_name: str  # 1..80 characters chosen by the owner; no provider account identifier
    status: ConnectionStatus
    granted_scopes: tuple[str, ...]
    secret_ref: str | None  # None once revoked
    provider_revoke_status: ProviderRevokeStatus
    created_at: datetime
    revoked_at: datetime | None
    version: int


@dataclass(frozen=True)
class ConnectionAttachment:
    id: str
    instance_id: str
    capability: str
    connection_id: str
    owner_id: str
    tenant_id: str
    created_at: datetime
    detached_at: datetime | None  # at most one active attachment per (instance_id, capability)


@dataclass(frozen=True)
class OAuthState:
    state_hash: str  # sha256 of the 32-byte URL-safe state
    owner_id: str
    session_id: str
    provider: Provider
    scopes: tuple[str, ...]
    pkce_verifier_ciphertext: bytes
    created_at: datetime
    expires_at: datetime  # created_at + 600 seconds; single use
    used_at: datetime | None


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    granted_scopes: tuple[str, ...]

    def __repr__(self) -> str:  # never render credentials
        return "TokenSet(<redacted>)"


@dataclass(frozen=True)
class ProviderResult:
    status: str
    response_summary: dict[str, object]  # bounded and redacted


@dataclass(frozen=True)
class RevokeResult:
    connection: Connection
    detached_instance_ids: tuple[str, ...]
    provider_revoke_status: ProviderRevokeStatus

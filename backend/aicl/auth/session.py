"""SessionAuthProvider and the sign-in service contract (aicl-experience/technical.md, owner E11-3).

Signatures and docstrings only. Tables (migration owned by E11-3, not created here):
`owner (id, email_hash, created_at)`, `magic_link (token_hash, email_hash, created_at, expires_at, used_at,
requested_ip_hash)`, `session (id_hash, owner_id, created_at, expires_at, revoked_at)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from aicl.control.auth import AuthContext

NOT_IMPLEMENTED = "E11-3 behavior is not implemented (contract stub)"
SESSION_COOKIE = "aicl_session"
GENERIC_LINK_SENT = "If the address can receive mail, a link is on its way"


@dataclass(frozen=True)
class SignedInSession:
    """Result of a successful verification: the raw cookie value is returned once and never stored."""

    cookie_value: str
    max_age_seconds: int
    context: AuthContext


class SignInService(Protocol):
    def normalize_email(self, email: str) -> str | None:
        """Trim, lowercase; None unless at most 254 characters with exactly one `@`."""
        ...

    def email_hash(self, normalized_email: str) -> str:
        """HMAC-SHA256(AICL_IDENTITY_HMAC_KEY, email), hex. Never the session secret."""
        ...

    def ip_hash(self, client_ip: str) -> str:
        """HMAC-SHA256(ip_subkey, ip) with ip_subkey = HMAC-SHA256(identity key, "aicl-ip-hash-v1")."""
        ...

    def request_link(self, email: str, client_ip: str) -> None:
        """Same outcome for known, unknown, invalid, rate-limited and send-failed requests (no leak).
        Rate limit 5 per email hash and 20 per IP hash per hour; at most one `auth.link_rate_limited`
        event per window (null tenant/owner, allow-listed details only)."""
        ...

    def verify(self, token: str, previous_cookie: str | None) -> SignedInSession | None:
        """Single-use conditional update (`used_at IS NULL AND expires_at > now`); rotates the prior session,
        creates the owner on first sign-in (owner_id == tenant_id), appends `auth.signed_in`; unknown, expired
        and used tokens append `auth.link_rejected` and return None."""
        ...

    def logout(self, auth: AuthContext) -> None:
        """Sets session.revoked_at and appends `auth.signed_out`."""
        ...


class SessionAuthProvider:
    """Real `AuthProvider`: resolves the hashed `aicl_session` cookie; revoked or expired gives None."""

    def __init__(self, service: SignInService) -> None:
        self.service = service

    def resolve(self, headers_and_cookies: Mapping[str, str]) -> AuthContext | None:
        raise NotImplementedError(NOT_IMPLEMENTED)


class UnimplementedSignInService:
    """Placeholder service whose every operation raises, so tests can assert behavior, not imports."""

    def normalize_email(self, email: str) -> str | None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def email_hash(self, normalized_email: str) -> str:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def ip_hash(self, client_ip: str) -> str:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def request_link(self, email: str, client_ip: str) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def verify(self, token: str, previous_cookie: str | None) -> SignedInSession | None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def logout(self, auth: AuthContext) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

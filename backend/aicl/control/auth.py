"""AuthContext, AuthProvider and FixedAuthProvider (technical.md "AuthContext", owner E11-1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol


@dataclass(frozen=True)
class AuthContext:
    """Created only by an AuthProvider. MVP rule: tenant_id == owner_id (both UUID4 strings)."""

    owner_id: str
    tenant_id: str
    session_id: str
    expires_at: datetime
    display_name: str | None = None  # Cosmetic label only; never an identity or authorization key.


class AuthProvider(Protocol):
    def resolve(self, headers_and_cookies: Mapping[str, str]) -> AuthContext | None:
        """Return the context for the request's session cookie, or None (unauthenticated)."""
        ...


class FixedAuthProvider:
    """Test double: returns configured contexts for fixture cookie values.

    `contexts` maps an `aicl_session` cookie value to the AuthContext it resolves to.
    An unknown or missing cookie, or an expired context, resolves to None.
    """

    def __init__(self, contexts: Mapping[str, AuthContext]) -> None:
        self.contexts = dict(contexts)

    def resolve(self, headers_and_cookies: Mapping[str, str]) -> AuthContext | None:
        context = self.contexts.get(headers_and_cookies.get("aicl_session", ""))
        if context is None or context.expires_at <= datetime.now(timezone.utc):
            return None
        return context

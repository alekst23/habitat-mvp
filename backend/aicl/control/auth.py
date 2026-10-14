"""AuthContext, AuthProvider and FixedAuthProvider (technical.md "AuthContext", owner E11-1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol


@dataclass(frozen=True)
class AuthContext:
    """Created only by an AuthProvider. MVP rule: tenant_id == owner_id (both UUID4 strings)."""

    owner_id: str
    tenant_id: str
    session_id: str
    expires_at: datetime


class AuthProvider(Protocol):
    def resolve(self, headers_and_cookies: Mapping[str, str]) -> AuthContext | None:
        """Return the context for the request's session cookie, or None (unauthenticated)."""
        ...


class FixedAuthProvider:
    """Test double: returns configured contexts for fixture cookie values (to be implemented).

    `contexts` maps an `aicl_session` cookie value to the AuthContext it resolves to.
    An unknown or missing cookie, or an expired context, must resolve to None.
    """

    def __init__(self, contexts: Mapping[str, AuthContext]) -> None:
        self.contexts = dict(contexts)

    def resolve(self, headers_and_cookies: Mapping[str, str]) -> AuthContext | None:
        raise NotImplementedError("FixedAuthProvider.resolve is not implemented (E11-1)")

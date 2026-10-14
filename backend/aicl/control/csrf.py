"""CsrfVerifier, FixedCsrfVerifier and the shared `require_csrf` dependency (owner E11-1)."""

from __future__ import annotations

from typing import Callable, Protocol

from aicl.control.auth import AuthContext


class CsrfVerifier(Protocol):
    def token_for(self, session_id: str) -> str: ...

    def verify(self, auth: AuthContext, submitted_token: str | None, origin: str | None) -> bool:
        """Constant-time comparison; when `origin` is present it must equal AICL_PUBLIC_BASE_URL."""
        ...


class FixedCsrfVerifier:
    """Fixed fake: accepts one configured token only for the seeded fixture sessions, else False."""

    def __init__(self, token: str, fixture_session_ids: frozenset[str], public_base_url: str) -> None:
        self.token = token
        self.fixture_session_ids = fixture_session_ids
        self.public_base_url = public_base_url

    def token_for(self, session_id: str) -> str:
        raise NotImplementedError("FixedCsrfVerifier.token_for is not implemented (E11-1)")

    def verify(self, auth: AuthContext, submitted_token: str | None, origin: str | None) -> bool:
        raise NotImplementedError("FixedCsrfVerifier.verify is not implemented (E11-1)")


def require_csrf(*args: object, **kwargs: object) -> Callable[..., object]:
    """Shared FastAPI dependency used by every non-GET route; rejects with the taxonomy's error.

    Stub: the real dependency resolves AppContext.auth_provider/csrf_verifier from the request.
    """
    raise NotImplementedError("require_csrf is not implemented (E11-1)")

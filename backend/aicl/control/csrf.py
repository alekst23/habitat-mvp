"""CsrfVerifier, FixedCsrfVerifier and the shared `require_csrf` dependency (owner E11-1)."""

from __future__ import annotations

import hmac
from typing import Callable, Protocol

from fastapi import Request

from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError


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
        return self.token

    def verify(self, auth: AuthContext, submitted_token: str | None, origin: str | None) -> bool:
        if auth.session_id not in self.fixture_session_ids or not submitted_token:
            return False
        if origin is not None and origin.rstrip("/") != self.public_base_url.rstrip("/"):
            return False
        return hmac.compare_digest(submitted_token.encode(), self.token.encode())


def require_csrf(ctx: object) -> Callable[..., object]:
    """Shared FastAPI dependency factory for every non-GET route. `ctx` is the AppContext; the
    dependency authenticates the session cookie, then checks `X-CSRF-Token` and `Origin`."""
    def dependency(request: Request) -> AuthContext:
        auth = ctx.auth_provider.resolve(dict(request.cookies))
        if auth is None:
            raise AiclError("unauthenticated", "sign in required")
        if not ctx.csrf_verifier.verify(auth, request.headers.get("x-csrf-token"), request.headers.get("origin")):
            raise AiclError("denied", "invalid CSRF token", reason="csrf_failed")
        return auth

    return dependency

"""HmacCsrfVerifier (aicl-experience/technical.md "CSRF", owner E11-3): the only production CsrfVerifier."""

from __future__ import annotations

from aicl.control.auth import AuthContext

NOT_IMPLEMENTED = "E11-3 behavior is not implemented (contract stub)"


class HmacCsrfVerifier:
    """Implements the E11-1 `CsrfVerifier` Protocol: token = HMAC-SHA256(AICL_SESSION_SECRET, session_id),
    constant-time compare; when `origin` is present it must equal AICL_PUBLIC_BASE_URL. Routes never call it
    directly; they use the shared E11-1 `require_csrf` dependency."""

    def __init__(self, session_secret: str, public_base_url: str) -> None:
        self.session_secret = session_secret
        self.public_base_url = public_base_url

    def token_for(self, session_id: str) -> str:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def verify(self, auth: AuthContext, submitted_token: str | None, origin: str | None) -> bool:
        raise NotImplementedError(NOT_IMPLEMENTED)

"""E11-3 test seam: the only place tests learn how to build the sign-in service.

The committed stubs fix signatures, not constructors. The implementation phase edits only the body of
`sign_in_service`. Until then it returns the stub whose every operation raises NotImplementedError, so a
test fails at its first call (the intended assertion point), never at import or collection.
"""

from __future__ import annotations

IDENTITY_KEY = "test-identity-hmac-key-" + "i" * 20
SESSION_SECRET = "test-session-secret-" + "s" * 20
PUBLIC_BASE_URL = "http://127.0.0.1:4173"


def sign_in_service(env, sender, *, identity_key: str = IDENTITY_KEY, session_secret: str = SESSION_SECRET,
                    public_base_url: str = PUBLIC_BASE_URL, link_ttl_seconds: int = 900,
                    session_ttl_seconds: int = 28800):
    """-> SignInService (aicl.auth.session) over env.db/env.clock/env.audit that hands links to `sender`.

    `sender` is a CaptureMagicLinkSender. The service builds each link as
    f"{public_base_url}/auth/verify?token=<token>".
    """
    from aicl.auth.session import SqliteSignInService
    return SqliteSignInService(env.db, env.clock, env.audit, sender, identity_key=identity_key,
                               public_base_url=public_base_url, link_ttl_seconds=link_ttl_seconds,
                               session_ttl_seconds=session_ttl_seconds)

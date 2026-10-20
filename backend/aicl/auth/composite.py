"""Composite auth (O-2): real `aicl_session` sessions resolve through SessionAuthProvider/HmacCsrfVerifier; seeded
fixture sessions (test composition only) keep resolving through the E11-1 fixed doubles."""

from __future__ import annotations

from typing import Mapping

from aicl.control.auth import AuthContext, AuthProvider, FixedAuthProvider
from aicl.control.csrf import CsrfVerifier, FixedCsrfVerifier


class CompositeAuthProvider:
    def __init__(self, real: AuthProvider, fixed: FixedAuthProvider) -> None:
        self.real, self.fixed = real, fixed

    @property
    def contexts(self) -> dict[str, AuthContext]:
        return self.fixed.contexts

    def resolve(self, headers_and_cookies: Mapping[str, str]) -> AuthContext | None:
        return self.fixed.resolve(headers_and_cookies) or self.real.resolve(headers_and_cookies)


class CompositeCsrfVerifier:
    def __init__(self, real: CsrfVerifier, fixed: FixedCsrfVerifier) -> None:
        self.real, self.fixed = real, fixed

    @property
    def fixture_session_ids(self) -> frozenset[str]:
        return self.fixed.fixture_session_ids

    @fixture_session_ids.setter
    def fixture_session_ids(self, value: frozenset[str]) -> None:
        self.fixed.fixture_session_ids = value

    def _is_fixture(self, session_id: str) -> bool:
        return session_id in self.fixed.fixture_session_ids

    def token_for(self, session_id: str) -> str:
        return (self.fixed if self._is_fixture(session_id) else self.real).token_for(session_id)

    def verify(self, auth: AuthContext, submitted_token: str | None, origin: str | None) -> bool:
        return (self.fixed if self._is_fixture(auth.session_id) else self.real).verify(auth, submitted_token, origin)

"""SessionAuthProvider and the sign-in service contract (aicl-experience/technical.md, owner E11-3).

Signatures and docstrings only. Tables (migration owned by E11-3, not created here):
`owner (id, email_hash, created_at)`, `magic_link (token_hash, email_hash, created_at, expires_at, used_at,
requested_ip_hash)`, `session (id_hash, owner_id, created_at, expires_at, revoked_at)`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping, Protocol

from aicl.control.audit import AuditEvent
from aicl.control.auth import AuthContext
from aicl.db import from_iso, to_iso

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

    def resolve_session(self, cookie: str) -> AuthContext | None:
        """Hashed-cookie lookup; revoked or expired gives None."""
        ...


class SessionAuthProvider:
    """Real `AuthProvider`: resolves the hashed `aicl_session` cookie; revoked or expired gives None."""

    def __init__(self, service: SignInService) -> None:
        self.service = service

    def resolve(self, headers_and_cookies: Mapping[str, str]) -> AuthContext | None:
        cookie = headers_and_cookies.get(SESSION_COOKIE)
        if not cookie:
            return None
        return self.service.resolve_session(cookie)


LINK_LIMIT_PER_EMAIL = 5
LINK_LIMIT_PER_IP = 20
WINDOW_SECONDS = 3600
PREFIX = 12


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class SqliteSignInService:
    """Magic-link sign-in over SQLite. The address is held in memory only for the sender call."""

    def __init__(self, db, clock, audit, sender, *, identity_key: str, public_base_url: str,
                 link_ttl_seconds: int = 900, session_ttl_seconds: int = 28800) -> None:
        self.db, self.clock, self.audit, self.sender = db, clock, audit, sender
        self._identity_key = identity_key.encode()
        self._ip_subkey = hmac.new(self._identity_key, b"aicl-ip-hash-v1", hashlib.sha256).digest()
        self.public_base_url = public_base_url.rstrip("/")
        self.link_ttl = link_ttl_seconds
        self.session_ttl = session_ttl_seconds

    def normalize_email(self, email: str) -> str | None:
        value = (email or "").strip().lower()
        if not value or len(value) > 254 or value.count("@") != 1:
            return None
        return value

    def email_hash(self, normalized_email: str) -> str:
        return hmac.new(self._identity_key, normalized_email.encode(), hashlib.sha256).hexdigest()

    def ip_hash(self, client_ip: str) -> str:
        return hmac.new(self._ip_subkey, client_ip.encode(), hashlib.sha256).hexdigest()

    def _window_start(self, now) -> str:
        epoch = int(now.timestamp())
        return to_iso(now.fromtimestamp(epoch - epoch % WINDOW_SECONDS, tz=now.tzinfo))

    def _limited(self, conn, scope: str, key_hash: str, column: str, limit: int, window: str, now) -> bool:
        queries = {
            "email_hash": "SELECT count(*) FROM magic_link WHERE email_hash = ? AND created_at >= ?",
            "requested_ip_hash": "SELECT count(*) FROM magic_link WHERE requested_ip_hash = ? AND created_at >= ?",
        }
        count = conn.execute(queries[column], (key_hash, window)).fetchone()[0]
        if count < limit:
            return False
        fresh = conn.execute("INSERT OR IGNORE INTO link_rate_window (scope, key_hash, window_start) VALUES (?,?,?)",
                             (scope, key_hash, window)).rowcount
        if fresh:  # one event per window; the log is append-only so `count` is fixed here
            details = {"reason_code": "rate_limit", "count": count}
            if scope == "email":
                details["email_hash_prefix"] = key_hash[:PREFIX]
            self.audit.append(conn, AuditEvent("auth.link_rate_limited", "system", "denied", details=details))
        return True

    def request_link(self, email: str, client_ip: str) -> None:
        normalized = self.normalize_email(email)
        if normalized is None:
            return None
        email_hash, ip_hash = self.email_hash(normalized), self.ip_hash(client_ip or "unknown")
        token = secrets.token_urlsafe(32)
        with self.db.transaction() as conn:
            now = self.clock.now()
            window = self._window_start(now)
            if (self._limited(conn, "email", email_hash, "email_hash", LINK_LIMIT_PER_EMAIL, window, now)
                    or self._limited(conn, "ip", ip_hash, "requested_ip_hash", LINK_LIMIT_PER_IP, window, now)):
                return None
            conn.execute("INSERT INTO magic_link (token_hash, email_hash, created_at, expires_at, requested_ip_hash) "
                         "VALUES (?,?,?,?,?)", (_sha256(token), email_hash, to_iso(now),
                                                to_iso(now + timedelta(seconds=self.link_ttl)), ip_hash))
        try:
            self.sender.send(normalized, f"{self.public_base_url}/auth/verify?token={token}")
        except Exception:  # delivery failure is silent to the requester (same 202 body)
            pass
        return None

    def _reject(self, conn, token_hash: str, reason: str) -> None:
        self.audit.append(conn, AuditEvent("auth.link_rejected", "system", "denied", details={
            "reason_code": reason, "token_hash_prefix": token_hash[:PREFIX]}))

    def verify(self, token: str, previous_cookie: str | None) -> SignedInSession | None:
        token_hash = _sha256(token or "")
        with self.db.transaction() as conn:
            now = self.clock.now()
            claimed = conn.execute("UPDATE magic_link SET used_at = ? WHERE token_hash = ? AND used_at IS NULL "
                                   "AND expires_at > ?", (to_iso(now), token_hash, to_iso(now))).rowcount
            row = conn.execute("SELECT * FROM magic_link WHERE token_hash = ?", (token_hash,)).fetchone()
            if not claimed:
                reason = "unknown" if row is None else "used" if row["used_at"] is not None else "expired"
                self._reject(conn, token_hash, reason)
                return None
            owner = conn.execute("SELECT id FROM owner WHERE email_hash = ?", (row["email_hash"],)).fetchone()
            if owner is None:
                owner_id = str(uuid.uuid4())
                conn.execute("INSERT INTO owner (id, email_hash, created_at) VALUES (?,?,?)",
                             (owner_id, row["email_hash"], to_iso(now)))
            else:
                owner_id = owner["id"]
            if previous_cookie:
                conn.execute("UPDATE session SET revoked_at = ? WHERE id_hash = ? AND revoked_at IS NULL",
                             (to_iso(now), _sha256(previous_cookie)))
            cookie = secrets.token_urlsafe(32)
            expires = now + timedelta(seconds=self.session_ttl)
            conn.execute("INSERT INTO session (id_hash, owner_id, created_at, expires_at) VALUES (?,?,?,?)",
                         (_sha256(cookie), owner_id, to_iso(now), to_iso(expires)))
            self.audit.append(conn, AuditEvent("auth.signed_in", "owner", "committed", owner_id, owner_id))
            context = AuthContext(owner_id, owner_id, _sha256(cookie), from_iso(to_iso(expires)))
            return SignedInSession(cookie, self.session_ttl, context)

    def resolve_session(self, cookie: str) -> AuthContext | None:
        with self.db.reader() as conn:
            row = conn.execute("SELECT * FROM session WHERE id_hash = ? AND revoked_at IS NULL AND expires_at > ?",
                               (_sha256(cookie), to_iso(self.clock.now()))).fetchone()
            if row is not None:
                demo = conn.execute("SELECT expires_at FROM judge_demo_workspace WHERE owner_id=?", (row["owner_id"],)).fetchone()
                if demo is not None and demo["expires_at"] <= to_iso(self.clock.now()):
                    return None
        if row is None:
            return None
        display_name = row["display_name"] if "display_name" in row.keys() else None
        return AuthContext(row["owner_id"], row["owner_id"], row["id_hash"], from_iso(row["expires_at"]), display_name)

    def logout(self, auth: AuthContext) -> None:
        with self.db.transaction() as conn:
            changed = conn.execute("UPDATE session SET revoked_at = ? WHERE id_hash = ? AND revoked_at IS NULL",
                                   (to_iso(self.clock.now()), auth.session_id)).rowcount
            if changed:
                self.audit.append(conn, AuditEvent("auth.signed_out", "owner", "committed",
                                                   auth.tenant_id, auth.owner_id))


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

    def resolve_session(self, cookie: str) -> AuthContext | None:
        raise NotImplementedError(NOT_IMPLEMENTED)

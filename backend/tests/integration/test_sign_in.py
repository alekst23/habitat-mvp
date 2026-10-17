"""E11-3 service-level proofs (F3-S2, F3-S8): magic-link TTL/single use/hash-only storage, owner stability under
session-secret rotation, rate limits with one event per window, keyed IP hash, purge, null-identity audit events
hidden from owner readers, HmacCsrfVerifier. Real SQLite and the E11-1 Env; the only fake is the email edge."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

import auth_seams
from aicl.auth.csrf import HmacCsrfVerifier
from aicl.auth.magic_link import CaptureMagicLinkSender
from aicl.auth.purge import MagicLinkPurge
from aicl.auth.session import SessionAuthProvider
from aicl.control.audit import SqliteAuditLog
from aicl.control.auth import AuthContext

EMAIL = "Owner@Example.com"
NORMALIZED = "owner@example.com"


def token_of(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def rows(env, sql: str, args: tuple = ()):
    with env.db.reader() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def events(env, event_type: str):
    return rows(env, "SELECT * FROM audit_event WHERE event_type = ? ORDER BY seq", (event_type,))


@pytest.mark.ac("E11-3.AC1", code="backend/aicl/auth/session.py:SessionAuthProvider")
def test_magic_link_is_single_use_expiring_hash_only_and_owner_stable_across_secret_rotation(build_env):
    env = build_env()
    sender = CaptureMagicLinkSender()
    service = auth_seams.sign_in_service(env, sender)
    service.request_link(EMAIL, "203.0.113.5")
    link = sender.last_for(NORMALIZED)
    assert link and link.startswith(f"{auth_seams.PUBLIC_BASE_URL}/auth/verify?token=")
    token = token_of(link)

    stored = rows(env, "SELECT * FROM magic_link")  # only hashes are stored, never the token or the address
    assert len(stored) == 1 and stored[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert stored[0]["email_hash"] == service.email_hash(NORMALIZED) == hmac.new(
        auth_seams.IDENTITY_KEY.encode(), NORMALIZED.encode(), hashlib.sha256).hexdigest()
    assert token not in repr(stored) and NORMALIZED not in repr(stored) and "203.0.113.5" not in repr(stored)

    signed = service.verify(token, None)
    assert signed is not None and signed.max_age_seconds == 28800
    assert signed.context.owner_id == signed.context.tenant_id  # owner created on first sign-in, tenant == owner
    sessions = rows(env, "SELECT * FROM session")
    assert len(sessions) == 1 and signed.cookie_value not in repr(sessions)  # cookie stored hashed only
    provider = SessionAuthProvider(service)
    assert provider.resolve({"aicl_session": signed.cookie_value}) == signed.context
    assert len(events(env, "auth.signed_in")) == 1

    assert service.verify(token, None) is None  # single use
    env.clock.advance(timedelta(seconds=1))
    service.request_link(EMAIL, "203.0.113.5")
    stale = token_of(sender.last_for(NORMALIZED))
    env.clock.advance(timedelta(seconds=901))  # past the 900 s TTL
    assert service.verify(stale, None) is None
    assert service.verify("unknown-token", None) is None
    rejected = events(env, "auth.link_rejected")
    assert [json.loads(r["details"])["reason_code"] for r in rejected] == ["used", "expired", "unknown"]
    assert all(r["tenant_id"] is None and r["owner_id"] is None for r in rejected)

    # rotating the session secret keeps the owner (identity key defines it) and the old session rotates out
    rotated = auth_seams.sign_in_service(env, sender, session_secret="rotated-session-secret-" + "r" * 20)
    rotated.request_link(EMAIL, "203.0.113.6")
    again = rotated.verify(token_of(sender.last_for(NORMALIZED)), signed.cookie_value)
    assert again is not None and again.context.owner_id == signed.context.owner_id
    assert provider.resolve({"aicl_session": signed.cookie_value}) is None

    service.logout(again.context)  # server-side invalidation
    assert provider.resolve({"aicl_session": again.cookie_value}) is None
    assert len(events(env, "auth.signed_out")) == 1

    mine = SqliteAuditLog().list_for_owner(again.context)  # pre-authentication events are never owner-readable
    assert mine and all(e.tenant_id == again.context.tenant_id for e in mine)
    assert not any(e.event_type in ("auth.link_rejected", "auth.link_rate_limited") for e in mine)


@pytest.mark.ac("E11-3.AC1", code="backend/aicl/auth/session.py:SessionAuthProvider")
def test_rate_limits_append_one_event_per_window_and_the_ip_hash_is_keyed(build_env):
    env = build_env()
    sender = CaptureMagicLinkSender()
    service = auth_seams.sign_in_service(env, sender)
    for n in range(15):  # over the 5-per-email-hash limit from varying addresses: same outcome, never raises
        assert service.request_link(EMAIL, f"198.51.100.{n}") is None
    assert len([s for s in sender.sent if s["email"] == NORMALIZED]) == 5
    limited = events(env, "auth.link_rate_limited")
    assert len(limited) == 1  # a flood appends exactly one event for the email-hash window
    event = limited[0]
    assert event["tenant_id"] is None and event["owner_id"] is None and event["actor_kind"] == "system"
    details = json.loads(event["details"])
    assert details["reason_code"] == "rate_limit" and "count" in details
    assert set(details) <= {"reason_code", "count", "email_hash_prefix"}
    assert NORMALIZED not in repr(event) and "198.51.100" not in repr(event)

    for n in range(25):  # 20 per IP hash: distinct addresses from one client address
        service.request_link(f"user{n}@example.com", "192.0.2.77")
    assert len([s for s in sender.sent if s["email"].startswith("user")]) == 20
    assert len(events(env, "auth.link_rate_limited")) == 2  # exactly one more, for the IP-hash window

    env.clock.advance(timedelta(seconds=3601))  # a new window sends again
    service.request_link(EMAIL, "198.51.100.1")
    assert len([s for s in sender.sent if s["email"] == NORMALIZED]) == 6

    subkey = hmac.new(auth_seams.IDENTITY_KEY.encode(), b"aicl-ip-hash-v1", hashlib.sha256).digest()
    assert service.ip_hash("198.51.100.0") == hmac.new(subkey, b"198.51.100.0", hashlib.sha256).hexdigest()
    assert service.ip_hash("192.0.2.77") != hashlib.sha256(b"192.0.2.77").hexdigest()  # keyed, not plain SHA-256
    stored = {r["requested_ip_hash"] for r in rows(env, "SELECT requested_ip_hash FROM magic_link")}
    assert service.ip_hash("192.0.2.77") in stored and "192.0.2.77" not in repr(stored)


@pytest.mark.ac("E11-3.AC1", code="backend/aicl/auth/purge.py:MagicLinkPurge")
def test_purge_deletes_only_rows_expired_for_more_than_24_hours(build_env):
    env = build_env()
    service = auth_seams.sign_in_service(env, CaptureMagicLinkSender())
    service.request_link(EMAIL, "203.0.113.5")  # created T0, expires T0+15m
    env.clock.advance(timedelta(hours=1))
    service.request_link("second@example.com", "203.0.113.5")  # created T0+1h, expires T0+1h15m
    purge = MagicLinkPurge(env.db, env.clock)
    env.clock.advance(timedelta(hours=24))  # T0+25h: first expired 24h45m ago, second 23h45m ago
    assert purge.run_once() == 1
    assert len(rows(env, "SELECT 1 FROM magic_link")) == 1
    assert purge.run_once() == 0


@pytest.mark.ac("E11-3.AC1", code="backend/aicl/auth/csrf.py:HmacCsrfVerifier")
def test_hmac_csrf_verifier_binds_the_token_to_the_session_and_checks_origin():
    verifier = HmacCsrfVerifier(auth_seams.SESSION_SECRET, auth_seams.PUBLIC_BASE_URL)
    auth = AuthContext("o", "o", "session-1", datetime(2100, 1, 1, tzinfo=timezone.utc))
    other = AuthContext("o", "o", "session-2", datetime(2100, 1, 1, tzinfo=timezone.utc))
    token = verifier.token_for("session-1")
    assert token == hmac.new(auth_seams.SESSION_SECRET.encode(), b"session-1", hashlib.sha256).hexdigest()
    assert verifier.verify(auth, token, None) and verifier.verify(auth, token, auth_seams.PUBLIC_BASE_URL)
    assert not verifier.verify(other, token, None)  # bound to the session id
    assert not verifier.verify(auth, None, None) and not verifier.verify(auth, "wrong", None)
    assert not verifier.verify(auth, token, "http://evil.example")

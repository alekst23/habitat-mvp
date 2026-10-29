"""Private-link demonstration entry with isolated, expiring owner workspaces.

This grants access only to a newly created anonymous workspace, never to an
existing named account. Sessions and subsequent CSRF checks are the normal
production implementations. Entry makes no model, payment or Render requests.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import timedelta

from aicl.auth.session import SignedInSession, _sha256
from aicl.control.audit import AuditEvent
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.control.instances import Limits
from aicl.creation.models import CreateInstanceRequest, TEMPLATE_ID_DEFAULT
from aicl.creation.operations import SqliteInstanceOperations
from aicl.creation.service import create_instance
from aicl.db import from_iso, to_iso
from aicl.workflow.ad_scenario import pocketplan_preset
from aicl.workflow.factory import workflow_service

ENTRY_COOKIE = "aicl_judge_entry"
ENTRY_TTL_SECONDS = 600
JUDGE_WORKSPACE_SECONDS = 86400
JUDGE_WORKSPACE_LIMIT = 100
JUDGE_ENTRY_LIMIT_PER_MINUTE = 10
_TOKEN = re.compile(r"^[0-9]{1,12}\.[A-Za-z0-9_-]{43}\.[0-9a-f]{64}$")


def _signature(ctx, payload: str) -> str:
    access_hash = _sha256(ctx.settings.access_link_token.get_secret_value())
    return hmac.new(ctx.settings.session_secret.encode(),
                    ("habitat-private-entry-v2:" + access_hash + ":" + payload).encode(), hashlib.sha256).hexdigest()


def entry_token(ctx) -> str:
    payload = f"{int(ctx.clock.now().timestamp()) + ENTRY_TTL_SECONDS}.{secrets.token_urlsafe(32)}"
    return payload + "." + _signature(ctx, payload)


def accept_access_link(ctx, token: str) -> str | None:
    """Exchange the configured reusable private link for a short-lived form proof."""
    configured = ctx.settings.access_link_token.get_secret_value()
    if (not ctx.settings.private_entry_enabled or not configured
            or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token) is None
            or not hmac.compare_digest(token, configured)):
        return None
    return entry_token(ctx)


def valid_entry_token(ctx, token: str | None) -> bool:
    if not ctx.settings.private_entry_enabled or not ctx.settings.access_link_token.get_secret_value():
        return False
    if not token or not _TOKEN.fullmatch(token):
        return False
    payload, signature = token.rsplit(".", 1)
    expires = int(payload.split(".", 1)[0])
    now = int(ctx.clock.now().timestamp())
    return now < expires <= now + ENTRY_TTL_SECONDS and hmac.compare_digest(signature, _signature(ctx, payload))


def verify_entry(ctx, submitted: str, cookie: str | None, origin: str | None, fetch_site: str | None) -> None:
    expected = ctx.settings.public_base_url.rstrip("/")
    if (origin != expected or fetch_site == "cross-site" or not cookie
            or not valid_entry_token(ctx, submitted) or not _TOKEN.fullmatch(cookie)
            or not hmac.compare_digest(submitted, cookie)):
        raise AiclError("denied", "Open your private access link and try again.", reason="csrf_failed")


def _sample(ctx, auth) -> None:
    preset = pocketplan_preset()
    created = create_instance(auth, CreateInstanceRequest(
        idempotency_key="judge-pocketplan-sample-v1", template_id=TEMPLATE_ID_DEFAULT,
        name="PocketPlan Marketing", instructions=preset["goal"], enabled_capabilities=frozenset({"inference"})),
        clock=ctx.clock)
    # These are configurable allowances, not funds or permission for any purchase.
    SqliteInstanceOperations(ctx.db, ctx.clock).set_limits(
        auth, created.instance.id, created.instance.version,
        Limits(250_000, 1_000_000, 100_000, 1_000_000))
    workflow = workflow_service(ctx)
    workflow.save_config(auth, created.instance.id, preset, 1)
    workflow.commerce.configure(auth, created.instance.id, True, 3000, 1)
    # A new instance remains a draft, and save_config never enables its schedule.
    # Funding requires a real, independently verified PayPal Sandbox checkout.


def start_workspace(ctx, token: str, previous_cookie: str | None, display_name: str = "") -> SignedInSession:
    """Consume one entry nonce and provision its sample atomically, or resume.

    The origin/cookie/form proof is verified by the route first. The nonce hash
    is durable so two concurrent anonymous POSTs cannot create two workspaces.
    """
    if not ctx.settings.private_entry_enabled:
        raise AiclError("not_found", "Page not found.")
    if not valid_entry_token(ctx, token):
        raise AiclError("denied", "Open your private access link and try again.", reason="csrf_failed")
    with ctx.db.transaction() as conn:
        now = ctx.clock.now()
        previous = ctx.sign_in.resolve_session(previous_cookie) if previous_cookie else None
        if previous is not None:
            # A previously authenticated named owner remains that owner if an
            # operator enables judge mode later. Entry never revokes or replaces
            # a still-valid account; expired demo owners are rejected by resolve.
            seconds = max(1, int((previous.expires_at - now).total_seconds()))
            return SignedInSession(previous_cookie, seconds, previous)
        nonce_hash = _sha256(token)
        if conn.execute("SELECT 1 FROM judge_demo_workspace WHERE entry_nonce_hash=?", (nonce_hash,)).fetchone():
            raise AiclError("conflict", "This entry has already been used. Open the demo page again.")
        if conn.execute("SELECT count(*) FROM judge_demo_workspace").fetchone()[0] >= JUDGE_WORKSPACE_LIMIT:
            raise AiclError("unavailable", "The demo has reached its workspace limit. Please try an existing workspace.")
        recent = conn.execute("SELECT count(*) FROM judge_demo_workspace WHERE created_at>?",
                              (to_iso(now - timedelta(minutes=1)),)).fetchone()[0]
        if recent >= JUDGE_ENTRY_LIMIT_PER_MINUTE:
            raise AiclError("unavailable", "The demo is busy. Please try again in a minute.")
        owner_id = str(uuid.uuid4())
        # The schema's email_hash is an opaque unique identity key. No invented
        # email or real person's address is used for an anonymous visitor.
        identity_hash = hmac.new(ctx.settings.identity_hmac_key.encode(),
                                 ("habitat-judge-owner-v1:" + owner_id).encode(), hashlib.sha256).hexdigest()
        expires = now + timedelta(seconds=min(ctx.settings.session_ttl_seconds, JUDGE_WORKSPACE_SECONDS))
        conn.execute("INSERT INTO owner(id,email_hash,created_at) VALUES (?,?,?)", (owner_id, identity_hash, to_iso(now)))
        conn.execute("INSERT INTO judge_demo_workspace(owner_id,entry_nonce_hash,created_at,expires_at) VALUES (?,?,?,?)",
                     (owner_id, nonce_hash, to_iso(now), to_iso(now + timedelta(seconds=JUDGE_WORKSPACE_SECONDS))))
        if previous_cookie:
            conn.execute("UPDATE session SET revoked_at=? WHERE id_hash=? AND revoked_at IS NULL", (to_iso(now), _sha256(previous_cookie)))
        # A short unverified label belongs to this session, never to account lookup.
        label = " ".join("".join(c for c in display_name if c.isprintable() or c.isspace()).split())[:64] or None
        cookie = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO session(id_hash,owner_id,created_at,expires_at,display_name) VALUES (?,?,?,?,?)",
                     (_sha256(cookie), owner_id, to_iso(now), to_iso(expires), label))
        auth = AuthContext(owner_id, owner_id, _sha256(cookie), from_iso(to_iso(expires)), label)
        _sample(ctx, auth)
        ctx.sign_in.audit.append(conn, AuditEvent("auth.signed_in", "owner", "committed", owner_id, owner_id,
                                                 details={"mode": "judge_demo"}))
        return SignedInSession(cookie, int((expires - now).total_seconds()), auth)

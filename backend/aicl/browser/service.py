"""Durable browser leases and encrypted session handoff, scoped to one owner/agent/site.

Returning a browser session is not a proof of account authentication. The worker
must check the requested resource and ask again if the website requires login.
There is no payment or permission grant in this broker.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import timedelta
from urllib.parse import urlparse

from aicl.browser.client import BrowserClient
from aicl.connections.ports import SecretUnavailable
from aicl.control.errors import AiclError
from aicl.db import to_iso

_LEASE_STATES = ("starting", "active", "saving", "closing")
_PLAIN_KEYS = frozenset(("Enter", "Tab", "Backspace", "Delete", "Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"))
_KEYS = _PLAIN_KEYS | {"Shift+" + key for key in _PLAIN_KEYS} | {"ControlOrMeta+A", "Control+A", "Meta+A"}


def safe_origin(url):
    """Never return OAuth codes, queries, fragments or paths from login navigation."""
    try:
        parsed = urlparse(str(url))
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return ""
        port = parsed.port
        return f"{parsed.scheme}://{parsed.hostname}" + (f":{port}" if port else "")
    except ValueError:
        return ""


class BrowserBroker:
    def __init__(self, ctx, requests, client=None):
        self.ctx, self.requests = ctx, requests
        self.db, self.clock = ctx.db, ctx.clock
        self.secrets = ctx.ports.secret_store
        self.enabled = bool(ctx.settings.browser_service_url and ctx.settings.browser_service_token.get_secret_value())
        self.client = client or (BrowserClient(ctx.settings.browser_service_url,
                                              ctx.settings.browser_service_token.get_secret_value()) if self.enabled else None)

    def _available(self):
        if not self.enabled:
            raise AiclError("unavailable", "Cloud sign-in needs the private browser service to be configured.")

    def _request(self, conn, auth, request_id, *, pending=False, expected_version=None):
        row = self.requests._owned(conn, auth, request_id)
        if row["kind"] != "authentication":
            raise AiclError("invalid_transition", "This request does not require browser sign-in.")
        if expected_version is not None and (type(expected_version) is not int or row["version"] != expected_version):
            raise AiclError("conflict", "This request changed. Reload before continuing.", current_version=row["version"])
        if pending:
            self.requests.workflow._require_demo_active(conn, auth)
            job = self.requests.workflow._job(conn, auth, row["workflow_run_id"])
            if row["status"] != "pending" or job["state"] != "waiting_owner":
                raise AiclError("conflict", "This job is no longer waiting for sign-in.")
        return row

    def _expire(self, conn, auth):
        now = to_iso(self.clock.now())
        expired = conn.execute("SELECT * FROM browser_session WHERE tenant_id=? AND owner_id=? AND "
                               "((state IN ('starting','active','saving') AND expires_at<=?) OR "
                               "(state='complete' AND credential_expires_at<=?))", (auth.tenant_id, auth.owner_id, now, now)).fetchall()
        for row in expired:
            self._mark_close(conn, row, "expired")
            for child in conn.execute("SELECT * FROM browser_session WHERE parent_session_id=? AND state IN ('starting','active','saving')", (row["id"],)).fetchall():
                self._mark_close(conn, child, "expired")

    def _mark_close(self, conn, row, target):
        if row["state"] == "closing" and row["close_target"] and target != "revoked":
            target = row["close_target"]
        if row["secret_ref"]:
            self.secrets.destroy(row["secret_ref"])
        active = row["state"] in _LEASE_STATES
        # Completed sessions have already closed successfully and need no lease.
        conn.execute("UPDATE browser_session SET state=?,close_target=?,secret_ref=NULL,updated_at=? WHERE id=?",
                     ("closing" if active else target, target if active else None, to_iso(self.clock.now()), row["id"]))

    def _finish_closing(self, auth, *, instance_id, domain):
        """Retry declared closures outside SQLite; never release a lease on timeout."""
        with self.db.reader() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM browser_session WHERE tenant_id=? AND owner_id=? AND instance_id=? AND domain=? AND state='closing'", (auth.tenant_id, auth.owner_id, instance_id, domain))]
        error = None
        for row in rows:
            try:
                self._close(row["runtime_id"], key=row["id"], required=True)
                with self.db.transaction() as conn:
                    conn.execute("UPDATE browser_session SET state=close_target,close_target=NULL,updated_at=? WHERE id=? AND state='closing'", (to_iso(self.clock.now()), row["id"]))
            except AiclError as exc:
                error = exc
        if error:
            raise error

    @staticmethod
    def _latest(conn, request_id):
        return conn.execute("SELECT * FROM browser_session WHERE request_id=? AND mode='owner' ORDER BY rowid DESC LIMIT 1", (request_id,)).fetchone()

    @staticmethod
    def _view(row, request, enabled=True):
        return {"id": row["id"] if row else None, "request_id": request["id"], "request_version": request["version"],
                "state": row["state"] if row else "ready" if enabled else "unavailable",
                "domain": json.loads(request["details_json"])["domain"],
                "expires_at": row["expires_at"] if row else None,
                "credential_expires_at": row["credential_expires_at"] if row else None,
                "close_target": row["close_target"] if row else None,
                "access_verified": False, "enabled": enabled}

    def status(self, auth, request_id):
        with self.db.transaction() as conn:
            request = self._request(conn, auth, request_id)
            self._expire(conn, auth)
            instance_id, domain = request["instance_id"], json.loads(request["details_json"])["domain"]
        try:
            self._finish_closing(auth, instance_id=instance_id, domain=domain)
        except AiclError:
            pass  # A failed cleanup remains visibly closing; it is never success.
        with self.db.reader() as conn:
            request = self._request(conn, auth, request_id)
            row = self._latest(conn, request_id)
            view = self._view(row, request, self.enabled)
            if row and conn.execute("SELECT 1 FROM browser_session WHERE parent_session_id=? AND state='closing'", (row["id"],)).fetchone():
                view["state"], view["close_target"] = "closing", row["state"]
            return view

    def _close(self, runtime_id, *, key=None, required=False):
        if (runtime_id or key) and self.client:
            try:
                if key:
                    confirmed = self.client.cancel_key(key)
                    if not isinstance(confirmed, dict) or confirmed.get("closed") is not True:
                        raise AiclError("unavailable", "The browser service has not confirmed that the session is closed. Retry closing before opening another session.")
                else:
                    self.client.close(runtime_id)
            except AiclError:
                if required:
                    raise
        elif required:
            raise AiclError("unavailable", "The browser service must confirm that the previous session has closed. Retry closing when it is available.")

    def start(self, auth, request_id, expected_version):
        self._available()
        with self.db.transaction() as conn:
            request = self._request(conn, auth, request_id, pending=True, expected_version=expected_version)
            self._expire(conn, auth)
            domain = json.loads(request["details_json"])["domain"]
        self._finish_closing(auth, instance_id=request["instance_id"], domain=domain)
        with self.db.transaction() as conn:
            request = self._request(conn, auth, request_id, pending=True, expected_version=expected_version)
            self._expire(conn, auth)
            previous = self._latest(conn, request_id)
            if previous and previous["state"] in ("active", "saving"):
                return self._view(previous, request)
            if previous and previous["state"] == "starting":
                row = dict(previous)  # Same runtime idempotency key after an uncertain start.
            else:
                domain = json.loads(request["details_json"])["domain"]
                busy = conn.execute("SELECT 1 FROM browser_session WHERE tenant_id=? AND owner_id=? AND instance_id=? AND domain=? "
                                    "AND state IN ('starting','active','saving','closing')", (auth.tenant_id, auth.owner_id, request["instance_id"], domain)).fetchone()
                if busy:
                    raise AiclError("conflict", "Another browser session is using this agent's account. Finish or cancel it first.")
                now, session_id = to_iso(self.clock.now()), str(uuid.uuid4())
                expires = to_iso(self.clock.now() + timedelta(minutes=10))
                conn.execute("INSERT INTO browser_session(id,tenant_id,owner_id,instance_id,request_id,workflow_run_id,request_version,domain,mode,state,expires_at,created_at,updated_at) "
                             "VALUES (?,?,?,?,?,?,?,?, 'owner','starting',?,?,?)", (session_id, auth.tenant_id, auth.owner_id, request["instance_id"], request_id, request["workflow_run_id"], request["version"], domain, expires, now, now))
                row = dict(conn.execute("SELECT * FROM browser_session WHERE id=?", (session_id,)).fetchone())
        result = self.client.create(idempotency_key=row["id"], url="https://" + row["domain"] + "/", mode="owner", ttl_seconds=600)
        runtime_id = result.get("session_id")
        if not isinstance(runtime_id, str) or not 1 <= len(runtime_id) <= 200:
            raise AiclError("unavailable", "The browser service did not create a usable session.")
        try:
            with self.db.transaction() as conn:
                request = self._request(conn, auth, request_id, pending=True, expected_version=expected_version)
                self._expire(conn, auth)
                current = conn.execute("SELECT * FROM browser_session WHERE id=?", (row["id"],)).fetchone()
                if current["state"] not in ("starting", "active") or (current["runtime_id"] and current["runtime_id"] != runtime_id):
                    raise AiclError("conflict", "The sign-in session ended while it was opening.")
                conn.execute("UPDATE browser_session SET state='active',runtime_id=?,updated_at=? WHERE id=?", (runtime_id, to_iso(self.clock.now()), row["id"]))
                return self._view(conn.execute("SELECT * FROM browser_session WHERE id=?", (row["id"],)).fetchone(), request)
        except AiclError:
            # Persist the returned handle even if cancellation won the race.
            with self.db.transaction() as conn:
                current = conn.execute("SELECT * FROM browser_session WHERE id=?", (row["id"],)).fetchone()
                if current["state"] in _LEASE_STATES:
                    conn.execute("UPDATE browser_session SET runtime_id=? WHERE id=?", (runtime_id, row["id"]))
                    self._mark_close(conn, current, current["close_target"] or "cancelled")
            self._finish_closing(auth, instance_id=row["instance_id"], domain=row["domain"])
            raise

    def _active(self, auth, request_id):
        self._available()
        with self.db.transaction() as conn:
            request = self._request(conn, auth, request_id, pending=True)
            self._expire(conn, auth)
            row = self._latest(conn, request_id)
            if not row or row["state"] != "active" or row["request_version"] != request["version"]:
                raise AiclError("conflict", "This sign-in session is not active. Open a new session.")
            return dict(row)

    def frame(self, auth, request_id):
        row = self._active(auth, request_id)
        result = self.client.frame(row["runtime_id"])
        self._active(auth, request_id)
        image, width, height = result.get("image"), result.get("width"), result.get("height")
        try:
            valid = (isinstance(image, str) and len(image) <= 4_000_000 and bool(base64.b64decode(image, validate=True))
                     and type(width) is int and type(height) is int and 1 <= width <= 4096 and 1 <= height <= 4096)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise AiclError("unavailable", "The browser service did not return a usable view.")
        return {"image": image, "width": width, "height": height, "url": safe_origin(result.get("url", "")), "title": "Secure sign-in"}

    def input(self, auth, request_id, payload):
        if not isinstance(payload, dict) or payload.get("type") not in ("click", "text", "key", "scroll"):
            raise AiclError("validation_failed", "Choose a supported browser input.")
        allowed = {"click": {"type", "x", "y"}, "text": {"type", "text"}, "key": {"type", "key"}, "scroll": {"type", "delta_y"}}[payload["type"]]
        if set(payload) != allowed:
            raise AiclError("validation_failed", "Invalid browser input fields.")
        if payload["type"] == "click" and (type(payload["x"]) is not int or type(payload["y"]) is not int or not 0 <= payload["x"] < 1280 or not 0 <= payload["y"] < 720):
            raise AiclError("validation_failed", "Choose a point inside the browser view.")
        if payload["type"] == "text" and (not isinstance(payload["text"], str) or not 1 <= len(payload["text"]) <= 4096):
            raise AiclError("validation_failed", "Browser text must contain 1–4096 characters.")
        if payload["type"] == "key" and (not isinstance(payload["key"], str) or payload["key"] not in _KEYS):
            raise AiclError("validation_failed", "This browser key is not supported.")
        if payload["type"] == "scroll" and (type(payload["delta_y"]) is not int or not -2000 <= payload["delta_y"] <= 2000):
            raise AiclError("validation_failed", "Invalid scroll distance.")
        row = self._active(auth, request_id)
        self.client.input(row["runtime_id"], payload)
        self._active(auth, request_id)
        return {"ok": True}

    @staticmethod
    def _state_bytes(state):
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
            raise AiclError("unavailable", "The browser service did not return a reusable session.")
        try:
            data = json.dumps(state, separators=(",", ":"), allow_nan=False).encode()
        except (TypeError, ValueError):
            raise AiclError("unavailable", "The browser service returned an invalid session.") from None
        if len(data) > 2_000_000:
            raise AiclError("unavailable", "The browser session exceeds the supported size.")
        return data

    def complete(self, auth, request_id, expected_version, continuation=None):
        self._available()
        if type(expected_version) is not int or expected_version < 1:
            raise AiclError("validation_failed", "A request version is required.")
        if continuation not in (None, "now", "schedule"):
            raise AiclError("validation_failed", "Choose now or schedule for continuation.")
        with self.db.transaction() as conn:
            request = self._request(conn, auth, request_id)
            self._expire(conn, auth)
            row = self._latest(conn, request_id)
            # Safe retry after response loss; it cannot change continuation.
            if row and row["state"] == "complete" and request["status"] == "resolved" and row["request_version"] == expected_version:
                return self.requests._project(conn, auth, request)
            self._request(conn, auth, request_id, pending=True, expected_version=expected_version)
            if not row or row["request_version"] != expected_version or row["state"] not in ("active", "saving"):
                raise AiclError("conflict", "Open a sign-in session before returning it to the agent.")
            if row["state"] == "saving" and not row["secret_ref"]:
                raise AiclError("conflict", "This session is already being saved. Retry shortly or reopen after it expires.")
            row = dict(row)
            conn.execute("UPDATE browser_session SET state='saving',updated_at=? WHERE id=?", (to_iso(self.clock.now()), row["id"]))
        if not row["secret_ref"]:
            try:
                snapshot = self.client.snapshot(row["runtime_id"])
                data = self._state_bytes(snapshot.get("storage_state"))
                with self.db.transaction() as conn:
                    self._request(conn, auth, request_id, pending=True, expected_version=expected_version)
                    self._expire(conn, auth)
                    current = conn.execute("SELECT * FROM browser_session WHERE id=?", (row["id"],)).fetchone()
                    if current["state"] != "saving":
                        raise AiclError("conflict", "This browser handoff is no longer active.")
                    ref = self.secrets.put(auth.owner_id, row["id"], "browser_storage_state", data)
                    conn.execute("UPDATE browser_session SET secret_ref=?,credential_expires_at=?,updated_at=? WHERE id=?", (ref, to_iso(self.clock.now() + timedelta(hours=24)), to_iso(self.clock.now()), row["id"]))
                    row["secret_ref"] = ref
            except AiclError:
                with self.db.transaction() as conn:
                    conn.execute("UPDATE browser_session SET state='active' WHERE id=? AND state='saving' AND secret_ref IS NULL", (row["id"],))
                raise
        # The owner context must close before any worker can receive this state.
        self._close(row["runtime_id"], key=row["id"], required=True)
        with self.db.transaction() as conn:
            self._request(conn, auth, request_id, pending=True, expected_version=expected_version)
            self._expire(conn, auth)
            current = conn.execute("SELECT * FROM browser_session WHERE id=?", (row["id"],)).fetchone()
            if current["state"] != "saving" or not current["secret_ref"]:
                raise AiclError("conflict", "This sign-in session expired or was cancelled before it could be returned.")
            older = conn.execute("SELECT id,secret_ref FROM browser_session WHERE tenant_id=? AND owner_id=? AND instance_id=? AND domain=? AND mode='owner' AND state='complete' AND id<>?", (auth.tenant_id, auth.owner_id, row["instance_id"], row["domain"], row["id"])).fetchall()
            for old in older:
                if old["secret_ref"]:
                    self.secrets.destroy(old["secret_ref"])
                conn.execute("UPDATE browser_session SET state='revoked',secret_ref=NULL,updated_at=? WHERE id=?", (to_iso(self.clock.now()), old["id"]))
            conn.execute("UPDATE browser_session SET state='complete',updated_at=? WHERE id=?", (to_iso(self.clock.now()), row["id"]))
            result = self.requests.complete_browser_session(auth, request_id, row["id"], expected_version, continuation)
        if result["continuation"] == "now" and self.requests.workflow.execution_mode == "local" and self.requests.workflow.inference:
            self.requests.workflow.inference.drain(auth, result["instance_id"])
            return self.requests.get(auth, request_id)
        return result

    def cancel(self, auth, request_id):
        with self.db.transaction() as conn:
            request = self._request(conn, auth, request_id)
            self._expire(conn, auth)
            row = self._latest(conn, request_id)
            if row and row["state"] in _LEASE_STATES:
                self._mark_close(conn, row, "cancelled")
            domain = json.loads(request["details_json"])["domain"]
        self._finish_closing(auth, instance_id=request["instance_id"], domain=domain)
        return self.status(auth, request_id)

    def revoke(self, auth, session_id):
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM browser_session WHERE id=? AND tenant_id=? AND owner_id=? AND mode='owner'", (session_id, auth.tenant_id, auth.owner_id)).fetchone()
            if row is None:
                raise AiclError("not_found", "Browser session not found.")
            self._request(conn, auth, row["request_id"])
            self._mark_close(conn, row, "revoked")
            children = conn.execute("SELECT * FROM browser_session WHERE parent_session_id=? AND state IN ('starting','active','saving','closing')", (session_id,)).fetchall()
            for child in children:
                self._mark_close(conn, child, "revoked")
            if row["state"] != "revoked" and not (row["state"] == "closing" and row["close_target"] == "revoked"):
                self.requests.workflow.commerce._event(conn, auth, row["instance_id"], "commerce.policy_changed", action="browser_session_revoked", run_id=row["workflow_run_id"], confirmation_id=row["request_id"])
        self._finish_closing(auth, instance_id=row["instance_id"], domain=row["domain"])
        return self.status(auth, row["request_id"])

    def _worker_session(self, conn, auth, request_id, parent, session_id, request_version,
                        *, expected_state="active", authorize=None):
        """Recheck the grant and exclusive lease before publishing refreshed state."""
        request = self._request(conn, auth, request_id)
        self._expire(conn, auth)
        current = conn.execute("SELECT state FROM browser_session WHERE id=?", (session_id,)).fetchone()
        saved = conn.execute("SELECT state,secret_ref FROM browser_session WHERE id=?", (parent["id"],)).fetchone()
        if (request["status"] != "resolved" or request["version"] != request_version
                or not current or current["state"] != expected_state
                or not saved or saved["state"] != "complete"
                or saved["secret_ref"] != parent["secret_ref"] or not saved["secret_ref"]):
            raise AiclError("denied", "The browser session was revoked, expired or replaced.", reason="connection_unavailable")
        pending = conn.execute("SELECT 1 FROM owner_request WHERE tenant_id=? AND owner_id=? AND instance_id=? AND kind='authentication' AND status='pending' AND json_extract(details_json,'$.domain')=?", (auth.tenant_id, auth.owner_id, parent["instance_id"], parent["domain"])).fetchone()
        if pending:
            raise AiclError("denied", "This agent has a pending sign-in request for the website.", reason="connection_unavailable")
        if authorize is not None:
            authorize(conn)

    def worker_page(self, auth, request_id, workflow_run_id, url, *, authorize=None):
        """Restore and refresh state here; the worker sees page text, never cookies.

        Each page operation owns a fresh browser. Save its updated snapshot before
        closing so later operations and scheduled jobs can reuse rotated tokens.
        The machine caller supplies its current job/control check for the save
        transaction, without holding a database lock during browser I/O.
        """
        self._available()
        with self.db.transaction() as conn:
            request = self._request(conn, auth, request_id)
            self._expire(conn, auth)
            parent = self._latest(conn, request_id)
            job = self.requests.workflow._job(conn, auth, workflow_run_id)
            if request["instance_id"] != job["instance_id"]:
                raise AiclError("not_found", "This sign-in request belongs to another agent.")
            if request["status"] != "resolved" or not parent or parent["state"] != "complete" or not parent["secret_ref"]:
                raise AiclError("denied", "A current owner-provided session is required.", reason="connection_unavailable")
            pending = conn.execute("SELECT 1 FROM owner_request WHERE tenant_id=? AND owner_id=? AND instance_id=? AND kind='authentication' AND status='pending' AND json_extract(details_json,'$.domain')=?", (auth.tenant_id, auth.owner_id, parent["instance_id"], parent["domain"])).fetchone()
            if pending:
                raise AiclError("denied", "This agent has a pending sign-in request for the website.", reason="connection_unavailable")
            try:
                parsed = urlparse(url)
                allowed = parsed.scheme == "https" and parsed.hostname == parent["domain"] and parsed.port in (None, 443) and not parsed.username and not parsed.password and not parsed.fragment and "\\" not in url and not any(ord(c) < 33 for c in url)
            except (ValueError, TypeError):
                allowed = False
            if not allowed:
                raise AiclError("denied", "The worker can only reopen the requested website over HTTPS.", reason="network_denied")
            busy = conn.execute("SELECT 1 FROM browser_session WHERE tenant_id=? AND owner_id=? AND instance_id=? AND domain=? AND state IN ('starting','active','saving','closing')", (auth.tenant_id, auth.owner_id, parent["instance_id"], parent["domain"])).fetchone()
            if busy:
                raise AiclError("conflict", "The owner or another worker is currently using this website session.")
            session_id, now = str(uuid.uuid4()), to_iso(self.clock.now())
            conn.execute("INSERT INTO browser_session(id,tenant_id,owner_id,instance_id,request_id,workflow_run_id,request_version,domain,mode,parent_session_id,state,expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?, 'worker',?,'starting',?,?,?)", (session_id, auth.tenant_id, auth.owner_id, parent["instance_id"], request_id, workflow_run_id, request["version"], parent["domain"], parent["id"], to_iso(self.clock.now() + timedelta(minutes=10)), now, now))
            parent = dict(parent)
        runtime_id = None
        try:
            try:
                state = json.loads(self.secrets.get(parent["secret_ref"], auth.owner_id, parent["id"]))
            except (SecretUnavailable, ValueError):
                raise AiclError("denied", "This website session is no longer available. Request sign-in again.", reason="connection_unavailable") from None
            created = self.client.create(idempotency_key=session_id, url=url, storage_state=state, mode="worker", ttl_seconds=600)
            runtime_id = created.get("session_id")
            if not isinstance(runtime_id, str) or not 1 <= len(runtime_id) <= 200:
                raise AiclError("unavailable", "The browser service did not create a usable session.")
            with self.db.transaction() as conn:
                self._worker_session(conn, auth, request_id, parent, session_id, request["version"],
                                     expected_state="starting", authorize=authorize)
                conn.execute("UPDATE browser_session SET state='active',runtime_id=?,updated_at=? WHERE id=?", (runtime_id, to_iso(self.clock.now()), session_id))
            page = self.client.page(runtime_id)
            with self.db.transaction() as conn:
                self._worker_session(conn, auth, request_id, parent, session_id, request["version"], authorize=authorize)
            snapshot = self.client.snapshot(runtime_id)
            data = self._state_bytes(snapshot.get("storage_state"))
            try:
                with self.db.transaction() as conn:
                    self._worker_session(conn, auth, request_id, parent, session_id, request["version"], authorize=authorize)
                    # The persistent secret store joins this transaction. Either
                    # the full snapshot replaces the old one, or all writes roll
                    # back. Do not extend the owner's original access expiry.
                    ref = self.secrets.put(auth.owner_id, parent["id"], "browser_storage_state", data)
                    conn.execute("UPDATE browser_session SET secret_ref=?,updated_at=? WHERE id=?",
                                 (ref, to_iso(self.clock.now()), parent["id"]))
                    self.secrets.destroy(parent["secret_ref"])
            except SecretUnavailable:
                raise AiclError("unavailable", "The updated website session could not be saved. Retry the browser operation.") from None
            return {"url": safe_origin(page.get("url", "")), "title": str(page.get("title", ""))[:200], "text": str(page.get("text", ""))[:20000], "request_id": request_id, "access_verified": False}
        finally:
            # No page result escapes until the runtime confirms shutdown. Even
            # an unknown create outcome is cancelled by its idempotency key.
            with self.db.transaction() as conn:
                current = conn.execute("SELECT * FROM browser_session WHERE id=?", (session_id,)).fetchone()
                if runtime_id:
                    conn.execute("UPDATE browser_session SET runtime_id=? WHERE id=?", (runtime_id, session_id))
                if current["state"] in _LEASE_STATES:
                    self._mark_close(conn, current, "complete")
            self._finish_closing(auth, instance_id=parent["instance_id"], domain=parent["domain"])

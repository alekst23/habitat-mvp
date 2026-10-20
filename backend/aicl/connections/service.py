"""Connections, OAuth, revocation, credential broker and the RevocationSweeper (owner E11-2).

Only this module's broker and revocation path hold a SecretStore. No credential is ever returned, audited,
logged or echoed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import string
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from sqlite3 import Connection as SqlConnection

from aicl.clock import Clock
from aicl.control.audit import AuditEvent, SqliteAuditLog
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.control.instances import GateContext, SqliteInstanceRepository
from aicl.connections.models import (
    CAPABILITY_SCOPES, Connection, ProviderResult, RevokeResult,
)
from aicl.connections.ports import (
    ProviderGrantError, ProviderOAuthPort, SecretStore, SecretUnavailable,
)
from aicl.db import Database, from_iso, to_iso
from aicl.network.policy import FIXED_NETWORK_POLICY, Resolver, authorize_destination

OAUTH_STATE_TTL_SECONDS = 600
PROVIDER_REVOKE_TIMEOUT_SECONDS = 5
ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
CALLBACK_PATH = "/connections/oauth/callback"
_VERIFIER_ALPHABET = string.ascii_letters + string.digits + "-._~"
OPERATION_METHODS = {"gmail.messages.list": "GET", "gmail.messages.send": "POST",
                     "reddit.listing.read": "GET", "reddit.submit": "POST"}


def _row_connection(row) -> Connection:
    return Connection(
        id=row["id"], owner_id=row["owner_id"], tenant_id=row["tenant_id"], provider=row["provider"],
        display_name=row["display_name"], status=row["status"], granted_scopes=tuple(json.loads(row["granted_scopes"])),
        secret_ref=row["secret_ref"], provider_revoke_status=row["provider_revoke_status"],
        created_at=from_iso(row["created_at"]),
        revoked_at=None if row["revoked_at"] is None else from_iso(row["revoked_at"]), version=row["version"])


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _oauth_denied(code: str) -> AiclError:
    return AiclError("denied", "authorization could not be completed", reason=code)


def fetch_connection(conn: SqlConnection, auth: AuthContext, connection_id: str) -> Connection:
    row = conn.execute("SELECT * FROM connection WHERE id = ? AND tenant_id = ? AND owner_id = ?",
                       (connection_id, auth.tenant_id, auth.owner_id)).fetchone()
    if row is None:
        raise AiclError("not_found", "connection not found")
    return _row_connection(row)


class SqliteConnectionService:
    def __init__(self, db: Database, clock: Clock, oauth: ProviderOAuthPort, store: SecretStore,
                 public_base_url: str) -> None:
        self.db, self.clock, self.oauth, self.store = db, clock, oauth, store
        self.redirect_uri = public_base_url.rstrip("/") + CALLBACK_PATH
        self.audit = SqliteAuditLog(clock)
        self.instances = SqliteInstanceRepository()

    # -- OAuth ---------------------------------------------------------------------------------
    def begin_oauth(self, auth: AuthContext, provider: str, capabilities: tuple[str, ...],
                    display_name: str | None = None) -> dict:
        caps = tuple(dict.fromkeys(capabilities))
        errors = [{"field": "capabilities", "code": "unsupported_capability"}
                  for c in caps if c not in CAPABILITY_SCOPES or CAPABILITY_SCOPES[c][0] != provider]
        name = (display_name or provider.capitalize()).strip()
        if not caps or errors or not 1 <= len(name) <= 80:
            raise AiclError("validation_failed", "invalid connection request",
                            field_errors=errors or [{"field": "capabilities", "code": "required"}])
        scopes = tuple(sorted({CAPABILITY_SCOPES[c][1] for c in caps}))
        state = secrets.token_urlsafe(32)
        verifier = "".join(secrets.choice(_VERIFIER_ALPHABET) for _ in range(64))
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        ref = self.store.put(auth.owner_id, state_hash, "pkce_verifier", verifier.encode())
        now = self.clock.now()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO oauth_state (state_hash, owner_id, session_id, provider, display_name, scopes, "
                "pkce_verifier_ciphertext, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (state_hash, auth.owner_id, auth.session_id, provider, name, json.dumps(list(scopes)),
                 ref.encode(), to_iso(now), to_iso(now + timedelta(seconds=OAUTH_STATE_TTL_SECONDS))))
        url = self.oauth.authorization_url(provider, scopes, state, _s256(verifier), self.redirect_uri)
        return {"authorization_url": url}

    def _denied_with_audit(self, auth: AuthContext, code: str) -> AiclError:
        with self.db.transaction() as conn:
            self.audit.append(conn, AuditEvent("access.denied", "owner", "denied", auth.tenant_id, auth.owner_id,
                                               details={"target_kind": "oauth_state"}, reason=code))
        return _oauth_denied(code)

    def complete_oauth(self, auth: AuthContext, state: str, code: str) -> Connection:
        state_hash = hashlib.sha256(str(state).encode()).hexdigest()
        now = self.clock.now()
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM oauth_state WHERE state_hash = ?", (state_hash,)).fetchone()
        if row is None:
            raise _oauth_denied("state_unknown")
        if row["owner_id"] != auth.owner_id or row["session_id"] != auth.session_id:
            raise self._denied_with_audit(auth, "state_mismatch")
        if row["used_at"] is not None:
            raise _oauth_denied("state_used")
        if from_iso(row["expires_at"]) <= now:
            raise _oauth_denied("state_expired")
        with self.db.transaction() as conn:  # single use: marked used before the code is exchanged
            changed = conn.execute("UPDATE oauth_state SET used_at = ? WHERE state_hash = ? AND used_at IS NULL",
                                   (to_iso(now), state_hash)).rowcount
        if changed != 1:
            raise _oauth_denied("state_used")
        try:
            verifier = self.store.get(row["pkce_verifier_ciphertext"].decode(), auth.owner_id, state_hash).decode()
            self.store.destroy(row["pkce_verifier_ciphertext"].decode())
            tokens = self.oauth.exchange_code(row["provider"], code, verifier, self.redirect_uri)
        except Exception:
            raise _oauth_denied("exchange_failed") from None
        requested = tuple(json.loads(row["scopes"]))
        requested_scopes, granted_scopes = set(requested), set(tokens.granted_scopes)
        if granted_scopes != requested_scopes:
            reason = "scope_missing" if requested_scopes - granted_scopes else "scope_mismatch"
            raise AiclError("validation_failed", "granted access does not match requested access",
                            field_errors=[{"field": "scope", "code": reason}])
        connection_id = str(uuid.uuid4())
        expires = min(tokens.expires_at, now + ACCESS_TOKEN_LIFETIME)
        refs: dict[str, str] = {}
        try:
            refs["access_token"] = self.store.put(auth.owner_id, connection_id, "access_token",
                                                  tokens.access_token.encode())
            if tokens.refresh_token:
                refs["refresh_token"] = self.store.put(auth.owner_id, connection_id, "refresh_token",
                                                       tokens.refresh_token.encode())
            refs["expires_at"] = self.store.put(auth.owner_id, connection_id, "expires_at", to_iso(expires).encode())
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO connection (id, owner_id, tenant_id, provider, display_name, status, "
                    "granted_scopes, secret_ref, provider_revoke_status, created_at, version) "
                    "VALUES (?,?,?,?,?,'active',?,?,'not_applicable',?,1)",
                    (connection_id, auth.owner_id, auth.tenant_id, row["provider"], row["display_name"],
                     json.dumps(list(tokens.granted_scopes)), refs["access_token"], to_iso(now)))
                for field, ref in refs.items():
                    conn.execute("INSERT INTO connection_secret (connection_id, field, secret_ref) VALUES (?,?,?)",
                                 (connection_id, field, ref))
                self.audit.append(conn, AuditEvent(
                    "connection.created", "owner", "committed", auth.tenant_id, auth.owner_id,
                    connection_id=connection_id,
                    details={"provider": row["provider"], "connection_id": connection_id}))
                return fetch_connection(conn, auth, connection_id)
        except BaseException:
            for ref in refs.values():
                try:
                    self.store.destroy(ref)
                except Exception:
                    pass
            raise

    # -- revocation ----------------------------------------------------------------------------
    def revoke_connection(self, auth: AuthContext, connection_id: str) -> RevokeResult:
        detached: list[str] = []
        with self.db.transaction() as conn:
            current = fetch_connection(conn, auth, connection_id)
            if current.status == "revoked" and current.secret_ref is None:
                return RevokeResult(current, (), current.provider_revoke_status)
            if current.status != "revoked":
                detached = self._transaction_a(conn, auth, current)
        # 2. provider revoke outside any transaction, reading the secret once
        status = self._provider_revoke(auth, connection_id)
        # 3. transaction B
        with self.db.transaction() as conn:
            self._destroy_secrets(conn, connection_id)
            conn.execute("UPDATE connection SET secret_ref = NULL, provider_revoke_status = ? WHERE id = ?",
                         (status, connection_id))
            self.audit.append(conn, AuditEvent(
                f"connection.provider_revoke_{status}", "owner", "committed", auth.tenant_id, auth.owner_id,
                connection_id=connection_id, details={"connection_id": connection_id}))
            return RevokeResult(fetch_connection(conn, auth, connection_id), tuple(detached), status)

    def _transaction_a(self, conn: SqlConnection, auth: AuthContext, current: Connection) -> list[str]:
        now = to_iso(self.clock.now())
        conn.execute("UPDATE connection SET status = 'revoked', revoked_at = ?, version = version + 1 WHERE id = ?",
                     (now, current.id))
        attachments = conn.execute(
            "SELECT * FROM connection_attachment WHERE connection_id = ? AND detached_at IS NULL ORDER BY created_at",
            (current.id,)).fetchall()
        per_instance: dict[str, list[str]] = {}
        for attachment in attachments:
            per_instance.setdefault(attachment["instance_id"], []).append(attachment["capability"])
        conn.execute("UPDATE connection_attachment SET detached_at = ? WHERE connection_id = ? AND detached_at IS NULL",
                     (now, current.id))
        for instance_id, capabilities in per_instance.items():
            row = conn.execute("SELECT lifecycle FROM agent_instance WHERE id = ?", (instance_id,)).fetchone()
            if row["lifecycle"] == "active":
                self.instances.set_gated(conn, auth, instance_id, "connection_revoked",
                                         GateContext(tuple(sorted(capabilities)), None))
                self.audit.append(conn, AuditEvent(
                    "instance.gated", "system", "committed", auth.tenant_id, auth.owner_id, instance_id,
                    current.id, details={"denial_reason": "connection_revoked", "connection_id": current.id}))
            conn.execute("UPDATE agent_instance SET version = version + 1, updated_at = ? WHERE id = ?",
                         (now, instance_id))
        self.audit.append(conn, AuditEvent(
            "connection.revoked", "owner", "committed", auth.tenant_id, auth.owner_id, connection_id=current.id,
            details={"provider": current.provider, "connection_id": current.id}))
        return list(per_instance)

    def _secret_refs(self, conn: SqlConnection, connection_id: str) -> dict[str, str]:
        return {r["field"]: r["secret_ref"] for r in conn.execute(
            "SELECT field, secret_ref FROM connection_secret WHERE connection_id = ?", (connection_id,))}

    def _destroy_secrets(self, conn: SqlConnection, connection_id: str) -> None:
        for ref in self._secret_refs(conn, connection_id).values():
            self.store.destroy(ref)

    def _provider_revoke(self, auth: AuthContext, connection_id: str) -> str:
        with self.db.reader() as conn:
            row = conn.execute("SELECT provider FROM connection WHERE id = ?", (connection_id,)).fetchone()
            refs = self._secret_refs(conn, connection_id)
        field = "refresh_token" if "refresh_token" in refs else "access_token"
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            token = self.store.get(refs[field], auth.owner_id, connection_id).decode()
            pool.submit(self.oauth.revoke, row["provider"], token).result(timeout=PROVIDER_REVOKE_TIMEOUT_SECONDS)
            return "succeeded"
        except Exception:  # SecretUnavailable, ProviderRevokeError, timeout, KeyError: recorded as failed
            return "failed"
        finally:
            pool.shutdown(wait=False)


class SqliteRevocationSweeper:
    """STARTUP_HOOKS entry (before the HoldReconciler): destroys the secrets of every revoked connection that
    still has one and records provider_revoke_status=failed. A failure fails startup (fail closed)."""

    def __init__(self, db: Database, clock: Clock, store: SecretStore) -> None:
        self.db, self.clock, self.store = db, clock, store
        self.audit = SqliteAuditLog(clock)

    def run_once(self) -> None:
        with self.db.reader() as conn:
            pending = [dict(r) for r in conn.execute(
                "SELECT id, owner_id, tenant_id FROM connection WHERE status = 'revoked' AND secret_ref IS NOT NULL")]
        for item in pending:
            with self.db.transaction() as conn:
                for ref in [r["secret_ref"] for r in conn.execute(
                        "SELECT secret_ref FROM connection_secret WHERE connection_id = ?", (item["id"],))]:
                    self.store.destroy(ref)
                conn.execute("UPDATE connection SET secret_ref = NULL, provider_revoke_status = 'failed' "
                             "WHERE id = ?", (item["id"],))
                self.audit.append(conn, AuditEvent(
                    "connection.provider_revoke_failed", "system", "committed", item["tenant_id"], item["owner_id"],
                    connection_id=item["id"], details={"connection_id": item["id"], "reason_code": "unknown"}))

    def __call__(self, ctx: object = None) -> None:
        self.run_once()


class SqliteCredentialBroker:
    """The only component that sees credentials (besides revocation)."""

    def __init__(self, db: Database, clock: Clock, oauth: ProviderOAuthPort, store: SecretStore,
                 resolver: Resolver) -> None:
        self.db, self.clock, self.oauth, self.store, self.resolver = db, clock, oauth, store, resolver

    @staticmethod
    def _deny(reason: str) -> AiclError:
        return AiclError("denied", "the connection cannot be used", reason=reason)

    def call(self, authorized_work, operation: str) -> ProviderResult:
        method = OPERATION_METHODS.get(operation)
        if method is None:
            raise self._deny("check_unavailable")
        with self.db.reader() as conn:
            row = conn.execute(
                "SELECT a.id AS attachment_id, c.* FROM connection_attachment a JOIN connection c ON "
                "c.id = a.connection_id WHERE a.instance_id = ? AND a.capability = ? AND a.detached_at IS NULL",
                (authorized_work.instance_id, authorized_work.capability)).fetchone()
            refs = {} if row is None else self._refs(conn, row["id"])
        if row is None or row["status"] != "active" or row["secret_ref"] is None:
            raise self._deny("connection_unavailable")
        decision = authorize_destination(FIXED_NETWORK_POLICY, (), authorized_work.capability, method,
                                         authorized_work.destination or "", 0, self.resolver)
        if not decision.allowed:
            raise self._deny("network_denied")
        try:
            access = self._access_token(row, refs)
            result = self.oauth.call(row["provider"], operation, access, dict(authorized_work.payload))
        except SecretUnavailable:
            raise AiclError("unavailable", "credential store unavailable") from None
        except AiclError:
            raise
        except Exception:
            raise self._deny("check_unavailable") from None
        return ProviderResult(str(result.status), dict(result.response_summary))

    def _refs(self, conn: SqlConnection, connection_id: str) -> dict[str, str]:
        return {r["field"]: r["secret_ref"] for r in conn.execute(
            "SELECT field, secret_ref FROM connection_secret WHERE connection_id = ?", (connection_id,))}

    def _access_token(self, row, refs: dict[str, str]) -> str:
        owner, connection_id = row["owner_id"], row["id"]
        expires = from_iso(self.store.get(refs["expires_at"], owner, connection_id).decode())
        if expires > self.clock.now():
            return self.store.get(refs["access_token"], owner, connection_id).decode()
        refresh = self.store.get(refs["refresh_token"], owner, connection_id).decode() if "refresh_token" in refs else None
        try:
            if refresh is None:
                raise ProviderGrantError("no refresh token")
            tokens = self.oauth.refresh(row["provider"], refresh)
        except Exception:
            with self.db.transaction() as conn:
                conn.execute("UPDATE connection SET status = 'reauthorization_required', version = version + 1 "
                             "WHERE id = ? AND status = 'active'", (connection_id,))
            raise self._deny("connection_unavailable") from None
        new_expiry = min(tokens.expires_at, self.clock.now() + ACCESS_TOKEN_LIFETIME)
        with self.db.transaction() as conn:
            # Refresh runs outside the write transaction. Revoke or another refresh
            # may have won meanwhile; stale results must not recreate credentials.
            current = conn.execute("SELECT status, version, secret_ref FROM connection WHERE id = ?",
                                   (connection_id,)).fetchone()
            if (current is None or current["status"] != "active" or current["version"] != row["version"]
                    or current["secret_ref"] != row["secret_ref"] or self._refs(conn, connection_id) != refs):
                raise self._deny("connection_unavailable")
            for field, value in (("access_token", tokens.access_token), ("expires_at", to_iso(new_expiry))):
                new_ref = self.store.put(owner, connection_id, field, value.encode())
                old_ref = refs[field]
                conn.execute("UPDATE connection_secret SET secret_ref = ? WHERE connection_id = ? AND field = ?",
                             (new_ref, connection_id, field))
                if field == "access_token":
                    conn.execute("UPDATE connection SET secret_ref = ? WHERE id = ?", (new_ref, connection_id))
                self.store.destroy(old_ref)
        return tokens.access_token

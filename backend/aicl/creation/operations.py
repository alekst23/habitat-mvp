"""InstanceOperations and evaluate_gate_control (technical.md "Instance mutation operations", owner E11-2).

Owner-UI form operations only; never reachable through /app-tools/* or chat. Every committed change bumps
`version` and appends one audit event in the same transaction; stale expected_version => AiclError conflict
(current_version) with no effect; archived => invalid_state; unchanged value at the current version =>
changed=False with no bump and no event.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from sqlite3 import Connection
from typing import Callable, Literal, Protocol

from aicl.clock import Clock, SystemClock
from aicl.control.audit import AuditEvent, SqliteAuditLog
from aicl.control.auth import AuthContext
from aicl.control.budget import SqliteBudgetPort
from aicl.control.errors import AiclError
from aicl.control.instances import (
    CATALOG_CAPABILITIES, AgentInstance, LifecycleAction, Limits, SqliteInstanceRepository, next_lifecycle,
)
from aicl.control.price_table import effective_version
from aicl.creation.models import MutationResult
from aicl.creation.service import (
    DEFAULT_HOLD_STALE_SECONDS, NOT_IMPLEMENTED, read_instance_snapshot_conn, validation_failed,
)
from aicl.db import Database, from_iso, to_iso
from aicl.network.policy import MAX_OWNER_DOMAINS, normalize_owner_domain

GateControlResult = Literal["permits", "still_denied"]
LIMIT_FIELDS = ("inference_daily_micro_usd", "inference_monthly_micro_usd", "compute_daily_micro_usd",
                "compute_monthly_micro_usd")


def host_hash12(host: str) -> str:
    return hashlib.sha256(host.encode()).hexdigest()[:12]


def _budget_permits(conn: Connection, instance: AgentInstance, clock: Clock, hold_stale_seconds: int) -> bool:
    """All four windows must have available > 0, measured in the windows that were current when the gate was
    persisted (`gated_at`), so a window rollover alone never clears a gate (D11-8)."""
    try:
        now = clock.now()
        if effective_version(conn, now) is None:
            return False
        row = conn.execute("SELECT * FROM agent_instance WHERE id = ?", (instance.id,)).fetchone()
        at = from_iso(row["gated_at"]) if row["gated_at"] else now
        amounts = SqliteBudgetPort(Database.current(), clock, hold_stale_seconds)._amounts(conn, row, at)
        return all(w.available > 0 for windows in amounts.values() for w in windows.values())
    except Exception:  # unreadable state never permits
        return False


def _connection_permits(conn: Connection, instance: AgentInstance, capabilities: tuple[str, ...]) -> bool:
    if not capabilities:
        return False
    for capability in capabilities:
        row = conn.execute(
            "SELECT c.status FROM connection_attachment a JOIN connection c ON c.id = a.connection_id "
            "WHERE a.instance_id = ? AND a.capability = ? AND a.detached_at IS NULL",
            (instance.id, capability)).fetchone()
        if row is None or row["status"] != "active":
            return False
    return True


def evaluate_gate_control(conn: Connection, instance: AgentInstance, clock: Clock | None = None,
                          hold_stale_seconds: int = DEFAULT_HOLD_STALE_SECONDS) -> GateControlResult:
    """Re-evaluate the persisted `gated_reason` with its `gate_context` (no persisted gate => permits).

    budget_*: read_budget readable, a price version effective, all four windows available > 0;
    capability_disabled: every gate_context capability enabled; connection_*: every capability has an
    active attachment on an active connection; network_denied: network.fetch enabled and network_domains
    holds a host whose sha256 prefix equals gate_context.host_hash12. A window rollover never permits.
    """
    reason, context = instance.gated_reason, instance.gate_context
    if reason is None:
        return "permits"
    clock = clock or SystemClock()
    capabilities = context.capabilities if context else ()
    if reason in ("budget_exhausted", "budget_unavailable"):
        ok = _budget_permits(conn, instance, clock, hold_stale_seconds)
    elif reason == "capability_disabled":
        enabled = {r["capability"] for r in conn.execute(
            "SELECT capability FROM capability_grant WHERE instance_id = ? AND enabled = 1", (instance.id,))}
        ok = bool(capabilities) and all(c in enabled for c in capabilities)
    elif reason in ("connection_revoked", "connection_reauthorization_required"):
        ok = _connection_permits(conn, instance, capabilities)
    elif reason == "network_denied":
        fetch = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id = ? AND capability = "
                             "'network.fetch'", (instance.id,)).fetchone()
        wanted = context.host_hash12 if context else None
        ok = bool(fetch and fetch["enabled"] and wanted
                  and any(host_hash12(h) == wanted for h in instance.network_domains))
    else:
        ok = False
    return "permits" if ok else "still_denied"


class InstanceOperations(Protocol):
    def set_lifecycle(self, auth: AuthContext, instance_id: str, expected_version: int,
                      action: LifecycleAction) -> MutationResult: ...

    def set_capability(self, auth: AuthContext, instance_id: str, expected_version: int,
                       capability: str, enabled: bool) -> MutationResult: ...

    def set_limits(self, auth: AuthContext, instance_id: str, expected_version: int,
                   limits: Limits) -> MutationResult: ...

    def add_network_domain(self, auth: AuthContext, instance_id: str, expected_version: int,
                           host: str) -> MutationResult: ...

    def remove_network_domain(self, auth: AuthContext, instance_id: str, expected_version: int,
                              host: str) -> MutationResult: ...

    def resolve_gate(self, auth: AuthContext, instance_id: str, expected_version: int) -> MutationResult:
        """Clears the persisted gate only when evaluate_gate_control permits (instance.gate_resolved,
        committed); otherwise AiclError denied reason=gate_unresolved (audited, outcome denied)."""
        ...

    def attach_connection(self, auth: AuthContext, instance_id: str, expected_version: int,
                          capability: str, connection_id: str) -> MutationResult: ...

    def detach_connection(self, auth: AuthContext, instance_id: str, expected_version: int,
                          capability: str) -> MutationResult: ...


class UnimplementedInstanceOperations:
    """Contract stub kept for importers of the E11-2 design phase; the real class is SqliteInstanceOperations."""

    def _stub(self, *_args: object, **_kwargs: object) -> MutationResult:
        raise NotImplementedError(NOT_IMPLEMENTED)

    set_lifecycle = set_capability = set_limits = add_network_domain = remove_network_domain = _stub
    resolve_gate = attach_connection = detach_connection = _stub


class SqliteInstanceOperations:
    def __init__(self, db: Database, clock: Clock, hold_stale_seconds: int = DEFAULT_HOLD_STALE_SECONDS) -> None:
        self.db = db
        self.clock = clock
        self.hold_stale_seconds = hold_stale_seconds
        self.instances = SqliteInstanceRepository()
        self.audit = SqliteAuditLog(clock)

    # -- shared machinery ----------------------------------------------------------------------
    def _load(self, conn: Connection, auth: AuthContext, instance_id: str, expected_version: int) -> AgentInstance:
        from aicl.control.instances import _fetch
        instance = _fetch(conn, auth, instance_id)
        if instance.lifecycle == "archived":
            raise AiclError("invalid_state", "instance is archived", lifecycle="archived")
        if instance.version != expected_version:
            raise AiclError("conflict", "stale expected_version", current_version=instance.version)
        return instance

    def _event(self, conn: Connection, auth: AuthContext, instance_id: str, event_type: str, details: dict,
               outcome: str = "committed", reason: str | None = None, connection_id: str | None = None):
        return self.audit.append(conn, AuditEvent(event_type, "owner", outcome, auth.tenant_id, auth.owner_id,
                                                  instance_id, connection_id, reason, details))

    def _bump(self, conn: Connection, auth: AuthContext, instance_id: str, **columns: object) -> None:
        updates = {
            'lifecycle': 'UPDATE agent_instance SET lifecycle = ? WHERE id = ? AND tenant_id = ?',
            'network_domains': 'UPDATE agent_instance SET network_domains = ? WHERE id = ? AND tenant_id = ?',
            'inference_daily_micro_usd': 'UPDATE agent_instance SET inference_daily_micro_usd = ? WHERE id = ? AND tenant_id = ?',
            'inference_monthly_micro_usd': 'UPDATE agent_instance SET inference_monthly_micro_usd = ? WHERE id = ? AND tenant_id = ?',
            'compute_daily_micro_usd': 'UPDATE agent_instance SET compute_daily_micro_usd = ? WHERE id = ? AND tenant_id = ?',
            'compute_monthly_micro_usd': 'UPDATE agent_instance SET compute_monthly_micro_usd = ? WHERE id = ? AND tenant_id = ?',
        }
        if not columns.keys() <= updates.keys():
            raise ValueError("unsupported instance update column")
        for column, value in columns.items():
            conn.execute(updates[column], (value, instance_id, auth.tenant_id))
        conn.execute("UPDATE agent_instance SET version = version + 1, updated_at = ? "
                     "WHERE id = ? AND tenant_id = ?",
                     (to_iso(self.clock.now()), instance_id, auth.tenant_id))

    def _reevaluate(self, conn: Connection, auth: AuthContext, instance_id: str) -> None:
        from aicl.control.instances import _fetch
        current = _fetch(conn, auth, instance_id)
        if current.gated_reason is not None and evaluate_gate_control(
                conn, current, self.clock, self.hold_stale_seconds) == "permits":
            self._clear_gate(conn, auth, instance_id)

    def _clear_gate(self, conn: Connection, auth: AuthContext, instance_id: str) -> None:
        self.instances.clear_gated(conn, auth, instance_id)
        conn.execute("UPDATE agent_instance SET gated_at = NULL WHERE id = ?", (instance_id,))

    def _result(self, conn: Connection, auth: AuthContext, instance_id: str, changed: bool,
                event_seq: int | None) -> MutationResult:
        return MutationResult(read_instance_snapshot_conn(conn, auth, instance_id, clock=self.clock,
                                                          hold_stale_seconds=self.hold_stale_seconds),
                              changed, event_seq)

    def mutate(self, auth: AuthContext, instance_id: str, expected_version: int,
               apply: Callable[[Connection, AgentInstance], tuple[bool, int | None]],
               reevaluate: bool = True) -> MutationResult:
        """One transaction: load/check, `apply(conn, instance)` returns (changed, audit seq), then re-evaluate."""
        with self.db.transaction() as conn:
            instance = self._load(conn, auth, instance_id, expected_version)
            changed, seq = apply(conn, instance)
            if changed and reevaluate:
                self._reevaluate(conn, auth, instance_id)
            return self._result(conn, auth, instance_id, changed, seq)

    # -- operations ----------------------------------------------------------------------------
    def set_lifecycle(self, auth, instance_id, expected_version, action):
        def apply(conn, instance):
            target = next_lifecycle(instance.lifecycle, action)
            self._bump(conn, auth, instance_id, lifecycle=target)
            event = self._event(conn, auth, instance_id, "instance.lifecycle_changed",
                                {"from": instance.lifecycle, "to": target, "action": action})
            return True, event.seq
        return self.mutate(auth, instance_id, expected_version, apply, reevaluate=False)

    def set_capability(self, auth, instance_id, expected_version, capability, enabled):
        def apply(conn, instance):
            if capability not in CATALOG_CAPABILITIES:
                raise validation_failed(("capability", "unknown_capability"))
            row = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id = ? AND capability = ?",
                               (instance_id, capability)).fetchone()
            if row is not None and bool(row["enabled"]) == bool(enabled):
                return False, None
            conn.execute("INSERT INTO capability_grant (instance_id, capability, enabled) VALUES (?,?,?) "
                         "ON CONFLICT (instance_id, capability) DO UPDATE SET enabled = excluded.enabled",
                         (instance_id, capability, int(bool(enabled))))
            self._bump(conn, auth, instance_id)
            event = self._event(conn, auth, instance_id, "instance.capability_changed",
                                {"capability": capability, "enabled": bool(enabled)})
            return True, event.seq
        return self.mutate(auth, instance_id, expected_version, apply)

    def set_limits(self, auth, instance_id, expected_version, limits):
        def apply(conn, instance):
            from aicl.control.instances import MAX_LIMIT_MICRO_USD
            values = {f: getattr(limits, f) for f in LIMIT_FIELDS}
            bad = [f for f, v in values.items()
                   if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > MAX_LIMIT_MICRO_USD]
            if bad:
                raise validation_failed(*((f, "out_of_range") for f in bad))
            changed = [f for f in LIMIT_FIELDS if getattr(instance.limits, f) != values[f]]
            if not changed:
                return False, None
            self._bump(conn, auth, instance_id, **values)
            event = self._event(conn, auth, instance_id, "instance.limits_changed", {"count": len(changed)})
            return True, event.seq
        return self.mutate(auth, instance_id, expected_version, apply)

    def add_network_domain(self, auth, instance_id, expected_version, host):
        def apply(conn, instance):
            normalized = normalize_owner_domain(host)
            if normalized in instance.network_domains:
                return False, None
            if len(instance.network_domains) >= MAX_OWNER_DOMAINS:
                raise validation_failed(("host", "too_many_domains"))
            domains = [*instance.network_domains, normalized]
            self._bump(conn, auth, instance_id, network_domains=json.dumps(domains))
            event = self._event(conn, auth, instance_id, "instance.domain_added", {"host": normalized})
            return True, event.seq
        return self.mutate(auth, instance_id, expected_version, apply)

    def remove_network_domain(self, auth, instance_id, expected_version, host):
        def apply(conn, instance):
            target = host.strip().lower()
            if target not in instance.network_domains:
                return False, None
            domains = [d for d in instance.network_domains if d != target]
            self._bump(conn, auth, instance_id, network_domains=json.dumps(domains))
            event = self._event(conn, auth, instance_id, "instance.domain_removed", {"host": target})
            return True, event.seq
        return self.mutate(auth, instance_id, expected_version, apply)

    def resolve_gate(self, auth, instance_id, expected_version):
        with self.db.transaction() as conn:
            instance = self._load(conn, auth, instance_id, expected_version)
            if instance.gated_reason is None:
                return self._result(conn, auth, instance_id, False, None)
            if evaluate_gate_control(conn, instance, self.clock, self.hold_stale_seconds) == "permits":
                self._clear_gate(conn, auth, instance_id)
                self._bump(conn, auth, instance_id)
                event = self._event(conn, auth, instance_id, "instance.gate_resolved", {})
                return self._result(conn, auth, instance_id, True, event.seq)
            self._event(conn, auth, instance_id, "instance.gate_resolved", {}, outcome="denied",
                        reason="gate_unresolved")
            error = AiclError("denied", "the control still denies work", reason="gate_unresolved")
            error.commit_on_error = True  # type: ignore[attr-defined]  # keep the denial audit record
            raise error

    def attach_connection(self, auth, instance_id, expected_version, capability, connection_id):
        def apply(conn, instance):
            from aicl.connections.models import CAPABILITY_SCOPES
            from aicl.connections.service import fetch_connection
            connection = fetch_connection(conn, auth, connection_id)
            spec = CAPABILITY_SCOPES.get(capability)
            if spec is None or spec[0] != connection.provider:
                raise validation_failed(("capability", "provider_mismatch"))
            if connection.status != "active":
                raise validation_failed(("connection_id", "connection_not_active"))
            if spec[1] not in connection.granted_scopes:
                raise validation_failed(("capability", "scope_missing"))
            current = conn.execute(
                "SELECT id, connection_id FROM connection_attachment WHERE instance_id = ? AND capability = ? "
                "AND detached_at IS NULL", (instance_id, capability)).fetchone()
            if current is not None and current["connection_id"] == connection_id:
                return False, None
            now = to_iso(self.clock.now())
            if current is not None:
                conn.execute("UPDATE connection_attachment SET detached_at = ? WHERE id = ?", (now, current["id"]))
            conn.execute(
                "INSERT INTO connection_attachment (id, instance_id, capability, connection_id, owner_id, "
                "tenant_id, created_at) VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), instance_id, capability, connection_id, auth.owner_id, auth.tenant_id, now))
            self._bump(conn, auth, instance_id)
            event = self._event(conn, auth, instance_id, "connection.attached",
                                {"capability": capability, "connection_id": connection_id,
                                 "provider": connection.provider}, connection_id=connection_id)
            return True, event.seq
        return self.mutate(auth, instance_id, expected_version, apply)

    def detach_connection(self, auth, instance_id, expected_version, capability):
        def apply(conn, instance):
            current = conn.execute(
                "SELECT id, connection_id FROM connection_attachment WHERE instance_id = ? AND capability = ? "
                "AND detached_at IS NULL", (instance_id, capability)).fetchone()
            if current is None:
                return False, None
            conn.execute("UPDATE connection_attachment SET detached_at = ? WHERE id = ?",
                         (to_iso(self.clock.now()), current["id"]))
            self._bump(conn, auth, instance_id)
            event = self._event(conn, auth, instance_id, "connection.detached",
                                {"capability": capability, "connection_id": current["connection_id"]},
                                connection_id=current["connection_id"])
            return True, event.seq
        return self.mutate(auth, instance_id, expected_version, apply, reevaluate=False)

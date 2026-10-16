"""AuditEvent and append-only AuditLog (technical.md "AuditEvent", owner E11-1)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from sqlite3 import Connection
from typing import Literal, Protocol

from aicl.clock import Clock, SystemClock
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.db import Database, from_iso, to_iso

ActorKind = Literal["owner", "chat", "system", "gate"]
Outcome = Literal["committed", "denied"]

EVENT_TYPES: frozenset[str] = frozenset({
    "instance.created", "instance.lifecycle_changed", "instance.capability_changed",
    "instance.limits_changed", "instance.domain_added", "instance.domain_removed",
    "instance.gated", "instance.gate_resolved", "connection.created", "connection.attached",
    "connection.detached", "connection.revoked", "connection.provider_revoke_succeeded",
    "connection.provider_revoke_failed", "confirmation.requested", "confirmation.created",
    "confirmation.used", "work.denied", "work.dispatched", "budget.reserved", "budget.settled",
    "budget.unknown", "budget.reconciled", "budget.overrun", "budget.late_settlement",
    "auth.signed_in", "auth.signed_out", "auth.link_rate_limited", "auth.link_rejected",
    "access.denied",
})
# Only these `details` keys survive the writer; any other key is dropped.
DETAILS_ALLOW_LIST: frozenset[str] = frozenset({
    "from", "to", "action", "capability", "enabled", "version", "limit_field", "old_micro_usd",
    "new_micro_usd", "host", "provider", "connection_id", "hold_id", "micro_usd",
    "price_table_version", "denial_reason", "confirmation_id", "payload_digest_prefix",
    "template_id", "surface", "target_kind", "count", "reason_code", "token_hash_prefix",
    "email_hash_prefix",
})
# Only pre-authentication system events may carry a null tenant/owner.
NULL_IDENTITY_EVENT_TYPES: frozenset[str] = frozenset({"auth.link_rate_limited", "auth.link_rejected"})
MAX_PAGE = 100


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    actor_kind: ActorKind
    outcome: Outcome
    tenant_id: str | None = None
    owner_id: str | None = None
    instance_id: str | None = None
    connection_id: str | None = None
    reason: str | None = None
    details: dict[str, object] = field(default_factory=dict)
    # Assigned by the log on append:
    seq: int | None = None
    id: str | None = None
    occurred_at: datetime | None = None


class AuditLog(Protocol):
    def append(self, conn: Connection, event: AuditEvent) -> AuditEvent:
        """Only writer; runs in the caller's transaction, redacting `details` to the allow-list."""
        ...

    def list_for_instance(self, auth: AuthContext, instance_id: str, after_seq: int | None = None,
                          limit: int = MAX_PAGE) -> list[AuditEvent]: ...

    def list_for_owner(self, auth: AuthContext, after_seq: int | None = None,
                       limit: int = MAX_PAGE) -> list[AuditEvent]: ...


def _to_event(row) -> AuditEvent:
    return AuditEvent(
        event_type=row["event_type"], actor_kind=row["actor_kind"], outcome=row["outcome"],
        tenant_id=row["tenant_id"], owner_id=row["owner_id"], instance_id=row["instance_id"],
        connection_id=row["connection_id"], reason=row["reason"], details=json.loads(row["details"]),
        seq=row["seq"], id=row["id"], occurred_at=from_iso(row["occurred_at"]))


class SqliteAuditLog:
    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or SystemClock()

    def append(self, conn, event):
        if event.event_type not in EVENT_TYPES:
            raise AiclError("validation_failed", "unknown audit event type")
        if (event.tenant_id is None or event.owner_id is None) and event.event_type not in NULL_IDENTITY_EVENT_TYPES:
            raise AiclError("validation_failed", "audit event requires tenant and owner")
        details = {k: v for k, v in event.details.items() if k in DETAILS_ALLOW_LIST}
        event_id, now = str(uuid.uuid4()), self.clock.now()
        cursor = conn.execute(
            "INSERT INTO audit_event (id, event_type, actor_kind, outcome, tenant_id, owner_id, instance_id, "
            "connection_id, reason, details, occurred_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, event.event_type, event.actor_kind, event.outcome, event.tenant_id, event.owner_id,
             event.instance_id, event.connection_id, event.reason, json.dumps(details, sort_keys=True), to_iso(now)))
        return replace(event, details=details, seq=cursor.lastrowid, id=event_id, occurred_at=from_iso(to_iso(now)))

    def _list(self, where: str, args: tuple, after_seq, limit) -> list[AuditEvent]:
        clause, params = where, list(args)
        if after_seq is not None:
            clause += " AND seq > ?"
            params.append(after_seq)
        params.append(max(1, min(int(limit), MAX_PAGE)))
        with Database.current().reader() as conn:
            rows = conn.execute(f"SELECT * FROM audit_event WHERE {clause} ORDER BY seq DESC LIMIT ?", params)
            return [_to_event(r) for r in rows]

    def list_for_instance(self, auth, instance_id, after_seq=None, limit=MAX_PAGE):
        return self._list("tenant_id = ? AND instance_id = ?", (auth.tenant_id, instance_id), after_seq, limit)

    def list_for_owner(self, auth, after_seq=None, limit=MAX_PAGE):
        return self._list("tenant_id = ? AND owner_id = ?", (auth.tenant_id, auth.owner_id), after_seq, limit)

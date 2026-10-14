"""AuditEvent and append-only AuditLog (technical.md "AuditEvent", owner E11-1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from sqlite3 import Connection
from typing import Literal, Protocol

from aicl.control.auth import AuthContext

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


class SqliteAuditLog:
    """Stub: raises NotImplementedError until implemented (E11-1)."""

    def append(self, conn, event):
        raise NotImplementedError("AuditLog.append is not implemented (E11-1)")

    def list_for_instance(self, auth, instance_id, after_seq=None, limit=MAX_PAGE):
        raise NotImplementedError("AuditLog.list_for_instance is not implemented (E11-1)")

    def list_for_owner(self, auth, after_seq=None, limit=MAX_PAGE):
        raise NotImplementedError("AuditLog.list_for_owner is not implemented (E11-1)")

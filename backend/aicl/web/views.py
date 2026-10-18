"""Read projections for the owner pages (aicl-experience/technical.md "Read projections and management pages",
owner E11-5).

Every read is filtered by `auth.tenant_id` (another tenant's instance, connection, usage or history is `not_found`
or absent, never shown). The views compose existing contracts and add nothing to them:

- `InstanceDetailView.snapshot` is the E11-2 `InstanceSnapshot` unchanged (id, name, instructions, lifecycle,
  status, gated reason, version, limits, capabilities, network domains, attachments);
- `budget` is the E11-1 `BudgetView` from `BudgetPort.read_budget`; amounts are micro-USD and rendered as USD with
  six decimals by `format_usd`;
- `audit` is `AuditLog.list_for_instance`, which already holds only allow-listed `details` keys;
- `usage_history` reuses the E11-1 `Usage` shape and `pending_actions` the E11-1 `PendingAction` shape (bounded
  allow-listed preview, never the payload body). No operation in the other contracts lists these rows, so the
  implementation reads them with tenant-filtered, read-only queries inside `ProjectionStore` (no change to
  `BudgetPort`, `ConfirmationStore` or any other contract);
- a connection summary never carries `secret_ref`, granted scopes or any credential field.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aicl.clock import Clock
from aicl.control.audit import AuditEvent
from aicl.control.auth import AuthContext
from aicl.control.audit import SqliteAuditLog
from aicl.control.budget import BudgetView, SqliteBudgetPort, Usage, _usage
from aicl.control.confirmation import PendingAction
from aicl.control.errors import AiclError
from aicl.control.instances import MAX_LIMIT_MICRO_USD, GatedReason, Lifecycle
from aicl.creation.models import ConnectionStatus, InstanceSnapshot, InstanceStatus
from aicl.creation.service import read_instance_snapshot_conn, validation_failed
from aicl.db import from_iso

USD_DECIMALS = 6  # `budget` and usage amounts render as USD with six decimals from micro-USD


@dataclass(frozen=True)
class InstanceSummary:
    """One workspace row: name, lifecycle, derived status and the gate reason, if any."""

    id: str
    name: str
    lifecycle: Lifecycle
    status: InstanceStatus
    gated_reason: GatedReason | None


@dataclass(frozen=True)
class WorkspaceView:
    instances: tuple[InstanceSummary, ...]


@dataclass(frozen=True)
class InstanceDetailView:
    snapshot: InstanceSnapshot
    budget: BudgetView
    usage_history: tuple[Usage, ...]
    audit: tuple[AuditEvent, ...]
    pending_actions: tuple[PendingAction, ...]


@dataclass(frozen=True)
class ConnectionSummary:
    """Owner-visible connection: no `secret_ref`, scopes or credential. `provider_revoke_status == "failed"` is the
    cue to tell the owner to remove access in the provider's own account settings."""

    id: str
    provider: str
    display_name: str
    status: ConnectionStatus
    provider_revoke_status: str
    created_at: datetime
    revoked_at: datetime | None
    version: int


@dataclass(frozen=True)
class AttachmentRow:
    """An active (not detached) attachment of a connection to one capability of one of the owner's instances."""

    connection_id: str
    instance_id: str
    instance_name: str
    capability: str


@dataclass(frozen=True)
class ConnectionsView:
    connections: tuple[ConnectionSummary, ...]
    attachments: tuple[AttachmentRow, ...]


_USD = re.compile(r"^(\d+)(?:\.(\d{1,6}))?$")


def format_usd(micro_usd: int) -> str:
    """Render micro-USD as USD with exactly six decimals (for example 1_500_000 -> "1.500000")."""
    sign = "-" if micro_usd < 0 else ""
    whole, frac = divmod(abs(int(micro_usd)), 1_000_000)
    return f"{sign}{whole}.{frac:0{USD_DECIMALS}d}"


def parse_usd(text: str) -> int:
    """Parse an owner-typed USD amount (non-negative decimal, at most six decimals) into integer micro-USD.
    Raises `AiclError("validation_failed", ...)` with a field error for malformed, negative or oversized
    (above `MAX_LIMIT_MICRO_USD`) input; the limits form posts the result to `InstanceOperations.set_limits`."""
    raw = str(text).strip()
    match = _USD.match(raw)
    if match is None:
        negative = re.fullmatch(r"-\d+(?:\.\d+)?", raw) is not None
        raise validation_failed(("amount", "out_of_range" if negative else "invalid"))
    micro = int(match.group(1)) * 1_000_000 + int((match.group(2) or "").ljust(USD_DECIMALS, "0") or 0)
    if micro > MAX_LIMIT_MICRO_USD:
        raise validation_failed(("amount", "out_of_range"))
    return micro


class ProjectionStore(Protocol):
    """Tenant-filtered read-only queries that no other contract exposes. Never commits or writes."""

    def list_instance_summaries(self, auth: AuthContext) -> tuple[InstanceSummary, ...]:
        """Oldest first, derived `status` exactly as `read_instance_snapshot` derives it."""
        ...

    def list_usage(self, auth: AuthContext, instance_id: str) -> tuple[Usage, ...]:
        """`budget_usage` rows of this instance, newest first; `not_found` for another tenant's instance."""
        ...

    def list_pending_actions(self, auth: AuthContext, instance_id: str) -> tuple[PendingAction, ...]:
        """Pending actions without a confirmation yet (the ones the confirmation prompt offers)."""
        ...

    def list_connections(self, auth: AuthContext) -> tuple[ConnectionSummary, ...]: ...

    def list_attachments(self, auth: AuthContext) -> tuple[AttachmentRow, ...]: ...


class SqliteProjectionStore:
    """Read-only SQL over the E11-1/E11-2 tables, every query filtered by `auth.tenant_id`."""

    def __init__(self, db: object, clock: Clock, hold_stale_seconds: int) -> None:
        self.db, self.clock, self.hold_stale_seconds = db, clock, hold_stale_seconds

    def _owned(self, conn, auth: AuthContext, instance_id: str) -> None:
        if conn.execute("SELECT 1 FROM agent_instance WHERE id = ? AND tenant_id = ?",
                        (instance_id, auth.tenant_id)).fetchone() is None:
            raise AiclError("not_found", "instance not found")

    def list_instance_summaries(self, auth):
        with self.db.reader() as conn:
            ids = [r["id"] for r in conn.execute(
                "SELECT id FROM agent_instance WHERE tenant_id = ? ORDER BY created_at, rowid", (auth.tenant_id,))]
            snapshots = [read_instance_snapshot_conn(conn, auth, i, clock=self.clock,
                                                     hold_stale_seconds=self.hold_stale_seconds) for i in ids]
        return tuple(InstanceSummary(s.id, s.name, s.lifecycle, s.status, s.gated_reason) for s in snapshots)

    def list_usage(self, auth, instance_id):
        with self.db.reader() as conn:
            self._owned(conn, auth, instance_id)
            rows = conn.execute("SELECT * FROM budget_usage WHERE instance_id = ? ORDER BY recorded_at DESC, rowid DESC",
                                (instance_id,)).fetchall()
        return tuple(_usage(r) for r in rows)

    def list_pending_actions(self, auth, instance_id):
        with self.db.reader() as conn:
            self._owned(conn, auth, instance_id)
            rows = conn.execute(
                "SELECT p.* FROM pending_action p LEFT JOIN action_confirmation c ON c.pending_action_id = p.id "
                "WHERE p.instance_id = ? AND p.tenant_id = ? AND c.id IS NULL ORDER BY p.created_at, p.rowid",
                (instance_id, auth.tenant_id)).fetchall()
        return tuple(PendingAction(r["id"], r["instance_id"], r["tenant_id"], r["capability"], r["payload_digest"],
                                   json.loads(r["preview"]), from_iso(r["created_at"])) for r in rows)

    def list_connections(self, auth):
        with self.db.reader() as conn:
            rows = conn.execute(
                "SELECT id, provider, display_name, status, provider_revoke_status, created_at, revoked_at, version "
                "FROM connection WHERE tenant_id = ? AND owner_id = ? ORDER BY created_at, rowid",
                (auth.tenant_id, auth.owner_id)).fetchall()
        return tuple(ConnectionSummary(r["id"], r["provider"], r["display_name"], r["status"],
                                       r["provider_revoke_status"], from_iso(r["created_at"]),
                                       None if r["revoked_at"] is None else from_iso(r["revoked_at"]), r["version"])
                     for r in rows)

    def list_attachments(self, auth):
        with self.db.reader() as conn:
            rows = conn.execute(
                "SELECT a.connection_id, a.instance_id, i.name, a.capability FROM connection_attachment a "
                "JOIN agent_instance i ON i.id = a.instance_id WHERE a.tenant_id = ? AND i.tenant_id = ? "
                "AND a.detached_at IS NULL ORDER BY a.created_at, a.rowid", (auth.tenant_id, auth.tenant_id)).fetchall()
        return tuple(AttachmentRow(r["connection_id"], r["instance_id"], r["name"], r["capability"]) for r in rows)


class ProjectionService(Protocol):
    def workspace(self, auth: AuthContext) -> WorkspaceView: ...

    def instance_detail(self, auth: AuthContext, instance_id: str) -> InstanceDetailView:
        """`not_found` for an unknown or another tenant's instance."""
        ...

    def connections(self, auth: AuthContext) -> ConnectionsView: ...


class SqliteProjectionService:
    """Composes `read_instance_snapshot_conn`, `SqliteBudgetPort.read_budget`, `SqliteAuditLog.list_for_instance`
    and a `ProjectionStore` over the E11-1 Database. The constructor signature is the contract."""

    def __init__(self, db: object, clock: Clock, hold_stale_seconds: int) -> None:
        self.db = db
        self.clock = clock
        self.hold_stale_seconds = hold_stale_seconds
        self.store = SqliteProjectionStore(db, clock, hold_stale_seconds)

    def workspace(self, auth: AuthContext) -> WorkspaceView:
        return WorkspaceView(self.store.list_instance_summaries(auth))

    def instance_detail(self, auth: AuthContext, instance_id: str) -> InstanceDetailView:
        with self.db.reader() as conn:  # not_found for an unknown or another tenant's instance
            snapshot = read_instance_snapshot_conn(conn, auth, instance_id, clock=self.clock,
                                                   hold_stale_seconds=self.hold_stale_seconds)
        budget = SqliteBudgetPort(self.db, self.clock, self.hold_stale_seconds).read_budget(instance_id)
        audit = tuple(SqliteAuditLog(self.clock).list_for_instance(auth, instance_id))
        return InstanceDetailView(snapshot, budget, self.store.list_usage(auth, instance_id), audit,
                                  self.store.list_pending_actions(auth, instance_id))

    def connections(self, auth: AuthContext) -> ConnectionsView:
        return ConnectionsView(self.store.list_connections(auth), self.store.list_attachments(auth))

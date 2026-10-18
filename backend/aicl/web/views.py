"""Read projections for the owner pages (aicl-experience/technical.md "Read projections and management pages",
owner E11-5). Contract stubs: shapes and signatures only, no behavior.

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

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aicl.clock import Clock
from aicl.control.audit import AuditEvent
from aicl.control.auth import AuthContext
from aicl.control.budget import BudgetView, Usage
from aicl.control.confirmation import PendingAction
from aicl.control.instances import GatedReason, Lifecycle
from aicl.creation.models import ConnectionStatus, InstanceSnapshot, InstanceStatus

NOT_IMPLEMENTED = "E11-5 behavior is not implemented (contract stub)"
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


def format_usd(micro_usd: int) -> str:
    """Render micro-USD as USD with exactly six decimals (for example 1_500_000 -> "1.500000")."""
    raise NotImplementedError(NOT_IMPLEMENTED)


def parse_usd(text: str) -> int:
    """Parse an owner-typed USD amount (non-negative decimal, at most six decimals) into integer micro-USD.
    Raises `AiclError("validation_failed", ...)` with a field error for malformed, negative or oversized
    (above `MAX_LIMIT_MICRO_USD`) input; the limits form posts the result to `InstanceOperations.set_limits`."""
    raise NotImplementedError(NOT_IMPLEMENTED)


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


class ProjectionService(Protocol):
    def workspace(self, auth: AuthContext) -> WorkspaceView: ...

    def instance_detail(self, auth: AuthContext, instance_id: str) -> InstanceDetailView:
        """`not_found` for an unknown or another tenant's instance."""
        ...

    def connections(self, auth: AuthContext) -> ConnectionsView: ...


class SqliteProjectionService:
    """Stub implementation over the E11-1 Database, composing `read_instance_snapshot`, `SqliteBudgetPort.read_budget`,
    `SqliteAuditLog.list_for_instance` and a `ProjectionStore`. The constructor signature is the contract."""

    def __init__(self, db: object, clock: Clock, hold_stale_seconds: int) -> None:
        self.db = db
        self.clock = clock
        self.hold_stale_seconds = hold_stale_seconds

    def workspace(self, auth: AuthContext) -> WorkspaceView:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def instance_detail(self, auth: AuthContext, instance_id: str) -> InstanceDetailView:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def connections(self, auth: AuthContext) -> ConnectionsView:
        raise NotImplementedError(NOT_IMPLEMENTED)

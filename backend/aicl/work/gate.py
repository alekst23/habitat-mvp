"""WorkAuthorization (the single dispatch gate), budget audit recorder and HoldReconciler contracts.

connection-network-policy/technical.md, owner E11-2. Stubs only.

Fixed fail-closed order (first failure denies; any exception or unavailable dependency => `check_unavailable`):
 1 identity, 2 instance in tenant (not_found), 3 lifecycle active (instance_not_active), 4 capability enabled
 (capability_disabled; set_gated), 5 estimate present and bounded (estimate_missing), 6 confirmation for
 gmail.send/reddit.post (confirmation_required/expired/used/mismatch; PendingAction), 7 attachment on an active
 connection (connection_unavailable; set_gated), 8 network via authorize_destination (network_denied;
 set_gated only for host_not_allowed), 9 ONE db.transaction() with one `conn`: BudgetPort.reserve(conn, ...),
 consume_confirmation(conn, ...) and the WorkRequestRecord insert, 10 WorkExecutorPort.execute.
After a denial's rollback, `gated_reason`/`gate_context` and the `work.denied` event are written each in their own
transaction.
"""

from __future__ import annotations

from sqlite3 import Connection
from typing import Protocol

from aicl.control.auth import AuthContext
from aicl.control.budget import Hold, Usage
from aicl.creation.service import NOT_IMPLEMENTED
from aicl.work.models import WorkRequest, WorkResult

# Fixed order, as data, so tests can assert the documented sequence.
GATE_CHECK_ORDER: tuple[str, ...] = (
    "identity", "instance", "lifecycle", "capability", "estimate", "confirmation", "connection", "network",
    "reserve_and_consume", "dispatch",
)


class WorkAuthorization(Protocol):
    def authorize_and_dispatch(self, auth: AuthContext, request: WorkRequest) -> WorkResult: ...


class BudgetAuditRecorder(Protocol):
    """O-1 (carried from the E11-1 review): E11-1's `SqliteBudgetPort` appends ONLY `budget.late_settlement`
    itself; it does not append the reserve, settle, unknown, reconcile or overrun events. E11-2 must append them
    through the existing `AuditLog.append(conn, ...)` INSIDE THE SAME UNIT OF WORK as the corresponding
    BudgetPort call (same `conn`), so a rolled-back reservation or settlement leaves no audit row:

      budget.reserved   with the step-9 reserve (details: hold_id, micro_usd, price_table_version)
      budget.settled    with settle (usage)
      budget.overrun    when measured cost exceeds the hold (the full measured cost is recorded, never truncated)
      budget.unknown    with mark_unknown (unknown outcome, executor exception or timeout)
      budget.reconciled with reconcile by the HoldReconciler

    Plus `work.dispatched` and `work.denied` (denial_reason). Details keys stay within the E11-1 allow-list.
    """

    def reserved(self, conn: Connection, auth: AuthContext, hold: Hold) -> None: ...

    def settled(self, conn: Connection, auth: AuthContext, hold: Hold, usage: Usage) -> None: ...

    def overrun(self, conn: Connection, auth: AuthContext, hold: Hold, usage: Usage) -> None: ...

    def unknown(self, conn: Connection, auth: AuthContext, hold: Hold) -> None: ...

    def reconciled(self, conn: Connection, auth: AuthContext, hold: Hold, usage: Usage | None) -> None: ...


class UnimplementedBudgetAuditRecorder:
    """Contract stub: the tests phase asserts these rows exist and roll back with the unit of work."""

    def _stub(self, *_args: object, **_kwargs: object) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    reserved = settled = overrun = unknown = reconciled = _stub


class UnimplementedWorkAuthorization:
    def authorize_and_dispatch(self, auth: AuthContext, request: WorkRequest) -> WorkResult:
        raise NotImplementedError(NOT_IMPLEMENTED)


class HoldReconciler(Protocol):
    """STARTUP_HOOKS entry, registered after the RevocationSweeper. `run_once()` for tests with FakeClock; calls
    only BudgetPort and WorkExecutorPort.lookup. unknown or stale-held hold: lookup; measured => reconcile
    {measured_usage}; not_started => release (reconcile {no_usage} for unknown); still_unknown => stays unknown.
    A stale held hold is first mark_unknown'd. An exception is audited and the holds keep blocking."""

    def run_once(self) -> None: ...


class UnimplementedHoldReconciler:
    def run_once(self) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

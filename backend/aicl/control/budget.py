"""BudgetPort, Hold, Usage, BudgetView (technical.md "BudgetPort", owner E11-1). Micro-USD integers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection
from typing import Literal, Protocol

from aicl.control.auth import AuthContext  # noqa: F401  (documented caller identity; see technical.md)

HoldState = Literal["held", "settled", "released", "unknown"]
# from -> allowed targets; settled and released are terminal.
HOLD_TRANSITIONS: dict[str, frozenset[str]] = {
    "held": frozenset({"settled", "released", "unknown"}),
    "unknown": frozenset({"settled", "released"}),
    "settled": frozenset(),
    "released": frozenset(),
}


@dataclass(frozen=True)
class Estimate:
    """Bounded maximum the work may use; nonnegative integers."""

    inference_input_tokens: int
    inference_output_tokens: int
    compute_minutes: int


@dataclass(frozen=True)
class MeasuredUsage:
    inference_input_tokens: int
    inference_output_tokens: int
    compute_minutes: int


@dataclass(frozen=True)
class Hold:
    id: str
    instance_id: str
    work_id: str
    price_table_version: str
    inference_micro_usd: int
    compute_micro_usd: int
    window_day: str  # UTC date of created_at
    window_month: str  # UTC YYYY-MM of created_at
    state: HoldState
    created_at: datetime
    state_changed_at: datetime


@dataclass(frozen=True)
class Usage:
    hold_id: str
    instance_id: str
    inference_input_tokens: int
    inference_output_tokens: int
    compute_minutes: int
    inference_micro_usd: int
    compute_micro_usd: int
    price_table_version: str
    window_day: str
    window_month: str
    recorded_at: datetime


@dataclass(frozen=True)
class WindowAmounts:
    limit: int
    settled: int
    held: int
    available: int  # max(0, limit - settled - held)


@dataclass(frozen=True)
class BudgetView:
    instance_id: str
    # keys "inference"/"compute" -> {"day"|"month": WindowAmounts}
    windows: dict[str, dict[str, WindowAmounts]]
    blocking_hold_count: int
    price_table_version: str | None


@dataclass(frozen=True)
class NoUsage:
    """reconcile outcome `{no_usage: true}`: release the hold with zero usage."""


class BudgetPort(Protocol):
    """Construct with the DB handle, a Clock and AICL_HOLD_STALE_SECONDS.

    Every mutation has `op(conn, ...)` running in the caller's open transaction (never commits) and a
    convenience form that opens its own BEGIN IMMEDIATE. Denials raise AiclError('denied', reason=...)
    with reason in budget_exhausted | budget_unavailable | price_unavailable | reconciliation_pending;
    `conflict` and `unavailable` per technical.md.
    """

    def reserve(self, conn: Connection, instance_id: str, work_id: str, estimate: Estimate) -> Hold: ...

    def settle(self, conn: Connection, hold_id: str, measured: MeasuredUsage) -> Usage: ...

    def mark_unknown(self, conn: Connection, hold_id: str) -> Hold: ...

    def reconcile(self, conn: Connection, hold_id: str, outcome: MeasuredUsage | NoUsage) -> Usage | Hold: ...

    def release(self, conn: Connection, hold_id: str) -> Hold: ...

    def read_budget(self, instance_id: str) -> BudgetView: ...


class SqliteBudgetPort:
    """Stub: every operation raises NotImplementedError and never grants budget (fail closed)."""

    def __init__(self, db: object, clock: object, hold_stale_seconds: int) -> None:
        self.db = db
        self.clock = clock
        self.hold_stale_seconds = hold_stale_seconds

    def reserve(self, conn, instance_id, work_id, estimate):
        raise NotImplementedError("BudgetPort.reserve is not implemented (E11-1)")

    def settle(self, conn, hold_id, measured):
        raise NotImplementedError("BudgetPort.settle is not implemented (E11-1)")

    def mark_unknown(self, conn, hold_id):
        raise NotImplementedError("BudgetPort.mark_unknown is not implemented (E11-1)")

    def reconcile(self, conn, hold_id, outcome):
        raise NotImplementedError("BudgetPort.reconcile is not implemented (E11-1)")

    def release(self, conn, hold_id):
        raise NotImplementedError("BudgetPort.release is not implemented (E11-1)")

    def read_budget(self, instance_id):
        raise NotImplementedError("BudgetPort.read_budget is not implemented (E11-1)")

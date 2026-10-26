"""BudgetPort, Hold, Usage, BudgetView (technical.md "BudgetPort", owner E11-1). Micro-USD integers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import Literal, Protocol

from aicl.clock import Clock
from aicl.control.audit import AuditEvent, SqliteAuditLog
from aicl.control.auth import AuthContext  # noqa: F401  (documented caller identity; see technical.md)
from aicl.control.errors import AiclError
from aicl.control.price_table import cost_micro_usd, effective_version, load_version
from aicl.db import Database, from_iso, to_iso

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
    web_search_calls: int = 0


@dataclass(frozen=True)
class MeasuredUsage:
    inference_input_tokens: int
    inference_output_tokens: int
    compute_minutes: int
    web_search_calls: int = 0


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
    web_search_calls: int = 0


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

    def reserve(self, conn: Connection, instance_id: str, work_id: str, estimate: Estimate, *, price_table_version: str | None = None) -> Hold: ...

    def settle(self, conn: Connection, hold_id: str, measured: MeasuredUsage) -> Usage: ...

    def mark_unknown(self, conn: Connection, hold_id: str) -> Hold: ...

    def reconcile(self, conn: Connection, hold_id: str, outcome: MeasuredUsage | NoUsage) -> Usage | Hold: ...

    def release(self, conn: Connection, hold_id: str) -> Hold: ...

    def read_budget(self, instance_id: str) -> BudgetView: ...


def _denied(reason: str, message: str = "") -> AiclError:
    return AiclError("denied", message or reason, reason=reason)


def _hold(row) -> Hold:
    return Hold(id=row["id"], instance_id=row["instance_id"], work_id=row["work_id"],
                price_table_version=row["price_table_version"], inference_micro_usd=row["inference_micro_usd"],
                compute_micro_usd=row["compute_micro_usd"], window_day=row["window_day"],
                window_month=row["window_month"], state=row["state"], created_at=from_iso(row["created_at"]),
                state_changed_at=from_iso(row["state_changed_at"]))


def _usage(row) -> Usage:
    return Usage(hold_id=row["hold_id"], instance_id=row["instance_id"],
                 inference_input_tokens=row["inference_input_tokens"],
                 inference_output_tokens=row["inference_output_tokens"], compute_minutes=row["compute_minutes"],
                 inference_micro_usd=row["inference_micro_usd"], compute_micro_usd=row["compute_micro_usd"],
                 price_table_version=row["price_table_version"], window_day=row["window_day"],
                 window_month=row["window_month"], recorded_at=from_iso(row["recorded_at"]),
                 web_search_calls=row["web_search_calls"])


class SqliteBudgetPort:
    """SQLite budget controller. Zero or negative limit in any of the four windows denies
    `budget_exhausted` (default limits are 0); otherwise the estimate must fit every window."""

    def __init__(self, db: Database, clock: Clock, hold_stale_seconds: int) -> None:
        self.db = db
        self.clock = clock
        self.hold_stale_seconds = hold_stale_seconds

    # -- helpers -------------------------------------------------------------------------------
    def _instance(self, conn: Connection, instance_id: str):
        row = conn.execute("SELECT * FROM agent_instance WHERE id = ?", (instance_id,)).fetchone()
        if row is None:
            raise AiclError("not_found", "instance not found")
        return row

    def _get_hold(self, conn: Connection, hold_id: str):
        row = conn.execute("SELECT * FROM budget_hold WHERE id = ?", (hold_id,)).fetchone()
        if row is None:
            raise AiclError("not_found", "hold not found")
        return row

    def _stale_cutoff(self, now: datetime) -> str:
        return to_iso(now - timedelta(seconds=self.hold_stale_seconds))

    def _blocking(self, conn: Connection, instance_id: str, now: datetime) -> int:
        return conn.execute(
            "SELECT count(*) FROM budget_hold WHERE instance_id = ? AND (state = 'unknown' "
            "OR (state = 'held' AND created_at < ?))", (instance_id, self._stale_cutoff(now))).fetchone()[0]

    def _amounts(self, conn: Connection, instance, now: datetime):
        day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
        out: dict[str, dict[str, WindowAmounts]] = {}
        for window, key in (("day", day), ("month", month)):
            params = (instance["id"], window, key)
            settled = conn.execute(
                "SELECT COALESCE(SUM(inference_micro_usd),0), COALESCE(SUM(compute_micro_usd),0) "
                "FROM budget_usage WHERE instance_id = ? "
                "AND CASE ? WHEN 'day' THEN window_day ELSE window_month END = ?", params).fetchone()
            held = conn.execute(
                "SELECT COALESCE(SUM(inference_micro_usd),0), COALESCE(SUM(compute_micro_usd),0) "
                "FROM budget_hold WHERE instance_id = ? "
                "AND CASE ? WHEN 'day' THEN window_day ELSE window_month END = ? "
                "AND state IN ('held','unknown')", params).fetchone()
            for index, category in enumerate(("inference", "compute")):
                limit = instance[f"{category}_{'daily' if window == 'day' else 'monthly'}_micro_usd"]
                out.setdefault(category, {})[window] = WindowAmounts(
                    limit, settled[index], held[index], max(0, limit - settled[index] - held[index]))
        return out

    def _transition(self, conn: Connection, row, target: str, now: datetime) -> Hold:
        conn.execute("UPDATE budget_hold SET state = ?, state_changed_at = ? WHERE id = ?",
                     (target, to_iso(now), row["id"]))
        return _hold(self._get_hold(conn, row["id"]))

    def _audit(self, conn: Connection, hold, event_type: str, outcome: str, reason: str | None = None) -> None:
        inst = self._instance(conn, hold["instance_id"])
        SqliteAuditLog(self.clock).append(conn, AuditEvent(
            event_type, "gate", outcome, inst["tenant_id"], inst["owner_id"], hold["instance_id"], reason=reason,
            details={"hold_id": hold["id"], "micro_usd": hold["inference_micro_usd"] + hold["compute_micro_usd"]}))

    def _in_txn(self, op, *args):
        with self.db.transaction() as conn:
            return op(conn, *args)

    # -- operations ----------------------------------------------------------------------------
    def reserve(self, conn, instance_id, work_id, estimate, *, price_table_version=None):
        inst = self._instance(conn, instance_id)
        values = (estimate.inference_input_tokens, estimate.inference_output_tokens,
                  estimate.compute_minutes, estimate.web_search_calls)
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in values):
            raise AiclError("validation_failed", "estimate must be nonnegative integers")
        existing = conn.execute("SELECT * FROM budget_hold WHERE instance_id = ? AND work_id = ?",
                                (instance_id, work_id)).fetchone()
        if existing is not None:
            if price_table_version is not None and existing["price_table_version"] != price_table_version:
                raise AiclError("conflict", "work_id already reserved with a different price version")
            if (existing["est_input_tokens"], existing["est_output_tokens"], existing["est_compute_minutes"],
                    existing["est_web_search_calls"]) != values:
                raise AiclError("conflict", "work_id already reserved with a different estimate",
                                existing_result_id=existing["id"])
            return _hold(existing)
        now = self.clock.now()
        version = load_version(conn, price_table_version) if price_table_version else effective_version(conn, now)
        if version is None or version.effective_from > now:
            raise _denied("price_unavailable")
        if self._blocking(conn, instance_id, now) > 0:
            raise _denied("reconciliation_pending")
        try:
            cost = {
                "inference": cost_micro_usd(version, "inference.input_tokens", values[0])
                + cost_micro_usd(version, "inference.output_tokens", values[1])
                + cost_micro_usd(version, "inference.web_search_calls", values[3]),
                "compute": cost_micro_usd(version, "compute.minutes", values[2]),
            }
        except AiclError as error:
            if error.error == "unavailable":
                raise _denied("price_unavailable") from None
            raise
        for category, windows in self._amounts(conn, inst, now).items():
            for amounts in windows.values():
                if amounts.limit < 0:
                    raise _denied("budget_unavailable")
                if amounts.limit == 0 or cost[category] > amounts.available:
                    raise _denied("budget_exhausted")
        hold_id, stamp = str(uuid.uuid4()), to_iso(now)
        conn.execute(
            "INSERT INTO budget_hold (id, instance_id, work_id, price_table_version, est_input_tokens, "
            "est_output_tokens, est_compute_minutes, est_web_search_calls, inference_micro_usd, compute_micro_usd, window_day, "
            "window_month, state, created_at, state_changed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'held',?,?)",
            (hold_id, instance_id, work_id, version.version, *values, cost["inference"], cost["compute"],
             now.strftime("%Y-%m-%d"), now.strftime("%Y-%m"), stamp, stamp))
        return _hold(self._get_hold(conn, hold_id))

    def settle(self, conn, hold_id, measured):
        row = self._get_hold(conn, hold_id)
        values = (measured.inference_input_tokens, measured.inference_output_tokens,
                  measured.compute_minutes, measured.web_search_calls)
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in values):
            raise AiclError("validation_failed", "measured usage must be nonnegative integers")
        if row["state"] == "settled":
            usage = conn.execute("SELECT * FROM budget_usage WHERE hold_id = ?", (hold_id,)).fetchone()
            if (usage["inference_input_tokens"], usage["inference_output_tokens"], usage["compute_minutes"],
                    usage["web_search_calls"]) == values:
                return _usage(usage)
            raise AiclError("conflict", "hold already settled with different usage")
        if row["state"] == "released":
            self._audit(conn, row, "budget.late_settlement", "denied", "hold_released")
            error = AiclError("conflict", "hold was released; late settlement recorded")
            error.commit_on_error = True  # type: ignore[attr-defined]  # keep the audit record
            raise error
        version = load_version(conn, row["price_table_version"])
        inference = (cost_micro_usd(version, "inference.input_tokens", values[0])
                     + cost_micro_usd(version, "inference.output_tokens", values[1])
                     + cost_micro_usd(version, "inference.web_search_calls", values[3]))
        compute = cost_micro_usd(version, "compute.minutes", values[2])
        now = self.clock.now()
        conn.execute(
            "INSERT INTO budget_usage (hold_id, instance_id, inference_input_tokens, inference_output_tokens, "
            "compute_minutes, web_search_calls, inference_micro_usd, compute_micro_usd, price_table_version, window_day, "
            "window_month, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (hold_id, row["instance_id"], *values, inference, compute, version.version, row["window_day"],
             row["window_month"], to_iso(now)))
        self._transition(conn, row, "settled", now)
        return _usage(conn.execute("SELECT * FROM budget_usage WHERE hold_id = ?", (hold_id,)).fetchone())

    def mark_unknown(self, conn, hold_id):
        row = self._get_hold(conn, hold_id)
        if row["state"] == "unknown":
            return _hold(row)
        if row["state"] != "held":
            raise AiclError("conflict", f"hold is {row['state']}")
        return self._transition(conn, row, "unknown", self.clock.now())

    def release(self, conn, hold_id):
        row = self._get_hold(conn, hold_id)
        if row["state"] == "released":
            return _hold(row)
        if row["state"] == "settled":
            raise AiclError("conflict", "hold is settled")
        return self._transition(conn, row, "released", self.clock.now())

    def reconcile(self, conn, hold_id, outcome):
        if isinstance(outcome, NoUsage):
            return self.release(conn, hold_id)
        return self.settle(conn, hold_id, outcome)

    def read_budget(self, instance_id):
        now = self.clock.now()
        with self.db.reader() as conn:
            inst = self._instance(conn, instance_id)
            version = effective_version(conn, now)
            return BudgetView(instance_id, self._amounts(conn, inst, now), self._blocking(conn, instance_id, now),
                              None if version is None else version.version)

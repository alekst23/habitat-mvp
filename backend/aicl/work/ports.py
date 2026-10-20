"""Durable deterministic executor, keyed by globally unique budget hold identity.

A work_id is only unique within a tenant. The hold_id binds the executor journal
and reconciliation to one authorized operation. Started is committed before any
simulated provider effect; losing a process therefore never loses that evidence.
"""

from __future__ import annotations

from typing import Protocol

from aicl.control.budget import MeasuredUsage
from aicl.control.errors import AiclError
from aicl.db import Database
from aicl.work.models import AuthorizedWork, ExecutorOutcome, StillUnknown


class WorkExecutorPort(Protocol):
    def execute(self, work: AuthorizedWork) -> ExecutorOutcome: ...

    def lookup(self, hold_id: str) -> ExecutorOutcome | StillUnknown: ...


OPERATIONS = {"gmail.read": "gmail.messages.list", "gmail.send": "gmail.messages.send",
              "reddit.read": "reddit.listing.read", "reddit.post": "reddit.submit"}


def stored_outcome(row) -> ExecutorOutcome | StillUnknown:
    if row["status"] == "started":
        return StillUnknown()
    usage = None
    if row["input_tokens"] is not None:
        usage = MeasuredUsage(row["input_tokens"], row["output_tokens"], row["compute_minutes"])
    return ExecutorOutcome(row["status"], usage)


class FakeWorkExecutor:
    """No network/model calls. Simulation outcomes and start markers survive restart in SQLite.

    Production composition passes its database explicitly. The no-argument test seam
    binds the process-default database at first use, never switches databases afterward.
    """

    def __init__(self, broker: object | None = None, db: Database | None = None) -> None:
        self._db = db
        self.broker = broker

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = Database.current()
        return self._db

    @property
    def started(self) -> frozenset[str]:
        """Read-only diagnostic snapshot of started hold IDs; never process-local authority."""
        with self.db.reader() as conn:
            return frozenset(row[0] for row in conn.execute(
                "SELECT hold_id FROM executor_journal WHERE status != 'not_started'"))

    def execute(self, work: AuthorizedWork) -> ExecutorOutcome:
        with self.db.transaction() as conn:
            hold = conn.execute("SELECT instance_id, work_id, state FROM budget_hold WHERE id = ?",
                                (work.hold_id,)).fetchone()
            if hold is None or (hold["instance_id"], hold["work_id"]) != (work.instance_id, work.work_id):
                raise AiclError("denied", "executor requires the matching authorized hold")
            existing = conn.execute("SELECT * FROM executor_journal WHERE hold_id = ?", (work.hold_id,)).fetchone()
            if existing is not None:
                found = stored_outcome(existing)
                return ExecutorOutcome("unknown") if isinstance(found, StillUnknown) else found
            if hold["state"] not in ("held", "unknown"):
                return ExecutorOutcome("not_started")
            conn.execute("INSERT INTO executor_journal (hold_id, status) VALUES (?, 'started')", (work.hold_id,))
        # This commit precedes provider calls and result production. A crash here leaves StillUnknown.
        sim = work.payload.get("sim") if isinstance(work.payload, dict) else None
        sim = sim if isinstance(sim, dict) else {}
        outcome = str(sim.get("outcome", "succeeded"))

        def number(key: str) -> int:
            value = sim.get(key, 0)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

        if outcome in ("unknown", "not_started"):
            result = ExecutorOutcome(outcome)
        else:
            if self.broker is not None and work.capability in OPERATIONS:
                self.broker.call(work, OPERATIONS[work.capability])
            result = ExecutorOutcome("failed" if outcome == "failed" else "succeeded",
                                     MeasuredUsage(number("input_tokens"), number("output_tokens"),
                                                   number("compute_minutes")))
        usage = result.measured_usage
        with self.db.transaction() as conn:
            conn.execute("UPDATE executor_journal SET status = ?, input_tokens = ?, output_tokens = ?, "
                         "compute_minutes = ? WHERE hold_id = ? AND status = 'started'",
                         (result.status, usage.inference_input_tokens if usage else None,
                          usage.inference_output_tokens if usage else None, usage.compute_minutes if usage else None,
                          work.hold_id))
        return result

    def lookup(self, hold_id: str) -> ExecutorOutcome | StillUnknown:
        # An absent start record is definitive only if it also prevents a delayed execute.
        # BEGIN IMMEDIATE serializes this tombstone with the execute claim above.
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM executor_journal WHERE hold_id = ?", (hold_id,)).fetchone()
            if row is not None:
                return stored_outcome(row)
            if conn.execute("SELECT 1 FROM budget_hold WHERE id = ?", (hold_id,)).fetchone():
                conn.execute("INSERT INTO executor_journal (hold_id, status) VALUES (?, 'not_started')", (hold_id,))
            return ExecutorOutcome("not_started")

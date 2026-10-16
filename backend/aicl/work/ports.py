"""WorkExecutorPort and FakeWorkExecutor (connection-network-policy/technical.md, owner E11-2).

`execute` must durably record `started` for the work_id before any side effect (also in the fake), so a
`not_started` lookup is safe grounds to release a hold. `lookup` of a work_id with no started record returns
not_started; started with no stored outcome returns StillUnknown. Fake: deterministic from
`payload.sim = {input_tokens, output_tokens, compute_minutes, outcome}` (defaults 0, 0, 0, succeeded; usage above
the estimate allowed), no network or model call, can return `unknown`.
"""

from __future__ import annotations

from typing import Protocol

from aicl.control.budget import MeasuredUsage
from aicl.work.models import AuthorizedWork, ExecutorOutcome, StillUnknown


class WorkExecutorPort(Protocol):
    def execute(self, work: AuthorizedWork) -> ExecutorOutcome: ...

    def lookup(self, work_id: str) -> ExecutorOutcome | StillUnknown: ...


OPERATIONS = {"gmail.read": "gmail.messages.list", "gmail.send": "gmail.messages.send",
              "reddit.read": "reddit.listing.read", "reddit.post": "reddit.submit"}


class FakeWorkExecutor:
    """The only enabled executor (AICL_EXECUTOR_MODE=fake). No network or model call; deterministic from
    `payload.sim`. `execute` records `started` before producing any result. For provider capabilities it
    exercises the fake provider through the credential broker when one is attached (never a credential)."""

    def __init__(self, broker: object | None = None) -> None:
        self.started: set[str] = set()  # durable `started` record, written before any outcome
        self.outcomes: dict[str, ExecutorOutcome] = {}
        self.broker = broker

    def execute(self, work: AuthorizedWork) -> ExecutorOutcome:
        self.started.add(work.work_id)
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
        self.outcomes[work.work_id] = result
        return result

    def lookup(self, work_id: str) -> ExecutorOutcome | StillUnknown:
        if work_id in self.outcomes:
            return self.outcomes[work_id]
        if work_id in self.started:
            return StillUnknown()
        return ExecutorOutcome("not_started")

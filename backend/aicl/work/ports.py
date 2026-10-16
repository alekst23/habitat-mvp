"""WorkExecutorPort and FakeWorkExecutor (connection-network-policy/technical.md, owner E11-2).

`execute` must durably record `started` for the work_id before any side effect (also in the fake), so a
`not_started` lookup is safe grounds to release a hold. `lookup` of a work_id with no started record returns
not_started; started with no stored outcome returns StillUnknown. Fake: deterministic from
`payload.sim = {input_tokens, output_tokens, compute_minutes, outcome}` (defaults 0, 0, 0, succeeded; usage above
the estimate allowed), no network or model call, can return `unknown`.
"""

from __future__ import annotations

from typing import Protocol

from aicl.creation.service import NOT_IMPLEMENTED
from aicl.work.models import AuthorizedWork, ExecutorOutcome, StillUnknown


class WorkExecutorPort(Protocol):
    def execute(self, work: AuthorizedWork) -> ExecutorOutcome: ...

    def lookup(self, work_id: str) -> ExecutorOutcome | StillUnknown: ...


class FakeWorkExecutor:
    """The only enabled executor (AICL_EXECUTOR_MODE=fake)."""

    def __init__(self) -> None:
        self.started: set[str] = set()  # durable `started` record, written before any outcome
        self.outcomes: dict[str, ExecutorOutcome] = {}

    def execute(self, work: AuthorizedWork) -> ExecutorOutcome:
        raise NotImplementedError(NOT_IMPLEMENTED)

    def lookup(self, work_id: str) -> ExecutorOutcome | StillUnknown:
        raise NotImplementedError(NOT_IMPLEMENTED)

"""WorkRequest, WorkResult, WorkRequestRecord, AuthorizedWork, ExecutorOutcome (connection-network-policy/technical.md).

`work_id` follows the key pattern `^[A-Za-z0-9_-]{16,64}$` (simulated-work form: `work_<32 hex>`), unique per tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aicl.control.budget import Estimate, HoldState, MeasuredUsage, Usage
from aicl.creation.models import IDEMPOTENCY_KEY_PATTERN

WORK_PAYLOAD_MAX_BYTES = 16 * 1024
WorkOutcome = Literal["succeeded", "failed", "unknown", "denied"]
RecordOutcome = Literal["pending", "succeeded", "failed", "unknown", "released"]
ExecutorStatus = Literal["succeeded", "failed", "not_started", "unknown"]


class WorkRequest(BaseModel):
    """No tenant or owner field; `destination_url` is required only for `network.fetch`."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    instance_id: str
    work_id: str = Field(pattern=IDEMPOTENCY_KEY_PATTERN)
    capability: str
    payload: dict[str, object]
    estimate: Estimate | None  # None => denied estimate_missing
    destination_url: str | None = None


@dataclass(frozen=True)
class WorkResult:
    work_id: str
    outcome: WorkOutcome
    denial_reason: str | None  # a GATE_REASONS value when outcome == "denied"
    pending_action_id: str | None  # set with confirmation_required
    usage: Usage | None
    hold_state: HoldState | None


@dataclass(frozen=True)
class WorkRequestRecord:
    """Table owned by E11-2 (migration added with the implementation). Inserted in the step-9 transaction with
    the hold; updated in the same transaction as each settle, mark_unknown, release and reconcile.
    request_digest = sha256(canonical_json({instance_id, capability, payload, estimate, destination_url})).
    Replay of a stored work_id returns the stored WorkResult; a different digest is `conflict`."""

    tenant_id: str
    work_id: str
    request_digest: str
    outcome: RecordOutcome
    hold_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AuthorizedWork:
    """Executor input. `connection_handle` is the opaque attachment id only; never a credential."""

    work_id: str
    instance_id: str
    capability: str
    payload: dict[str, object]
    hold_id: str
    connection_handle: str | None
    destination: str | None


@dataclass(frozen=True)
class ExecutorOutcome:
    status: ExecutorStatus
    measured_usage: MeasuredUsage | None = None


class StillUnknown:
    """lookup result for work that is started with no recorded result."""

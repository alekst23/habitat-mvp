"""CreateInstanceRequest/Result, InstanceSnapshot, MutationResult (aicl-control-plane/technical.md, owner E11-2).

Shapes only. The snapshot is the lean tenant-filtered view: no tenant_id, owner_id, budget, usage, audit,
pending actions, secret_ref or credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aicl.control.instances import GatedReason, Lifecycle, Limits

# Conventions "Key pattern": every client idempotency key and work_id.
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9_-]{16,64}$"
TEMPLATE_ID_DEFAULT = "default"
InstanceStatus = Literal["draft", "active", "paused", "archived", "gated"]
ConnectionStatus = Literal["active", "reauthorization_required", "revoked"]
ActorKind = Literal["owner", "chat"]
Surface = Literal["wizard", "chat", "ui"]


class CreateInstanceRequest(BaseModel):
    """No tenant, owner, credential or confirmation field exists; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(pattern=IDEMPOTENCY_KEY_PATTERN)
    template_id: str
    name: str
    instructions: str
    enabled_capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AttachmentView:
    capability: str
    connection_id: str
    connection_display_name: str
    connection_status: ConnectionStatus


@dataclass(frozen=True)
class InstanceSnapshot:
    id: str
    template_id: str
    name: str
    instructions: str
    lifecycle: Lifecycle
    status: InstanceStatus  # derived: lifecycle unless active and (gated_reason set or blocking hold)
    gated_reason: GatedReason | None
    version: int
    limits: Limits
    capabilities: dict[str, bool]
    network_domains: tuple[str, ...]
    attachments: tuple[AttachmentView, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CreateInstanceResult:
    instance: InstanceSnapshot
    created: bool  # False on an idempotent replay
    audit_event_id: int  # AuditEvent.seq of the instance.created event


@dataclass(frozen=True)
class MutationResult:
    instance: InstanceSnapshot
    changed: bool  # False: no-op at the current version, no version bump, no audit event
    audit_event_id: int | None

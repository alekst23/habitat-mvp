"""AgentInstance, CapabilityGrant, gate-state primitives (technical.md "Instance model", owner E11-1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection
from typing import Literal, Protocol

from aicl.control.auth import AuthContext

Lifecycle = Literal["draft", "active", "paused", "archived"]
LifecycleAction = Literal["activate", "pause", "resume", "archive"]
GatedReason = Literal[
    "budget_exhausted", "budget_unavailable", "capability_disabled",
    "connection_revoked", "connection_reauthorization_required", "network_denied",
]
CATALOG_CAPABILITIES: tuple[str, ...] = (
    "inference", "gmail.read", "gmail.send", "reddit.read", "reddit.post", "network.fetch",
)
MAX_LIMIT_MICRO_USD = 1_000_000_000_000

# (from, action) -> to; every unlisted pair is invalid_transition and archived is terminal.
# Data only, from the technical.md table.
LIFECYCLE_TRANSITIONS: dict[tuple[str, str], str] = {
    ("draft", "activate"): "active", ("draft", "archive"): "archived",
    ("active", "pause"): "paused", ("active", "archive"): "archived",
    ("paused", "resume"): "active", ("paused", "archive"): "archived",
}


@dataclass(frozen=True)
class Limits:
    inference_daily_micro_usd: int = 0
    inference_monthly_micro_usd: int = 0
    compute_daily_micro_usd: int = 0
    compute_monthly_micro_usd: int = 0


@dataclass(frozen=True)
class GateContext:
    capabilities: tuple[str, ...] = ()
    host_hash12: str | None = None


@dataclass(frozen=True)
class CapabilityGrant:
    instance_id: str
    capability: str
    enabled: bool = False


@dataclass(frozen=True)
class AgentInstance:
    id: str
    tenant_id: str
    owner_id: str
    template_id: str
    name: str
    instructions: str
    lifecycle: Lifecycle
    gated_reason: GatedReason | None
    gate_context: GateContext | None
    version: int
    limits: Limits
    network_domains: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


def next_lifecycle(current: str, action: str) -> str:
    """Return the target state or raise AiclError('invalid_transition', from=..., action=...)."""
    raise NotImplementedError("next_lifecycle is not implemented (E11-1)")


class InstanceRepository(Protocol):
    """Every query is filtered by auth.tenant_id; another tenant's row is `not_found`.

    Connection-scoped forms take `conn` first (after auth) and never commit. E11-1 supplies the
    primitives; E11-2 composes creation and the owner mutations from them.
    """

    def insert_draft(self, conn: Connection, auth: AuthContext, instance: AgentInstance,
                     grants: tuple[CapabilityGrant, ...]) -> AgentInstance: ...

    def get(self, auth: AuthContext, instance_id: str) -> AgentInstance: ...

    def get_grants(self, auth: AuthContext, instance_id: str) -> tuple[CapabilityGrant, ...]: ...

    def set_gated(self, conn: Connection, auth: AuthContext, instance_id: str,
                  reason: GatedReason, context: GateContext) -> AgentInstance: ...

    def clear_gated(self, conn: Connection, auth: AuthContext, instance_id: str) -> AgentInstance: ...


class SqliteInstanceRepository:
    """Stub: every method raises NotImplementedError until implemented (E11-1)."""

    def insert_draft(self, conn, auth, instance, grants):
        raise NotImplementedError("InstanceRepository.insert_draft is not implemented (E11-1)")

    def get(self, auth, instance_id):
        raise NotImplementedError("InstanceRepository.get is not implemented (E11-1)")

    def get_grants(self, auth, instance_id):
        raise NotImplementedError("InstanceRepository.get_grants is not implemented (E11-1)")

    def set_gated(self, conn, auth, instance_id, reason, context):
        raise NotImplementedError("InstanceRepository.set_gated is not implemented (E11-1)")

    def clear_gated(self, conn, auth, instance_id):
        raise NotImplementedError("InstanceRepository.clear_gated is not implemented (E11-1)")

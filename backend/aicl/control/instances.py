"""AgentInstance, CapabilityGrant, gate-state primitives (technical.md "Instance model", owner E11-1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection
from typing import Literal, Protocol

from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.db import Database, from_iso, to_iso

Lifecycle = Literal["draft", "active", "paused", "archived"]
LifecycleAction = Literal["activate", "pause", "resume", "archive"]
GatedReason = Literal[
    "budget_exhausted", "budget_unavailable", "capability_disabled",
    "connection_revoked", "connection_reauthorization_required", "network_denied",
]
CATALOG_CAPABILITIES: tuple[str, ...] = (
    "inference", "gmail.read", "gmail.send", "reddit.read", "reddit.post", "network.fetch", "network.search",
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
    target = LIFECYCLE_TRANSITIONS.get((current, action))
    if target is None:
        raise AiclError("invalid_transition", f"cannot {action} an instance that is {current}",
                        **{"from": current, "action": action})
    return target


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


def _not_found() -> AiclError:
    return AiclError("not_found", "instance not found")


def _row_to_instance(row) -> AgentInstance:
    context = json.loads(row["gate_context"]) if row["gate_context"] else None
    return AgentInstance(
        id=row["id"], tenant_id=row["tenant_id"], owner_id=row["owner_id"], template_id=row["template_id"],
        name=row["name"], instructions=row["instructions"], lifecycle=row["lifecycle"],
        gated_reason=row["gated_reason"],
        gate_context=None if context is None else GateContext(tuple(context["capabilities"]), context["host_hash12"]),
        version=row["version"],
        limits=Limits(row["inference_daily_micro_usd"], row["inference_monthly_micro_usd"],
                      row["compute_daily_micro_usd"], row["compute_monthly_micro_usd"]),
        network_domains=tuple(json.loads(row["network_domains"])),
        created_at=from_iso(row["created_at"]), updated_at=from_iso(row["updated_at"]))


def _fetch(conn: Connection, auth: AuthContext, instance_id: str) -> AgentInstance:
    row = conn.execute("SELECT * FROM agent_instance WHERE id = ? AND tenant_id = ?",
                       (instance_id, auth.tenant_id)).fetchone()
    if row is None:
        raise _not_found()
    return _row_to_instance(row)


class SqliteInstanceRepository:
    """SQLite repository. Reads use the open unit of work, else a short read connection of the
    process database (the most recently migrated `Database`)."""

    def insert_draft(self, conn, auth, instance, grants):
        if instance.tenant_id != auth.tenant_id or instance.owner_id != auth.owner_id:
            raise _not_found()
        lim = instance.limits
        conn.execute(
            "INSERT INTO agent_instance (id, tenant_id, owner_id, template_id, name, instructions, lifecycle, "
            "gated_reason, gate_context, version, inference_daily_micro_usd, inference_monthly_micro_usd, "
            "compute_daily_micro_usd, compute_monthly_micro_usd, network_domains, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (instance.id, instance.tenant_id, instance.owner_id, instance.template_id, instance.name,
             instance.instructions, "draft", None, None, instance.version, lim.inference_daily_micro_usd,
             lim.inference_monthly_micro_usd, lim.compute_daily_micro_usd, lim.compute_monthly_micro_usd,
             json.dumps(list(instance.network_domains)), to_iso(instance.created_at), to_iso(instance.updated_at)))
        for grant in grants:
            conn.execute("INSERT INTO capability_grant (instance_id, capability, enabled) VALUES (?,?,?)",
                         (instance.id, grant.capability, int(grant.enabled)))
        return _fetch(conn, auth, instance.id)

    def get(self, auth, instance_id):
        with Database.current().reader() as conn:
            return _fetch(conn, auth, instance_id)

    def get_grants(self, auth, instance_id):
        with Database.current().reader() as conn:
            _fetch(conn, auth, instance_id)
            return tuple(CapabilityGrant(r["instance_id"], r["capability"], bool(r["enabled"])) for r in conn.execute(
                "SELECT * FROM capability_grant WHERE instance_id = ? ORDER BY capability", (instance_id,)))

    def set_gated(self, conn, auth, instance_id, reason, context):
        _fetch(conn, auth, instance_id)
        conn.execute("UPDATE agent_instance SET gated_reason = ?, gate_context = ? WHERE id = ? AND tenant_id = ?",
                     (reason, json.dumps({"capabilities": list(context.capabilities),
                                          "host_hash12": context.host_hash12}), instance_id, auth.tenant_id))
        return _fetch(conn, auth, instance_id)

    def clear_gated(self, conn, auth, instance_id):
        _fetch(conn, auth, instance_id)
        conn.execute("UPDATE agent_instance SET gated_reason = NULL, gate_context = NULL "
                     "WHERE id = ? AND tenant_id = ?", (instance_id, auth.tenant_id))
        return _fetch(conn, auth, instance_id)

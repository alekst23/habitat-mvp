"""Canonical creation service and snapshot reader (technical.md, owner E11-2). Contract stubs only."""

from __future__ import annotations

from sqlite3 import Connection

from aicl.control.auth import AuthContext
from aicl.creation.models import ActorKind, CreateInstanceRequest, CreateInstanceResult, InstanceSnapshot, Surface

NOT_IMPLEMENTED = "E11-2 behavior is not implemented (contract stub)"


def create_instance(auth: AuthContext, request: CreateInstanceRequest, *, actor_kind: ActorKind = "owner",
                    surface: Surface = "ui") -> CreateInstanceResult:
    """The one canonical creation function (wizard E11-3, tool `create_instance`, chat E11-4).

    One `db.transaction()`: validate (unknown template/capability, name 1..80 after trim+NFC,
    instructions 0..4000, control characters => AiclError validation_failed), insert the draft instance
    (version 1, all limits 0), one grant row per catalog capability, and the `instance.created` audit event
    via the existing AuditLog (details: template_id, surface). Idempotent on (tenant_id, idempotency_key):
    same digest => stored result, created=False; different digest => AiclError conflict with
    existing_result_id. `actor_kind` and `surface` come from the server-side caller only.
    """
    raise NotImplementedError(NOT_IMPLEMENTED)


def read_instance_snapshot(auth: AuthContext, instance_id: str) -> InstanceSnapshot:
    """Tenant-filtered lean view; another tenant's instance is AiclError not_found."""
    raise NotImplementedError(NOT_IMPLEMENTED)


def read_instance_snapshot_conn(conn: Connection, auth: AuthContext, instance_id: str) -> InstanceSnapshot:
    """`conn` form: reads inside the caller's open unit of work (used by every MutationResult)."""
    raise NotImplementedError(NOT_IMPLEMENTED)

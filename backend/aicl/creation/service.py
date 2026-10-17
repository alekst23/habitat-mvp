"""Canonical creation service and snapshot reader (technical.md, owner E11-2)."""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from datetime import timedelta
from sqlite3 import Connection

from aicl.clock import Clock, SystemClock
from aicl.control.audit import AuditEvent, SqliteAuditLog
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.control.instances import (
    CATALOG_CAPABILITIES, AgentInstance, CapabilityGrant, Limits, SqliteInstanceRepository,
)
from aicl.creation.models import (
    TEMPLATE_ID_DEFAULT, ActorKind, AttachmentView, CreateInstanceRequest, CreateInstanceResult,
    InstanceSnapshot, Surface,
)
from aicl.db import Database, from_iso, to_iso

NOT_IMPLEMENTED = "E11-2 behavior is not implemented (contract stub)"
DEFAULT_HOLD_STALE_SECONDS = 900
TEMPLATES = {TEMPLATE_ID_DEFAULT: {"version": 1, "name": "Default agent", "capabilities": list(CATALOG_CAPABILITIES)}}


def validation_failed(*fields: tuple[str, str]) -> AiclError:
    return AiclError("validation_failed", "invalid input", field_errors=[{"field": f, "code": c} for f, c in fields])


def _has_control(text: str) -> bool:
    return any(unicodedata.category(ch) == "Cc" and ch not in "\n\t" for ch in text)


def list_templates() -> dict:
    return {"templates": [{"template_id": tid, "name": t["name"], "capabilities": t["capabilities"],
                           "constraints": {"name_max": 80, "instructions_max": 4000}} for tid, t in TEMPLATES.items()]}


def create_instance(auth: AuthContext, request: CreateInstanceRequest, *, actor_kind: ActorKind = "owner",
                    surface: Surface = "ui", clock: Clock | None = None) -> CreateInstanceResult:
    """The one canonical creation function: validate, then insert instance, grants and audit event in one
    transaction, idempotent on (tenant_id, idempotency_key)."""
    clock = clock or SystemClock()
    errors: list[tuple[str, str]] = []
    if request.template_id not in TEMPLATES:
        errors.append(("template_id", "unknown_template"))
    name = unicodedata.normalize("NFC", request.name).strip()
    if not 1 <= len(name) <= 80:
        errors.append(("name", "length"))
    elif _has_control(name):
        errors.append(("name", "control_character"))
    if len(request.instructions) > 4000:
        errors.append(("instructions", "length"))
    elif _has_control(request.instructions):
        errors.append(("instructions", "control_character"))
    for capability in sorted(request.enabled_capabilities):
        if capability not in CATALOG_CAPABILITIES:
            errors.append(("enabled_capabilities", "unknown_capability"))
            break
    if errors:
        raise validation_failed(*errors)
    digest = hashlib.sha256(json.dumps(
        {"template_id": request.template_id, "name": name, "instructions": request.instructions,
         "enabled_capabilities": sorted(request.enabled_capabilities)}, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    db = Database.current()
    with db.transaction() as conn:
        existing = conn.execute("SELECT * FROM create_request WHERE tenant_id = ? AND idempotency_key = ?",
                                (auth.tenant_id, request.idempotency_key)).fetchone()
        if existing is not None:
            if existing["request_digest"] != digest:
                raise AiclError("conflict", "idempotency key was used with a different request",
                                existing_result_id=existing["instance_id"])
            snapshot = read_instance_snapshot_conn(conn, auth, existing["instance_id"], clock=clock)
            return CreateInstanceResult(snapshot, False, existing["audit_event_id"])
        now = clock.now()
        instance = AgentInstance(
            id=str(uuid.uuid4()), tenant_id=auth.tenant_id, owner_id=auth.owner_id, template_id=request.template_id,
            name=name, instructions=request.instructions, lifecycle="draft", gated_reason=None, gate_context=None,
            version=1, limits=Limits(), network_domains=(), created_at=now, updated_at=now)
        grants = tuple(CapabilityGrant(instance.id, c, c in request.enabled_capabilities)
                       for c in CATALOG_CAPABILITIES)
        SqliteInstanceRepository().insert_draft(conn, auth, instance, grants)
        event = SqliteAuditLog(clock).append(conn, AuditEvent(
            "instance.created", actor_kind, "committed", auth.tenant_id, auth.owner_id, instance.id,
            details={"template_id": request.template_id, "surface": surface}))
        conn.execute("INSERT INTO create_request (tenant_id, idempotency_key, request_digest, instance_id, "
                     "audit_event_id, created_at) VALUES (?,?,?,?,?,?)",
                     (auth.tenant_id, request.idempotency_key, digest, instance.id, event.seq, to_iso(now)))
        return CreateInstanceResult(read_instance_snapshot_conn(conn, auth, instance.id, clock=clock), True, event.seq)


def read_instance_snapshot(auth: AuthContext, instance_id: str, *, clock: Clock | None = None,
                           hold_stale_seconds: int = DEFAULT_HOLD_STALE_SECONDS) -> InstanceSnapshot:
    with Database.current().reader() as conn:
        return read_instance_snapshot_conn(conn, auth, instance_id, clock=clock, hold_stale_seconds=hold_stale_seconds)


def read_instance_snapshot_conn(conn: Connection, auth: AuthContext, instance_id: str, *, clock: Clock | None = None,
                                hold_stale_seconds: int = DEFAULT_HOLD_STALE_SECONDS) -> InstanceSnapshot:
    """Reads inside the caller's open unit of work (used by every MutationResult)."""
    row = conn.execute("SELECT * FROM agent_instance WHERE id = ? AND tenant_id = ?",
                       (instance_id, auth.tenant_id)).fetchone()
    if row is None:
        raise AiclError("not_found", "instance not found")
    now = (clock or SystemClock()).now()
    grants = {r["capability"]: bool(r["enabled"]) for r in conn.execute(
        "SELECT capability, enabled FROM capability_grant WHERE instance_id = ?", (instance_id,))}
    capabilities = {c: grants.get(c, False) for c in CATALOG_CAPABILITIES}
    active = row["lifecycle"] == "active"
    gated_reason = row["gated_reason"] if active else None
    blocking = conn.execute(
        "SELECT count(*) FROM budget_hold WHERE instance_id = ? AND (state = 'unknown' OR (state = 'held' AND "
        "created_at < ?))", (instance_id, to_iso(now - timedelta(seconds=hold_stale_seconds)))
    ).fetchone()[0]
    status = "gated" if active and (gated_reason or blocking) else row["lifecycle"]
    attachments = _attachments(conn, instance_id)
    return InstanceSnapshot(
        id=row["id"], template_id=row["template_id"], name=row["name"], instructions=row["instructions"],
        lifecycle=row["lifecycle"], status=status, gated_reason=gated_reason, version=row["version"],
        limits=Limits(row["inference_daily_micro_usd"], row["inference_monthly_micro_usd"],
                      row["compute_daily_micro_usd"], row["compute_monthly_micro_usd"]),
        capabilities=capabilities, network_domains=tuple(json.loads(row["network_domains"])),
        attachments=attachments, created_at=from_iso(row["created_at"]), updated_at=from_iso(row["updated_at"]))


def _attachments(conn: Connection, instance_id: str) -> tuple[AttachmentView, ...]:
    rows = conn.execute(
        "SELECT a.capability, a.connection_id, c.display_name, c.status FROM connection_attachment a "
        "JOIN connection c ON c.id = a.connection_id WHERE a.instance_id = ? AND a.detached_at IS NULL "
        "ORDER BY a.capability", (instance_id,))
    return tuple(AttachmentView(r["capability"], r["connection_id"], r["display_name"], r["status"]) for r in rows)

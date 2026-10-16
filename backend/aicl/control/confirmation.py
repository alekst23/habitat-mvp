"""ActionConfirmation and PendingAction (technical.md "ActionConfirmation and PendingAction", E11-1)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import Protocol

from aicl.clock import Clock, SystemClock
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso

CONFIRMED_CAPABILITIES: tuple[str, ...] = ("gmail.send", "reddit.post")


@dataclass(frozen=True)
class PendingAction:
    id: str
    instance_id: str
    tenant_id: str
    capability: str
    payload_digest: str
    preview: dict[str, object]  # bounded allow-listed summary, never the body
    created_at: datetime


@dataclass(frozen=True)
class ActionConfirmation:
    id: str
    pending_action_id: str
    instance_id: str
    capability: str
    payload_digest: str
    owner_id: str
    tenant_id: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None


def payload_digest(instance_id: str, capability: str, payload: object) -> str:
    """sha256 of canonical JSON {instance_id, capability, payload}: sorted keys, no whitespace, UTF-8."""
    canonical = json.dumps({"instance_id": instance_id, "capability": capability, "payload": payload},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ConfirmationStore(Protocol):
    def create_confirmation(self, conn: Connection, auth: AuthContext, pending_action_id: str) -> ActionConfirmation:
        """Owner-authenticated, CSRF-protected UI only; idempotent per pending action."""
        ...

    def consume_confirmation(self, conn: Connection, confirmation_id: str, computed_digest: str,
                             now: datetime) -> bool:
        """Single conditional update (used_at IS NULL AND expires_at > now AND digest equal)."""
        ...


def _to_confirmation(row) -> ActionConfirmation:
    return ActionConfirmation(
        id=row["id"], pending_action_id=row["pending_action_id"], instance_id=row["instance_id"],
        capability=row["capability"], payload_digest=row["payload_digest"], owner_id=row["owner_id"],
        tenant_id=row["tenant_id"], created_at=from_iso(row["created_at"]), expires_at=from_iso(row["expires_at"]),
        used_at=None if row["used_at"] is None else from_iso(row["used_at"]))


class SqliteConfirmationStore:
    def __init__(self, ttl_seconds: int, clock: Clock | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self.clock = clock or SystemClock()

    def create_confirmation(self, conn, auth, pending_action_id):
        pending = conn.execute("SELECT * FROM pending_action WHERE id = ? AND tenant_id = ?",
                               (pending_action_id, auth.tenant_id)).fetchone()
        if pending is None:
            raise AiclError("not_found", "pending action not found")
        existing = conn.execute("SELECT * FROM action_confirmation WHERE pending_action_id = ?",
                                (pending_action_id,)).fetchone()
        if existing is None:
            now = self.clock.now()
            conn.execute(
                "INSERT INTO action_confirmation (id, pending_action_id, instance_id, capability, payload_digest, "
                "owner_id, tenant_id, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), pending_action_id, pending["instance_id"], pending["capability"],
                 pending["payload_digest"], auth.owner_id, auth.tenant_id, to_iso(now),
                 to_iso(now + timedelta(seconds=self.ttl_seconds))))
            existing = conn.execute("SELECT * FROM action_confirmation WHERE pending_action_id = ?",
                                    (pending_action_id,)).fetchone()
        return _to_confirmation(existing)

    def consume_confirmation(self, conn, confirmation_id, computed_digest, now):
        cursor = conn.execute(
            "UPDATE action_confirmation SET used_at = ? WHERE id = ? AND used_at IS NULL AND expires_at > ? "
            "AND payload_digest = ?", (to_iso(now), confirmation_id, to_iso(now), computed_digest))
        return cursor.rowcount == 1

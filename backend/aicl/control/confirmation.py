"""ActionConfirmation and PendingAction (technical.md "ActionConfirmation and PendingAction", E11-1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection
from typing import Protocol

from aicl.control.auth import AuthContext

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
    raise NotImplementedError("payload_digest is not implemented (E11-1)")


class ConfirmationStore(Protocol):
    def create_confirmation(self, conn: Connection, auth: AuthContext, pending_action_id: str) -> ActionConfirmation:
        """Owner-authenticated, CSRF-protected UI only; idempotent per pending action."""
        ...

    def consume_confirmation(self, conn: Connection, confirmation_id: str, computed_digest: str,
                             now: datetime) -> bool:
        """Single conditional update (used_at IS NULL AND expires_at > now AND digest equal)."""
        ...


class SqliteConfirmationStore:
    """Stub: raises NotImplementedError; consumption never returns True."""

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds

    def create_confirmation(self, conn, auth, pending_action_id):
        raise NotImplementedError("create_confirmation is not implemented (E11-1)")

    def consume_confirmation(self, conn, confirmation_id, computed_digest, now):
        raise NotImplementedError("consume_confirmation is not implemented (E11-1)")

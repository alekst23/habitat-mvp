"""Plain helpers shared by tests (no fixtures)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import timezone
from pathlib import Path

from aicl.control.errors import AiclError
from aicl.settings import SettingsError

REPO = Path(__file__).resolve().parents[2]
EXAMPLE_PRICE_TABLE = REPO / "backend" / "aicl" / "price_table.example.json"

# A startup failure is a typed error or an OS/storage error. NotImplementedError (an unimplemented
# stub) and AssertionError are deliberately NOT in this tuple, so a stub can never satisfy it.
STARTUP_FAILURES = (AiclError, SettingsError, ValueError, OSError, sqlite3.Error)


class Abort(Exception):
    """Raised by a test to abort a unit of work. Not a RuntimeError, so an unimplemented stub
    (NotImplementedError) can never be mistaken for the intended abort."""


def work_id(n: int) -> str:
    """A work_id/idempotency key matching ^[A-Za-z0-9_-]{16,64}$."""
    return f"work_{n:030d}"


def table_names(conn: sqlite3.Connection, fragment: str) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
                        (f"%{fragment}%",)).fetchall()
    return [r[0] for r in rows]


def add_pending_action(conn: sqlite3.Connection, instance, digest: str, capability: str = "gmail.send") -> str:
    """Insert a PendingAction row (the gate that creates it belongs to E11-2). The table is found by
    the name fragment 'pending' and filled by the documented PendingAction field names (A5/A9)."""
    (table,) = table_names(conn, "pending")
    pending_id = str(uuid.uuid4())
    values = {"id": pending_id, "instance_id": instance.id, "tenant_id": instance.tenant_id,
              "capability": capability, "payload_digest": digest,
              "preview": json.dumps({"recipient_domain": "example.com", "body_length": 2}),
              "created_at": instance.created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    used = {c: values[c] for c in columns if c in values}
    conn.execute(f"INSERT INTO {table} ({', '.join(used)}) VALUES ({', '.join('?' * len(used))})",
                 tuple(used.values()))
    return pending_id

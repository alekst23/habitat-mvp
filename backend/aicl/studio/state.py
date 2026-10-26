"""Opaque owner-specific Studio layout state with bounded JSON and stale-save protection."""
from __future__ import annotations

import json

from aicl.control.errors import AiclError
from aicl.db import to_iso

MAX_STATE_BYTES = 262_144


def validate_json(value, depth=0):
    if depth > 24:
        raise AiclError("validation_failed", "Dashboard state is too deeply nested.")
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("__proto__", "prototype", "constructor"):
                raise AiclError("validation_failed", "Unsupported dashboard state field.")
            validate_json(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            validate_json(item, depth + 1)


class StudioState:
    def __init__(self, ctx):
        self.db, self.clock = ctx.db, ctx.clock

    def read(self, auth):
        with self.db.reader() as conn:
            row = conn.execute("SELECT state_json,version,updated_at FROM studio_layout WHERE tenant_id=? AND owner_id=?",
                               (auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            return {"state": None, "version": 0}
        return {"state": json.loads(row["state_json"]) if row["state_json"] else None,
                "version": row["version"], "updated_at": row["updated_at"]}

    def save(self, auth, state, expected_version):
        if (state is not None and not isinstance(state, dict)) or type(expected_version) is not int or expected_version < 0:
            raise AiclError("validation_failed", "Supply dashboard state and its current version.")
        validate_json(state)
        try:
            encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError):
            raise AiclError("validation_failed", "Dashboard state must be valid JSON.") from None
        if len(encoded.encode()) > MAX_STATE_BYTES:
            raise AiclError("validation_failed", "Dashboard state exceeds 256 KiB.")
        now = to_iso(self.clock.now())
        with self.db.transaction() as conn:
            row = conn.execute("SELECT version FROM studio_layout WHERE tenant_id=? AND owner_id=?",
                               (auth.tenant_id, auth.owner_id)).fetchone()
            current = row[0] if row else 0
            if current != expected_version:
                raise AiclError("conflict", "This layout changed in another tab. Reload before saving.", current_version=current)
            conn.execute("INSERT INTO studio_layout VALUES (?,?,?,?,?) ON CONFLICT(tenant_id,owner_id) DO UPDATE SET "
                         "state_json=excluded.state_json,version=excluded.version,updated_at=excluded.updated_at",
                         (auth.tenant_id, auth.owner_id, encoded if state is not None else None, current + 1, now))
        return {"state": state, "version": current + 1, "updated_at": now}

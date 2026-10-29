"""Per-workspace setup attribution without erasing provider costs or holds.

Pending settled setup costs and in-flight reservations already reduce available
agent credit. Activation converts pending amounts into immutable charges, so
the same cost is never deducted a second time. Provider-wide underwriting still
uses the original assistant attempts, including amounts waived for an owner.
"""
from __future__ import annotations

import re
import uuid

from aicl.control.audit import AuditEvent, SqliteAuditLog
from aicl.control.errors import AiclError
from aicl.db import to_iso


_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ATTEMPTS = (
    "FROM assistant_inference_attempt a JOIN assistant_turn t ON t.id=a.turn_id "
    "JOIN agent_workspace w ON w.session_id=t.session_id "
    "LEFT JOIN workspace_setup_charge c ON c.attempt_id=a.id "
    "LEFT JOIN workspace_setup_waiver v ON v.attempt_id=a.id "
    "WHERE w.id=? AND a.tenant_id=w.tenant_id AND a.owner_id=w.owner_id "
    # Old creator conversations could manage several agents. Their pre-workspace
    # turns cannot be assigned to one agent merely because it was opened first.
    # Preserve any immutable prior attribution and all later workspace turns.
    "AND (c.attempt_id IS NOT NULL OR v.attempt_id IS NOT NULL OR t.created_at>=w.created_at OR "
    "(SELECT COUNT(*) FROM ("
    "SELECT p.instance_id FROM assistant_proposal p WHERE p.session_id=w.session_id AND p.state='committed' "
    "AND p.instance_id IS NOT NULL AND p.tenant_id=w.tenant_id AND p.owner_id=w.owner_id "
    "UNION SELECT r.instance_id FROM agent_chat_run l JOIN agent_run r ON r.id=l.run_id "
    "WHERE l.session_id=w.session_id AND r.tenant_id=w.tenant_id AND r.owner_id=w.owner_id"
    "))<=1) "
)


def usage(conn, workspace_id):
    """Read a scoped projection; no reset, recovery, debit or hold mutation."""
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN a.state='settled' THEN a.cost_micro_usd ELSE 0 END),0) raw, "
        "COALESCE(SUM(CASE WHEN a.state IN ('held','unknown') THEN a.reserved_micro_usd ELSE 0 END),0) held, "
        "COALESCE(SUM(CASE WHEN a.state='settled' AND c.attempt_id IS NULL AND v.attempt_id IS NULL "
        "THEN a.cost_micro_usd ELSE 0 END),0) pending, "
        "COALESCE(SUM(c.cost_micro_usd),0) charged, COALESCE(SUM(v.cost_micro_usd),0) waived, "
        "COALESCE(MAX(CASE WHEN a.state='unknown' OR a.reason='usage_exceeded_bound' THEN 1 ELSE 0 END),0) unknown, "
        "COALESCE(MAX(CASE WHEN a.state='held' THEN 1 ELSE 0 END),0) inflight " + _ATTEMPTS,
        (workspace_id,),
    ).fetchone()
    running = conn.execute("SELECT 1 FROM assistant_turn t JOIN agent_workspace w ON w.session_id=t.session_id "
                           "WHERE w.id=? AND t.state='running' LIMIT 1", (workspace_id,)).fetchone()
    return {"scope": "workspace", "workspace_id": workspace_id, "raw_spent_micro_usd": row["raw"],
            "spent_micro_usd": row["raw"] - row["waived"], "held_micro_usd": row["held"],
            "pending_micro_usd": row["pending"], "charged_micro_usd": row["charged"],
            "waived_micro_usd": row["waived"], "unknown": bool(row["unknown"]),
            "busy": bool(row["inflight"] or running)}


def attempts(conn, workspace_id):
    """Minimal usage evidence with the same attribution rules as the balance.

    Callers must resolve the workspace from authenticated owner scope first.
    No conversation text, provider response identifiers or secrets are returned.
    """
    return [dict(row) for row in conn.execute(
        "SELECT a.id,a.state,a.cost_micro_usd,a.reserved_micro_usd,a.input_tokens,a.output_tokens,"
        "a.model,a.price_version,a.created_at,a.updated_at,"
        "c.attempt_id AS charged_attempt_id,v.attempt_id AS waived_attempt_id " + _ATTEMPTS +
        "ORDER BY a.created_at,a.id", (workspace_id,))]


def balance_cost(conn, instance_id):
    """Total attributed setup exposure, subtracted once by commerce._balance."""
    workspace = conn.execute("SELECT id FROM agent_workspace WHERE instance_id=?", (instance_id,)).fetchone()
    if workspace is None:
        return 0
    amounts = usage(conn, workspace["id"])
    return amounts["charged_micro_usd"] + amounts["pending_micro_usd"] + amounts["held_micro_usd"]


class WorkspaceSetupAccounting:
    def __init__(self, ctx):
        self.db, self.clock = ctx.db, ctx.clock

    def _owned(self, conn, auth, workspace_id):
        if auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "Sign in to continue.")
        workspace = conn.execute("SELECT * FROM agent_workspace WHERE id=? AND tenant_id=? AND owner_id=?",
                                 (workspace_id, auth.tenant_id, auth.owner_id)).fetchone()
        if workspace is None:
            raise AiclError("not_found", "Workspace not found.")
        return workspace

    def view(self, auth, workspace_id):
        with self.db.reader() as conn:
            self._owned(conn, auth, workspace_id)
            return usage(conn, workspace_id)

    @staticmethod
    def _pending(conn, workspace_id):
        return conn.execute("SELECT a.id,a.cost_micro_usd " + _ATTEMPTS +
                            "AND a.state='settled' AND c.attempt_id IS NULL AND v.attempt_id IS NULL ORDER BY a.id",
                            (workspace_id,)).fetchall()

    def _audit(self, conn, auth, workspace, action, rows, reason=None):
        SqliteAuditLog(self.clock).append(conn, AuditEvent(
            "commerce.policy_changed", "owner", "committed", auth.tenant_id, auth.owner_id,
            workspace["instance_id"], reason=reason,
            details={"action": action, "count": len(rows), "micro_usd": sum(row["cost_micro_usd"] for row in rows)}))

    def charge(self, auth, workspace_id):
        """Settle attribution inside the same transaction as owner activation."""
        from aicl.commerce.service import MockCommerceService
        with self.db.transaction() as conn:
            workspace = self._owned(conn, auth, workspace_id)
            amounts = usage(conn, workspace_id)
            if amounts["unknown"]:
                raise AiclError("denied", "Resolve the pending setup usage before activating this agent.", reason="setup_unresolved")
            if amounts["busy"]:
                raise AiclError("denied", "Wait for the setup assistant to finish before activating this agent.", reason="setup_in_progress")
            if not workspace["instance_id"]:
                raise AiclError("invalid_state", "Apply the agent settings before activating it.")
            # _balance already deducts pending setup. Converting its attribution
            # below changes no available credit and must not charge it twice.
            if MockCommerceService(self.db, self.clock)._balance(conn, workspace["instance_id"]) < 0:
                raise AiclError("denied", "Add enough service credit to cover this agent's setup cost.", reason="credit_insufficient")
            rows = self._pending(conn, workspace_id)
            now = to_iso(self.clock.now())
            conn.executemany("INSERT INTO workspace_setup_charge(attempt_id,workspace_id,instance_id,cost_micro_usd,created_at) VALUES (?,?,?,?,?)",
                             [(row["id"], workspace_id, workspace["instance_id"], row["cost_micro_usd"], now) for row in rows])
            if rows:
                self._audit(conn, auth, workspace, "workspace_setup_charged", rows)
            return usage(conn, workspace_id)

    def waive(self, auth, workspace_id, request_id, reason):
        """Explicit local reset: waive known uncharged attempts, preserving holds.

        This operator-authorized operation is not an assistant tool or a public
        reset control. A repeated request never waives newly accrued usage.
        Already charged usage remains an immutable debit rather than a refund.
        """
        if any(not isinstance(value, str) or not _CODE.fullmatch(value) for value in (request_id, reason)):
            raise AiclError("validation_failed", "A bounded reset identifier and reason code are required.")
        with self.db.transaction() as conn:
            workspace = self._owned(conn, auth, workspace_id)
            existing = conn.execute("SELECT reason FROM workspace_setup_reset WHERE workspace_id=? AND request_id=?",
                                    (workspace_id, request_id)).fetchone()
            if existing:
                if existing["reason"] != reason:
                    raise AiclError("conflict", "This setup reset identifier was used for a different reason.")
                return usage(conn, workspace_id)
            reset_id, now = str(uuid.uuid4()), to_iso(self.clock.now())
            conn.execute("INSERT INTO workspace_setup_reset(id,workspace_id,request_id,reason,tenant_id,owner_id,created_at) VALUES (?,?,?,?,?,?,?)",
                         (reset_id, workspace_id, request_id, reason, auth.tenant_id, auth.owner_id, now))
            rows = self._pending(conn, workspace_id)
            conn.executemany("INSERT INTO workspace_setup_waiver(attempt_id,workspace_id,reset_id,cost_micro_usd,created_at) VALUES (?,?,?,?,?)",
                             [(row["id"], workspace_id, reset_id, row["cost_micro_usd"], now) for row in rows])
            self._audit(conn, auth, workspace, "workspace_setup_waived", rows, reason)
            return usage(conn, workspace_id)

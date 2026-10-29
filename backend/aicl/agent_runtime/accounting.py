"""Durable execution uses the existing budget ledger and service-credit account.

All mutations run in the coordinator's transaction. This module never dispatches
work, commits, or treats an interrupted operation as proof that no charge occurred.
"""
from __future__ import annotations

import re

from aicl.commerce.service import MockCommerceService
from aicl.control.audit import SqliteAuditLog
from aicl.control.auth import AuthContext
from aicl.control.budget import Estimate, MeasuredUsage, NoUsage, SqliteBudgetPort, _hold
from aicl.control.errors import AiclError
from aicl.control.price_table import cost_micro_usd, effective_version, load_version
from aicl.db import to_iso
from aicl.work.gate import SqliteBudgetAuditRecorder
from aicl.workflow.service import MockWorkflowService

_OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_RUNTIME_HOLD = "EXISTS (SELECT 1 FROM agent_runtime_hold r WHERE r.hold_id=h.id)"
_PROVIDER_HOLD = (
    "(" + _RUNTIME_HOLD
    + " OR EXISTS (SELECT 1 FROM workflow_inference_attempt a WHERE a.hold_id=h.id)"
    + " OR EXISTS (SELECT 1 FROM render_dispatch d WHERE d.hold_id=h.id))"
)


def platform_spend(conn, category: str) -> int:
    """Tracked provider/runtime lifetime amounts, once per canonical hold.

    Render's compute record and commerce's debit are projections of budget_usage,
    so neither is added again. Unrelated FakeWorkExecutor simulation charges
    still consume their instance budget, but not the real-provider ceiling.
    Call under BEGIN IMMEDIATE for admission.
    """
    if category not in ("inference", "compute"):
        raise ValueError("unsupported spend category")
    column = category + "_micro_usd"
    return conn.execute(
        f"SELECT COALESCE(SUM(u.{column}),0) + COALESCE(SUM(CASE "
        f"WHEN h.state IN ('held','unknown') THEN h.{column} ELSE 0 END),0) "
        "FROM budget_hold h LEFT JOIN budget_usage u ON u.hold_id=h.id "
        "WHERE " + _PROVIDER_HOLD).fetchone()[0]


def runtime_reconciliation_pending(conn) -> bool:
    """Unknown charges and trusted provider limit violations stop new paid work."""
    return _reconciliation_pending(conn, _RUNTIME_HOLD)


def _reconciliation_pending(conn, ownership) -> bool:
    return conn.execute(
        "SELECT 1 FROM budget_hold h LEFT JOIN budget_usage u ON u.hold_id=h.id "
        "WHERE " + ownership + " AND (h.state='unknown' "
        "OR u.inference_input_tokens > h.est_input_tokens "
        "OR u.inference_output_tokens > h.est_output_tokens "
        "OR u.compute_minutes > h.est_compute_minutes "
        "OR u.web_search_calls > h.est_web_search_calls "
        "OR EXISTS (SELECT 1 FROM agent_step s WHERE s.hold_id=h.id "
        "AND json_type(s.receipt_metadata_json,'$.bounds_exceeded')='true')) LIMIT 1").fetchone() is not None


class RuntimeAccounting:
    def __init__(self, db, clock, platform_limit_micro_usd=1_000_000):
        if type(platform_limit_micro_usd) is not int or platform_limit_micro_usd <= 0:
            raise ValueError("platform_limit_micro_usd must be a positive integer")
        self.db, self.clock, self.platform_limit_micro_usd = db, clock, platform_limit_micro_usd
        self.budget = SqliteBudgetPort(db, clock, 900)
        self.commerce = MockCommerceService(db, clock)
        self._workspace_controls = MockWorkflowService(db, clock, self.commerce)
        self.recorder = SqliteBudgetAuditRecorder(SqliteAuditLog(clock))

    def _require_demo_active(self, conn, auth):
        # Worker identities may outlive the private workspace that admitted a
        # run. Reuse its current server-clock boundary, independently of auth TTL.
        self._workspace_controls._require_demo_active(conn, auth)

    def _controls(self, conn, auth, instance_id):
        instance = self.commerce._controls(conn, auth, instance_id, allow_setup_busy=True)
        self._require_demo_active(conn, auth)
        return instance

    def _price_estimate(self, conn, estimate, price_version=None):
        """Use the adapter's pinned prices for both previews and reservations."""
        if not isinstance(estimate, Estimate) or any(
            type(value) is not int or not 0 <= value <= 10**12 for value in (
                estimate.inference_input_tokens, estimate.inference_output_tokens,
                estimate.compute_minutes, estimate.web_search_calls)):
            raise AiclError("validation_failed", "estimate must contain bounded nonnegative integers")
        try:
            version = load_version(conn, price_version) if price_version else effective_version(conn, self.clock.now())
        except AiclError:
            version = None
        if version is None or version.effective_from > self.clock.now():
            raise AiclError("denied", "Price information is unavailable.", reason="price_unavailable")
        try:
            costs = {
                "inference": cost_micro_usd(version, "inference.input_tokens", estimate.inference_input_tokens)
                + cost_micro_usd(version, "inference.output_tokens", estimate.inference_output_tokens)
                + cost_micro_usd(version, "inference.web_search_calls", estimate.web_search_calls),
                "compute": cost_micro_usd(version, "compute.minutes", estimate.compute_minutes),
            }
        except AiclError as error:
            if error.error == "unavailable":
                raise AiclError("denied", "Price information is unavailable.", reason="price_unavailable") from None
            raise
        return version, costs

    def _provider_reconciliation_pending(self, conn):
        return bool(_reconciliation_pending(conn, _PROVIDER_HOLD) or conn.execute(
            "SELECT 1 FROM workflow_inference_attempt WHERE state IN ('inflight','unknown') "
            "OR validation_error='usage_exceeded_bound' LIMIT 1").fetchone() or conn.execute(
            "SELECT 1 FROM render_dispatch WHERE state IN ('submission_unknown','unknown') LIMIT 1").fetchone())

    def readiness(self, conn, auth, instance_id, estimate, run_limit_micro_usd,
                  run_spent_held_micro_usd=0, *, price_version=None, allow_draft=False):
        """Read admission requirements without creating holds, orders, or events.

        This is advisory until checked in the start/resume transaction. Dispatch
        still reserves against the current controls and balance atomically.
        """
        inst = self.commerce._owned_instance(conn, auth, instance_id)
        balance = self.commerce._balance(conn, instance_id)
        blockers = []

        def blocked(reason, message):
            if not any(item["reason"] == reason for item in blockers):
                blockers.append({"reason": reason, "message": message})

        try:
            self._require_demo_active(conn, auth)
        except AiclError as error:
            blocked(str(error.extra.get("reason", error.error)), error.message)
        if inst["lifecycle"] != "active" and not (allow_draft and inst["lifecycle"] == "draft"):
            blocked("instance_not_active", "Activate or resume the agent before continuing.")
        grant = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability='inference'",
                             (instance_id,)).fetchone()
        if not grant or not grant[0]:
            blocked("capability_disabled", "Agent processing is unavailable. Reapply this agent’s settings before continuing.")
        if inst["gated_reason"]:
            blocked("gate_unresolved", "Resolve the agent's existing control gate before continuing.")
        if self._provider_reconciliation_pending(conn) or self.budget._blocking(conn, instance_id, self.clock.now()):
            blocked("reconciliation_pending", "Resolve the earlier paid operation before continuing.")
        costs, maximum = None, None
        try:
            _, costs = self._price_estimate(conn, estimate, price_version)
            maximum = sum(costs.values())
        except AiclError as error:
            blocked(str(error.extra.get("reason", error.error)), error.message)
        if maximum is not None:
            if run_spent_held_micro_usd + maximum > run_limit_micro_usd:
                blocked("run_budget_exhausted", "The session's cumulative budget is exhausted.")
            if platform_spend(conn, "inference") + platform_spend(conn, "compute") + maximum > self.platform_limit_micro_usd:
                blocked("platform_spend_ceiling", "The server's spend ceiling is reached.")
            if balance < maximum:
                blocked("credit_insufficient", "Add service credit to cover the next step before starting or resuming work.")
        for category, windows in self.budget._amounts(conn, inst, self.clock.now()).items():
            for amounts in windows.values():
                if amounts.limit < 0:
                    blocked("budget_unavailable", "Review this agent's daily and monthly spending limits.")
                elif amounts.limit == 0 or (costs is not None and costs[category] > amounts.available):
                    blocked("budget_exhausted", "Set positive daily and monthly inference and compute limits with room for the next step.")
        return {"ready": not blockers, "balance_micro_usd": balance, "required_micro_usd": maximum,
                "blockers": blockers}

    def reserve(self, conn, auth, instance_id, operation_id, estimate: Estimate,
                run_limit_micro_usd, run_spent_held_micro_usd, *, price_version=None):
        """Reserve and register ownership atomically before dispatch.

        The coordinator derives the cumulative run amount from persisted state;
        none of these limits or identifiers come from model decisions.
        """
        if not conn.in_transaction:
            raise AiclError("conflict", "runtime reservations require a transaction")
        self._controls(conn, auth, instance_id)
        if not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(operation_id):
            raise AiclError("validation_failed", "operation_id must be a stable identifier")
        if not isinstance(estimate, Estimate) or any(
            type(value) is not int or not 0 <= value <= 10**12 for value in (
                estimate.inference_input_tokens, estimate.inference_output_tokens,
                estimate.compute_minutes, estimate.web_search_calls)):
            raise AiclError("validation_failed", "estimate must contain bounded nonnegative integers")
        if any(type(value) is not int or value < 0 for value in
               (run_limit_micro_usd, run_spent_held_micro_usd)) or run_limit_micro_usd == 0:
            raise AiclError("validation_failed", "run budget must be finite and positive")
        prior = conn.execute("SELECT * FROM agent_runtime_hold WHERE operation_id=?", (operation_id,)).fetchone()
        if prior:
            if (prior["tenant_id"], prior["owner_id"], prior["instance_id"]) != (
                    auth.tenant_id, auth.owner_id, instance_id):
                raise AiclError("conflict", "operation identity is already reserved")
            # Canonical replay verifies the original estimate and returns the
            # same terminal/unknown hold; it never grants another dispatch.
            return self.budget.reserve(conn, instance_id, "runtime:" + operation_id, estimate,
                                       price_table_version=price_version)
        if conn.execute("SELECT 1 FROM budget_hold WHERE instance_id=? AND work_id=?",
                        (instance_id, "runtime:" + operation_id)).fetchone():
            raise AiclError("conflict", "operation identity belongs to another reservation owner")
        if self._provider_reconciliation_pending(conn):
            raise AiclError("denied", "An earlier paid operation needs reconciliation.", reason="reconciliation_pending")
        version, costs = self._price_estimate(conn, estimate, price_version)
        maximum = sum(costs.values())
        if run_spent_held_micro_usd + maximum > run_limit_micro_usd:
            raise AiclError("denied", "The session's cumulative budget is exhausted.", reason="run_budget_exhausted")
        if platform_spend(conn, "inference") + platform_spend(conn, "compute") + maximum > self.platform_limit_micro_usd:
            raise AiclError("denied", "The server's spend ceiling is reached.", reason="platform_spend_ceiling")
        if self.commerce._balance(conn, instance_id) < maximum:
            raise AiclError("denied", "Service credit must cover the bounded estimate.", reason="credit_insufficient")
        hold = self.budget.reserve(conn, instance_id, "runtime:" + operation_id, estimate,
                                   price_table_version=version.version)
        conn.execute("INSERT INTO agent_runtime_hold "
                     "(hold_id,operation_id,tenant_id,owner_id,instance_id,created_at) VALUES (?,?,?,?,?,?)",
                     (hold.id, operation_id, auth.tenant_id, auth.owner_id, instance_id, to_iso(self.clock.now())))
        self.recorder.reserved(conn, auth, hold)
        return hold

    def _owned_hold(self, conn, hold_id):
        if not conn.in_transaction:
            raise AiclError("conflict", "runtime accounting requires a transaction")
        row = conn.execute("SELECT h.*,r.tenant_id,r.owner_id FROM budget_hold h "
                           "JOIN agent_runtime_hold r ON r.hold_id=h.id WHERE h.id=?", (hold_id,)).fetchone()
        if row is None:
            raise AiclError("not_found", "runtime hold not found")
        return _hold(row), AuthContext(row["owner_id"], row["tenant_id"], "runtime", self.clock.now())

    def settle(self, conn, hold_id, usage: MeasuredUsage):
        hold, auth = self._owned_hold(conn, hold_id)
        measured = (self.budget.reconcile(conn, hold_id, usage) if hold.state == "unknown"
                    else self.budget.settle(conn, hold_id, usage))
        if hold.state != "settled":
            self.recorder.settled(conn, auth, hold, measured)
            if hold.state == "unknown":
                self.recorder.reconciled(conn, auth, hold, measured)
            if (measured.inference_micro_usd > hold.inference_micro_usd
                    or measured.compute_micro_usd > hold.compute_micro_usd):
                self.recorder.overrun(conn, auth, hold, measured)
        return measured

    def mark_unknown(self, conn, hold_id):
        hold, auth = self._owned_hold(conn, hold_id)
        result = self.budget.mark_unknown(conn, hold_id)
        if hold.state != "unknown":
            self.recorder.unknown(conn, auth, hold)
        return result

    def release(self, conn, hold_id):
        """Only for proven pre-dispatch cancellation; unknowns remain held."""
        hold, auth = self._owned_hold(conn, hold_id)
        if hold.state == "unknown":
            raise AiclError("denied", "Unknown outcomes require reconciliation.", reason="reconciliation_pending")
        result = self.budget.release(conn, hold_id)
        if hold.state != "released":
            self.recorder.reconciled(conn, auth, hold, None)
        return result

    def reconcile_no_charge(self, conn, hold_id):
        """Trusted adapter rejection evidence can resolve an uncertain charge."""
        hold, auth = self._owned_hold(conn, hold_id)
        result = self.budget.reconcile(conn, hold_id, NoUsage())
        if hold.state != "released":
            self.recorder.reconciled(conn, auth, hold, None)
        return result

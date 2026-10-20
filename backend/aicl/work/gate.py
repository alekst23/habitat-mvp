"""WorkAuthorization (the single dispatch gate), budget audit recorder and HoldReconciler.

connection-network-policy/technical.md, owner E11-2.

Fixed fail-closed order (first failure denies; any exception or unavailable dependency => `check_unavailable`):
 1 identity, 2 instance in tenant (not_found), 3 lifecycle active (instance_not_active), 4 capability enabled
 (capability_disabled; set_gated), 5 estimate present and bounded (estimate_missing), 6 confirmation for
 gmail.send/reddit.post (confirmation_required/expired/used/mismatch; PendingAction), 7 attachment on an active
 connection (connection_unavailable; set_gated), 8 network via authorize_destination (network_denied;
 set_gated only for host_not_allowed), 9 ONE db.transaction() with one `conn`: BudgetPort.reserve(conn, ...),
 consume_confirmation(conn, ...) and the WorkRequestRecord insert, 10 WorkExecutorPort.execute.
After a denial's rollback, `gated_reason`/`gate_context` and the `work.denied` event are written each in their own
transaction.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from sqlite3 import Connection
from typing import Protocol
from urllib.parse import urlparse

from aicl.clock import Clock
from aicl.connections.models import CAPABILITY_SCOPES
from aicl.control.audit import AuditEvent, SqliteAuditLog
from aicl.control.auth import AuthContext
from aicl.control.budget import Estimate, Hold, MeasuredUsage, NoUsage, SqliteBudgetPort, Usage, _hold, _usage
from aicl.control.confirmation import CONFIRMED_CAPABILITIES, SqliteConfirmationStore, payload_digest
from aicl.control.errors import AiclError
from aicl.control.instances import CATALOG_CAPABILITIES, GateContext, SqliteInstanceRepository, _fetch
from aicl.creation.service import NOT_IMPLEMENTED
from aicl.db import Database, from_iso, to_iso
from aicl.network.policy import FIXED_NETWORK_POLICY, authorize_destination
from aicl.work.models import (
    AuthorizedWork, ExecutorOutcome, StillUnknown, WorkRequest, WorkResult, WORK_PAYLOAD_MAX_BYTES,
)

log = logging.getLogger("aicl.work")

# Fixed order, as data, so tests can assert the documented sequence.
GATE_CHECK_ORDER: tuple[str, ...] = (
    "identity", "instance", "lifecycle", "capability", "estimate", "confirmation", "connection", "network",
    "reserve_and_consume", "dispatch",
)
FIXED_REQUESTS = {
    "gmail.read": ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"),
    "gmail.send": ("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"),
    "reddit.read": ("GET", "https://oauth.reddit.com/"),
    "reddit.post": ("POST", "https://oauth.reddit.com/api/submit"),
}
BUDGET_GATE_REASONS = {"budget_exhausted": "budget_exhausted", "budget_unavailable": "budget_unavailable",
                       "price_unavailable": "budget_unavailable"}


class WorkAuthorization(Protocol):
    def authorize_and_dispatch(self, auth: AuthContext, request: WorkRequest) -> WorkResult: ...


class BudgetAuditRecorder(Protocol):
    """O-1: E11-1's `SqliteBudgetPort` appends ONLY `budget.late_settlement`. E11-2 appends the reserve, settle,
    unknown, reconcile and overrun events through `AuditLog.append(conn, ...)` INSIDE THE SAME UNIT OF WORK as
    the corresponding BudgetPort call (same `conn`), so a rolled-back reservation or settlement leaves no row.
    Details stay within {hold_id, micro_usd, price_table_version}."""

    def reserved(self, conn: Connection, auth: AuthContext, hold: Hold) -> None: ...

    def settled(self, conn: Connection, auth: AuthContext, hold: Hold, usage: Usage) -> None: ...

    def overrun(self, conn: Connection, auth: AuthContext, hold: Hold, usage: Usage) -> None: ...

    def unknown(self, conn: Connection, auth: AuthContext, hold: Hold) -> None: ...

    def reconciled(self, conn: Connection, auth: AuthContext, hold: Hold, usage: Usage | None) -> None: ...


def _hold_total(hold: Hold) -> int:
    return hold.inference_micro_usd + hold.compute_micro_usd


def _usage_total(usage: Usage) -> int:
    return usage.inference_micro_usd + usage.compute_micro_usd


class SqliteBudgetAuditRecorder:
    def __init__(self, audit: SqliteAuditLog) -> None:
        self.audit = audit

    def _append(self, conn: Connection, auth: AuthContext, hold: Hold, event_type: str, micro_usd: int) -> None:
        self.audit.append(conn, AuditEvent(
            event_type, "gate", "committed", auth.tenant_id, auth.owner_id, hold.instance_id,
            details={"hold_id": hold.id, "micro_usd": micro_usd, "price_table_version": hold.price_table_version}))

    def reserved(self, conn, auth, hold):
        self._append(conn, auth, hold, "budget.reserved", _hold_total(hold))

    def settled(self, conn, auth, hold, usage):
        self._append(conn, auth, hold, "budget.settled", _usage_total(usage))

    def overrun(self, conn, auth, hold, usage):
        self._append(conn, auth, hold, "budget.overrun", _usage_total(usage))

    def unknown(self, conn, auth, hold):
        self._append(conn, auth, hold, "budget.unknown", _hold_total(hold))

    def reconciled(self, conn, auth, hold, usage):
        self._append(conn, auth, hold, "budget.reconciled", 0 if usage is None else _usage_total(usage))


class UnimplementedBudgetAuditRecorder:
    """Contract stub retained for importers of the design phase."""

    def _stub(self, *_args: object, **_kwargs: object) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

    reserved = settled = overrun = unknown = reconciled = _stub


class UnimplementedWorkAuthorization:
    def authorize_and_dispatch(self, auth: AuthContext, request: WorkRequest) -> WorkResult:
        raise NotImplementedError(NOT_IMPLEMENTED)


class Denied(Exception):
    """Internal control flow of the gate: a denial with its reason and optional persisted gate."""

    def __init__(self, reason: str, *, gate: tuple[str, GateContext] | None = None, rule: str | None = None,
                 pending_action_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason, self.gate, self.rule, self.pending_action_id = reason, gate, rule, pending_action_id


def request_digest(request: WorkRequest) -> str:
    estimate = None if request.estimate is None else {
        "inference_input_tokens": request.estimate.inference_input_tokens,
        "inference_output_tokens": request.estimate.inference_output_tokens,
        "compute_minutes": request.estimate.compute_minutes}
    canonical = json.dumps({"instance_id": request.instance_id, "capability": request.capability,
                            "payload": request.payload, "estimate": estimate,
                            "destination_url": request.destination_url},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _estimate_ok(estimate: object) -> bool:
    if not isinstance(estimate, Estimate):
        return False
    values = (estimate.inference_input_tokens, estimate.inference_output_tokens, estimate.compute_minutes)
    return all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10**12 for v in values)


def _preview(capability: str, payload: dict) -> dict:
    body = payload.get("body")
    length = len(body) if isinstance(body, str) else 0
    if capability == "gmail.send":
        recipient = payload.get("to")
        domain = recipient.rsplit("@", 1)[-1][:100] if isinstance(recipient, str) and "@" in recipient else None
        return {"recipient_domain": domain, "body_length": length}
    subreddit = payload.get("subreddit")
    return {"subreddit": subreddit[:50] if isinstance(subreddit, str) else None, "body_length": length}


class SqliteWorkGate:
    def __init__(self, db: Database, clock: Clock, budget: SqliteBudgetPort, confirmations: SqliteConfirmationStore,
                 executor, resolver, hold_stale_seconds: int = 900, executor_timeout_seconds: int = 30) -> None:
        self.db, self.clock, self.budget, self.confirmations = db, clock, budget, confirmations
        self.executor, self.resolver = executor, resolver
        self.hold_stale_seconds, self.executor_timeout_seconds = hold_stale_seconds, executor_timeout_seconds
        self.audit = SqliteAuditLog(clock)
        self.recorder = SqliteBudgetAuditRecorder(self.audit)
        self.instances = SqliteInstanceRepository()

    # -- public ------------------------------------------------------------------------------
    def authorize_and_dispatch(self, auth: AuthContext, request: WorkRequest) -> WorkResult:
        if auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "sign in required")
        instance = self.instances.get(auth, request.instance_id)  # 2: not_found across tenants
        digest = request_digest(request)
        replay = self._replay(auth, request, digest)
        if replay is not None:
            return replay
        try:
            return self._run(auth, request, instance, digest)
        except Denied as denied:
            return self._deny(auth, request, denied)
        except AiclError as error:
            if error.error == "denied":
                return self._deny(auth, request, Denied(str(error.extra.get("reason", "check_unavailable"))))
            raise
        except Exception:
            log.exception("work gate check failed")
            return self._deny(auth, request, Denied("check_unavailable"))

    # -- replay --------------------------------------------------------------------------------
    def _replay(self, auth: AuthContext, request: WorkRequest, digest: str) -> WorkResult | None:
        with self.db.reader() as conn:
            row = conn.execute("SELECT * FROM work_request_record WHERE tenant_id = ? AND work_id = ?",
                               (auth.tenant_id, request.work_id)).fetchone()
            if row is None:
                return None
            if row["request_digest"] != digest:
                raise AiclError("conflict", "work_id was used with a different request",
                                existing_result_id=row["hold_id"])
            return self._result_from_record(conn, row)

    def _result_from_record(self, conn: Connection, row) -> WorkResult:
        hold = _hold(conn.execute("SELECT * FROM budget_hold WHERE id = ?", (row["hold_id"],)).fetchone())
        usage_row = conn.execute("SELECT * FROM budget_usage WHERE hold_id = ?", (hold.id,)).fetchone()
        outcome = {"succeeded": "succeeded", "failed": "failed", "unknown": "unknown",
                   "released": "failed", "pending": "unknown"}[row["outcome"]]
        return WorkResult(row["work_id"], outcome, None, None, None if usage_row is None else _usage(usage_row),
                          hold.state)

    # -- the ordered checks --------------------------------------------------------------------
    def _run(self, auth, request, instance, digest) -> WorkResult:
        if instance.lifecycle != "active":
            raise Denied("instance_not_active")
        capability = request.capability
        if capability not in CATALOG_CAPABILITIES:
            raise AiclError("validation_failed", "unknown capability",
                            field_errors=[{"field": "capability", "code": "unknown_capability"}])
        grants = {g.capability: g.enabled for g in self.instances.get_grants(auth, instance.id)}
        if not grants.get(capability, False):
            raise Denied("capability_disabled", gate=("capability_disabled", GateContext((capability,), None)))
        if not _estimate_ok(request.estimate):
            raise Denied("estimate_missing")
        if len(json.dumps(request.payload, ensure_ascii=False).encode()) > WORK_PAYLOAD_MAX_BYTES:
            raise AiclError("validation_failed", "payload too large",
                            field_errors=[{"field": "payload", "code": "too_large"}])
        confirmation_id = None
        computed = payload_digest(instance.id, capability, request.payload)
        if capability in CONFIRMED_CAPABILITIES:
            confirmation_id = self._check_confirmation(auth, instance, request, computed)
        attachment_id = None
        if capability in CAPABILITY_SCOPES:
            attachment_id = self._check_connection(instance, capability)
        destination = self._check_network(instance, request)
        hold, result = self._reserve_and_consume(auth, request, digest, computed, confirmation_id,
                                                instance, attachment_id)
        return self._dispatch(auth, request, hold, attachment_id, destination)

    def _check_confirmation(self, auth, instance, request, computed) -> str:
        now = self.clock.now()
        with self.db.reader() as conn:
            rows = conn.execute(
                "SELECT * FROM action_confirmation WHERE instance_id = ? AND capability = ? AND tenant_id = ? "
                "ORDER BY created_at DESC, rowid DESC", (instance.id, request.capability, auth.tenant_id)).fetchall()
        for row in rows:  # a usable confirmation for exactly this payload
            if row["payload_digest"] == computed and row["used_at"] is None and from_iso(row["expires_at"]) > now:
                return row["id"]
        latest = rows[0] if rows else None  # otherwise the most recent confirmation decides the denial
        if latest is not None:
            live = latest["used_at"] is None and from_iso(latest["expires_at"]) > now
            if latest["payload_digest"] == computed:
                raise Denied("confirmation_used" if latest["used_at"] is not None else "confirmation_expired")
            if live:
                raise Denied("confirmation_mismatch")  # a live confirmation exists for a different payload
        raise Denied("confirmation_required", pending_action_id=self._pending_action(auth, instance, request, computed))

    def _pending_action(self, auth, instance, request, computed) -> str:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT p.id FROM pending_action p LEFT JOIN action_confirmation c ON c.pending_action_id = p.id "
                "WHERE p.instance_id = ? AND p.capability = ? AND p.payload_digest = ? AND p.tenant_id = ? "
                "AND c.id IS NULL ORDER BY p.created_at DESC LIMIT 1",
                (instance.id, request.capability, computed, auth.tenant_id)).fetchone()
            if row is not None:
                return row["id"]
            pending_id = str(uuid.uuid4())
            conn.execute("INSERT INTO pending_action (id, instance_id, tenant_id, capability, payload_digest, "
                         "preview, created_at) VALUES (?,?,?,?,?,?,?)",
                         (pending_id, instance.id, auth.tenant_id, request.capability, computed,
                          json.dumps(_preview(request.capability, request.payload)), to_iso(self.clock.now())))
            self.audit.append(conn, AuditEvent(
                "confirmation.requested", "gate", "committed", auth.tenant_id, auth.owner_id, instance.id,
                details={"capability": request.capability, "payload_digest_prefix": computed[:12]}))
            return pending_id

    def _check_connection(self, instance, capability: str) -> str:
        with self.db.reader() as conn:
            row = conn.execute(
                "SELECT a.id, c.status FROM connection_attachment a JOIN connection c ON c.id = a.connection_id "
                "WHERE a.instance_id = ? AND a.capability = ? AND a.detached_at IS NULL",
                (instance.id, capability)).fetchone()
        if row is None or row["status"] != "active":
            reason = ("connection_reauthorization_required"
                      if row is not None and row["status"] == "reauthorization_required" else "connection_revoked")
            raise Denied("connection_unavailable", gate=(reason, GateContext((capability,), None)))
        return row["id"]

    def _check_network(self, instance, request) -> str | None:
        capability = request.capability
        if capability in FIXED_REQUESTS:
            method, url = FIXED_REQUESTS[capability]
            domains: tuple[str, ...] = ()
        elif capability == "network.fetch":
            method, url, domains = "GET", request.destination_url or "", instance.network_domains
            if not url:
                raise Denied("network_denied", rule="destination_missing")
        else:
            return None
        decision = authorize_destination(FIXED_NETWORK_POLICY, domains, capability, method, url, 0, self.resolver)
        if decision.allowed:
            return url
        gate = None
        if capability == "network.fetch" and decision.reason == "host_not_allowed":
            host = urlparse(url).hostname or ""
            gate = ("network_denied", GateContext((capability,), hashlib.sha256(host.encode()).hexdigest()[:12]))
        raise Denied("network_denied", gate=gate, rule=decision.rule or decision.reason)

    def _reserve_and_consume(self, auth, request, digest, computed, confirmation_id, checked, attachment_id):
        try:
            with self.db.transaction() as conn:
                # This write transaction is the dispatch authorization boundary. Owner changes
                # committed before it must win; network resolution stays outside the DB lock.
                current = _fetch(conn, auth, request.instance_id)
                if auth.expires_at <= self.clock.now():
                    raise Denied("check_unavailable")
                if current.lifecycle != "active":
                    raise Denied("instance_not_active")
                grant = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id = ? AND capability = ?",
                                     (current.id, request.capability)).fetchone()
                if grant is None or not grant["enabled"]:
                    raise Denied("capability_disabled",
                                 gate=("capability_disabled", GateContext((request.capability,), None)))
                if current.gated_reason is not None:
                    reason = ("connection_unavailable" if current.gated_reason.startswith("connection_")
                              else current.gated_reason)
                    raise Denied(reason)
                if current.version != checked.version:
                    raise Denied("check_unavailable")  # retry with the owner's current policy
                if attachment_id is not None and self._check_connection(current, request.capability) != attachment_id:
                    raise Denied("check_unavailable")
                hold = self.budget.reserve(conn, request.instance_id, request.work_id, request.estimate)
                self.recorder.reserved(conn, auth, hold)
                if confirmation_id is not None and not self.confirmations.consume_confirmation(
                        conn, confirmation_id, computed, self.clock.now()):
                    raise Denied("confirmation_used")
                now = to_iso(self.clock.now())
                conn.execute("INSERT INTO work_request_record (tenant_id, work_id, request_digest, outcome, hold_id, "
                             "created_at, updated_at) VALUES (?,?,?,'pending',?,?,?)",
                             (auth.tenant_id, request.work_id, digest, hold.id, now, now))
                if confirmation_id is not None:
                    self.audit.append(conn, AuditEvent(
                        "confirmation.used", "gate", "committed", auth.tenant_id, auth.owner_id, request.instance_id,
                        details={"confirmation_id": confirmation_id, "capability": request.capability}))
                self.audit.append(conn, AuditEvent(
                    "work.dispatched", "gate", "committed", auth.tenant_id, auth.owner_id, request.instance_id,
                    details={"capability": request.capability, "hold_id": hold.id}))
                return hold, None
        except AiclError as error:
            if error.error == "denied":
                reason = str(error.extra.get("reason", "check_unavailable"))
                gate = ((BUDGET_GATE_REASONS[reason], GateContext()) if reason in BUDGET_GATE_REASONS else None)
                raise Denied(reason, gate=gate) from None
            raise

    # -- dispatch and outcome handling ---------------------------------------------------------
    def _dispatch(self, auth, request, hold: Hold, attachment_id, destination) -> WorkResult:
        payload = dict(request.payload)
        if "sim" not in payload and request.estimate is not None:  # simulated work without a script uses its bound
            payload["sim"] = {"input_tokens": request.estimate.inference_input_tokens,
                              "output_tokens": request.estimate.inference_output_tokens,
                              "compute_minutes": request.estimate.compute_minutes}
        work = AuthorizedWork(request.work_id, request.instance_id, request.capability, payload,
                              hold.id, attachment_id, destination)
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            outcome = pool.submit(self.executor.execute, work).result(timeout=self.executor_timeout_seconds)
        except (FutureTimeout, Exception):
            outcome = ExecutorOutcome("unknown")
        finally:
            pool.shutdown(wait=False)
        return self._settle_outcome(auth, request, hold, outcome)

    def _record(self, conn: Connection, auth, work_id: str, outcome: str) -> None:
        conn.execute("UPDATE work_request_record SET outcome = ?, updated_at = ? WHERE tenant_id = ? AND work_id = ?",
                     (outcome, to_iso(self.clock.now()), auth.tenant_id, work_id))

    def _settle_outcome(self, auth, request, hold: Hold, outcome: ExecutorOutcome) -> WorkResult:
        if outcome.status in ("succeeded", "failed"):
            measured = outcome.measured_usage or MeasuredUsage(0, 0, 0)
            with self.db.transaction() as conn:  # a released hold makes settle raise conflict + late_settlement
                usage = self.budget.settle(conn, hold.id, measured)
                self.recorder.settled(conn, auth, hold, usage)
                if usage.inference_micro_usd > hold.inference_micro_usd or usage.compute_micro_usd > hold.compute_micro_usd:
                    self.recorder.overrun(conn, auth, hold, usage)
                self._record(conn, auth, request.work_id, outcome.status)
            return WorkResult(request.work_id, outcome.status, None, None, usage, "settled")
        if outcome.status == "not_started":
            with self.db.transaction() as conn:
                released = self.budget.release(conn, hold.id)
                self.recorder.reconciled(conn, auth, hold, None)
                self._record(conn, auth, request.work_id, "released")
            return WorkResult(request.work_id, "failed", None, None, None, released.state)
        with self.db.transaction() as conn:
            marked = self.budget.mark_unknown(conn, hold.id)
            self.recorder.unknown(conn, auth, hold)
            self._record(conn, auth, request.work_id, "unknown")
        return WorkResult(request.work_id, "unknown", None, None, None, marked.state)

    # -- denial --------------------------------------------------------------------------------
    def _deny(self, auth, request, denied: Denied) -> WorkResult:
        with self.db.transaction() as conn:
            if denied.gate is not None:
                reason, context = denied.gate
                current = self.instances.get(auth, request.instance_id)
                if current.lifecycle == "active" and (current.gated_reason, current.gate_context) != (reason, context):
                    self.instances.set_gated(conn, auth, request.instance_id, reason, context)
                    conn.execute("UPDATE agent_instance SET gated_at = ? WHERE id = ?",
                                 (to_iso(self.clock.now()), request.instance_id))
                    self.audit.append(conn, AuditEvent(
                        "instance.gated", "gate", "committed", auth.tenant_id, auth.owner_id, request.instance_id,
                        details={"denial_reason": reason}))
            self.audit.append(conn, AuditEvent(
                "work.denied", "gate", "denied", auth.tenant_id, auth.owner_id, request.instance_id,
                reason=denied.rule or denied.reason,
                details={"denial_reason": denied.reason, "capability": request.capability}))
        return WorkResult(request.work_id, "denied", denied.reason, denied.pending_action_id, None, None)


class HoldReconciler(Protocol):
    def run_once(self) -> None: ...


class SqliteHoldReconciler:
    """STARTUP_HOOKS entry, registered after the RevocationSweeper. Calls only BudgetPort and
    WorkExecutorPort.lookup. An exception is audited and the holds keep blocking."""

    def __init__(self, db: Database, clock: Clock, budget: SqliteBudgetPort, executor) -> None:
        self.db, self.clock, self.budget, self.executor = db, clock, budget, executor
        self.audit = SqliteAuditLog(clock)
        self.recorder = SqliteBudgetAuditRecorder(self.audit)

    def _candidates(self) -> list[dict]:
        from datetime import timedelta
        cutoff = to_iso(self.clock.now() - timedelta(seconds=self.budget.hold_stale_seconds))
        with self.db.reader() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT h.*, i.tenant_id AS tenant_id, i.owner_id AS owner_id FROM budget_hold h JOIN "
                "agent_instance i ON i.id = h.instance_id WHERE h.state = 'unknown' OR "
                "(h.state = 'held' AND h.created_at < ?) ORDER BY h.created_at", (cutoff,))]

    def run_once(self) -> None:
        try:
            candidates = self._candidates()
        except Exception:
            log.exception("hold reconciler could not list holds")
            return
        for row in candidates:
            try:
                self._handle(row)
            except Exception:
                log.exception("hold reconciliation failed")
                self._audit_failure(row)

    def _audit_failure(self, row: dict) -> None:
        try:
            with self.db.transaction() as conn:
                self.audit.append(conn, AuditEvent(
                    "budget.reconciled", "system", "denied", row["tenant_id"], row["owner_id"], row["instance_id"],
                    reason="reconcile_failed", details={"hold_id": row["id"], "reason_code": "unknown"}))
        except Exception:
            log.exception("hold reconciler could not audit a failure")

    def _handle(self, row: dict) -> None:
        auth = AuthContext(row["owner_id"], row["tenant_id"], "system", self.clock.now())
        found = self.executor.lookup(row["id"])
        if isinstance(found, StillUnknown) or found.status == "unknown":
            if row["state"] == "held":
                self._mark_unknown(auth, row)
            return
        with self.db.transaction() as conn:
            hold = _hold(conn.execute("SELECT * FROM budget_hold WHERE id = ?", (row["id"],)).fetchone())
            if found.status == "not_started":
                if hold.state == "held":
                    self.budget.release(conn, hold.id)
                else:
                    self.budget.reconcile(conn, hold.id, NoUsage())
                self.recorder.reconciled(conn, auth, hold, None)
                outcome = "released"
            else:
                if hold.state == "held":
                    self.budget.mark_unknown(conn, hold.id)
                    self.recorder.unknown(conn, auth, hold)
                usage = self.budget.reconcile(conn, hold.id, found.measured_usage or MeasuredUsage(0, 0, 0))
                self.recorder.reconciled(conn, auth, hold, usage)
                if (usage.inference_micro_usd > hold.inference_micro_usd
                        or usage.compute_micro_usd > hold.compute_micro_usd):
                    self.recorder.overrun(conn, auth, hold, usage)
                outcome = found.status
            conn.execute("UPDATE work_request_record SET outcome = ?, updated_at = ? WHERE tenant_id = ? AND "
                         "work_id = ?", (outcome, to_iso(self.clock.now()), row["tenant_id"], row["work_id"]))

    def _mark_unknown(self, auth: AuthContext, row: dict) -> None:
        with self.db.transaction() as conn:
            hold = _hold(conn.execute("SELECT * FROM budget_hold WHERE id = ?", (row["id"],)).fetchone())
            self.budget.mark_unknown(conn, hold.id)
            self.recorder.unknown(conn, auth, hold)
            conn.execute("UPDATE work_request_record SET outcome = 'unknown', updated_at = ? WHERE tenant_id = ? "
                         "AND work_id = ?", (to_iso(self.clock.now()), row["tenant_id"], row["work_id"]))


class UnimplementedHoldReconciler:
    def run_once(self) -> None:
        raise NotImplementedError(NOT_IMPLEMENTED)

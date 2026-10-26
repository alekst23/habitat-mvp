"""Durable Render dispatch with authority and accounting retained by AICL.

General writing/research and reviewed example workflows are supported. Scheduler identity can queue
eligible occurrences; worker identity can execute only its bound task. Neither
identity has a purchase approval or payment capability. Network I/O never holds
a SQLite transaction. Unknown provider outcomes are never automatically resent.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import timedelta
import json
import math
import re
import uuid
from urllib.parse import urlsplit, urlunsplit

from aicl.control.auth import AuthContext
from aicl.control.audit import AuditEvent
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso
from aicl.workflow.ad_scenario import SCENARIO
from aicl.workflow.openai_inference import InferenceResult, InferenceNoChargeError

PRICE_VERSION = "render-flex-bound-2026-10-22"
MAX_COMPUTE_MINUTES = 6  # task timeout 180 s, at most one retry
MAX_COMPUTE_COST = 40002
_TERMINAL = {"completed", "blocked", "attention"}
_RUN_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


class RenderExecution:
    def __init__(self, workflow, *, browser=None):
        self.workflow = workflow
        self.db, self.clock, self.commerce = workflow.db, workflow.clock, workflow.commerce
        self.browser = browser

    def _auth(self, conn, instance_id):
        row = conn.execute("SELECT * FROM agent_instance WHERE id=?", (instance_id,)).fetchone()
        if not row:
            raise AiclError("not_found", "Agent not found.")
        # Machine authority is restricted to this saved instance by the endpoint,
        # never by a tenant or owner supplied by the caller.
        return AuthContext(row["owner_id"], row["tenant_id"], "render-system", self.clock.now() + timedelta(hours=1))

    def _event(self, conn, row, action, *, denied=False, reason=None):
        auth = self._auth(conn, row["instance_id"])
        self.commerce.audit.append(conn, AuditEvent(
            "work.denied" if denied else "work.dispatched", "system", "denied" if denied else "committed",
            auth.tenant_id, auth.owner_id, row["instance_id"], reason=reason,
            details={"action": action, "provider": "render", "mode": "render", "run_id": row["id"],
                     "hold_id": row["hold_id"]}))

    def _row(self, conn, dispatch_id, task_run_id=None):
        row = conn.execute("SELECT * FROM render_dispatch WHERE id=?", (dispatch_id,)).fetchone()
        if row is None:
            raise AiclError("not_found", "Render job not found.")
        if task_run_id is not None and row["task_run_id"] != task_run_id:
            raise AiclError("denied", "This Render task is not bound to the job.")
        return row

    def _validate_run_id(self, task_run_id):
        if not isinstance(task_run_id, str) or not _RUN_ID.fullmatch(task_run_id):
            raise AiclError("validation_failed", "A valid Render task run identity is required.")

    def _enqueue(self, conn, auth, config, scheduled_for, *, job=None, retry_blocked=False, owner_request_id=None):
        kind = "continuation" if job else "schedule"
        key = "continue:" + job["id"] if job else scheduled_for
        if owner_request_id:
            key += ":request:" + owner_request_id
        prior = (conn.execute("SELECT * FROM render_dispatch WHERE instance_id=? AND scheduled_for=? AND kind=?", (config["instance_id"], key, kind)).fetchone()
                 if owner_request_id else conn.execute("SELECT * FROM render_dispatch WHERE continuation_run_id=? ORDER BY rowid DESC LIMIT 1", (job["id"],)).fetchone()
                 if job else conn.execute("SELECT * FROM render_dispatch WHERE instance_id=? AND scheduled_for=? AND kind=?",
                                          (config["instance_id"], key, kind)).fetchone())
        if prior:
            if job and retry_blocked and prior["state"] == "blocked":
                key += ":" + str(uuid.uuid4())
            else:
                return prior
        if config.get("scenario") not in ("general", SCENARIO, "browser_purchase") or self.workflow.inference is None:
            raise AiclError("denied", "Render requires a supported workflow and configured inference.", reason="unsupported_workflow")
        self.workflow._require_demo_active(conn, auth)
        if not config["enabled"]:
            raise AiclError("denied", "The schedule is paused.", reason="schedule_paused")
        self.commerce._controls(conn, auth, config["instance_id"])
        # The caller holds BEGIN IMMEDIATE. Count, sum and reservation must be
        # atomic across every owner; new accounts and sandbox funding cannot
        # increase the server's lifetime allowances. Replays above cost nothing.
        if conn.execute("SELECT COUNT(*) FROM render_dispatch").fetchone()[0] >= self.workflow.render_max_dispatches:
            raise AiclError("denied", "The server's Render dispatch limit is reached.", reason="render_dispatch_limit")
        realized = conn.execute("SELECT COALESCE(SUM(cost_micro_usd),0) FROM render_compute_usage").fetchone()[0]
        reserved = conn.execute("SELECT COALESCE(SUM(h.compute_micro_usd),0) FROM render_dispatch d "
                                "JOIN budget_hold h ON h.id=d.hold_id WHERE h.state IN ('held','unknown')").fetchone()[0]
        if realized + reserved + MAX_COMPUTE_COST > self.workflow.render_max_spend_micro_usd:
            raise AiclError("denied", "The server's Render compute spend ceiling is reached. Demo funding cannot increase it.", reason="render_spend_ceiling")
        if self.commerce._balance(conn, config["instance_id"]) < MAX_COMPUTE_COST:
            raise AiclError("denied", "Service credit must cover the bounded Render runtime.", reason="credit_insufficient")
        dispatch_id = str(uuid.uuid4())
        hold = self.commerce.budget.reserve(conn, config["instance_id"], "render:" + dispatch_id,
            Estimate(0, 0, MAX_COMPUTE_MINUTES), price_table_version=PRICE_VERSION)
        now = to_iso(self.clock.now())
        conn.execute("INSERT INTO render_dispatch(id,instance_id,scheduled_for,kind,continuation_run_id,config_json,state,hold_id,created_at) "
                     "VALUES (?,?,?,?,?,?,'queued',?,?)", (dispatch_id, config["instance_id"], key, kind,
                     job["id"] if job else None, json.dumps(config), hold.id, now))
        row = self._row(conn, dispatch_id)
        self._event(conn, row, "render_queued")
        return row

    def enqueue_continuation(self, conn, auth, job, *, retry_blocked=False):
        # Called only after the owner's explicit continuation choice and verified
        # payment. Queuing cannot turn an unpaid proposal into an authorization.
        purchase = self.workflow._current_purchase(conn, job)
        if not purchase or purchase["state"] != "paid" or not purchase["fulfillment_json"]:
            raise AiclError("denied", "Complete payment before continuing.")
        config = self.workflow._config(conn, auth, job["instance_id"])
        self._enqueue(conn, auth, config, to_iso(self.clock.now()), job=job, retry_blocked=retry_blocked)

    def enqueue_owner_continuation(self, conn, auth, job):
        from aicl.owner_requests.service import OwnerRequestService
        if OwnerRequestService(self.workflow).pending_for_job(conn, job["id"]):
            raise AiclError("denied", "This job still needs an owner response.")
        request = conn.execute("SELECT id FROM owner_request WHERE workflow_run_id=? AND status='resolved' ORDER BY rowid DESC LIMIT 1", (job["id"],)).fetchone()
        if not request or conn.execute("SELECT 1 FROM owner_request WHERE workflow_run_id=? AND status='declined'", (job["id"],)).fetchone():
            raise AiclError("denied", "A verified owner response is required.")
        config = self.workflow._config(conn, auth, job["instance_id"])
        return self._enqueue(conn, auth, config, to_iso(self.clock.now()), job=job,
                             retry_blocked=True, owner_request_id=request["id"])

    def request_owner(self, dispatch_id, task_run_id, job_id, kind, title, reason, details, dedupe_key):
        """A worker may ask its owner, never supply their response or identity."""
        from aicl.owner_requests.service import OwnerRequestService
        with self.db.transaction() as conn:
            row = self._row(conn, dispatch_id, task_run_id)
            if row["state"] != "running":
                raise AiclError("denied", "The Render job is not running.")
            job = conn.execute("SELECT * FROM mock_workflow_run WHERE id=? AND instance_id=?", (job_id, row["instance_id"])).fetchone()
            mapped = conn.execute("SELECT 1 FROM render_dispatch_attempt m JOIN workflow_inference_attempt a ON a.id=m.attempt_id WHERE m.dispatch_id=? AND a.workflow_run_id=?", (dispatch_id, job_id)).fetchone()
            bound = job is not None and (job["id"] == row["continuation_run_id"] if row["kind"] == "continuation"
                                         else job["occurrence_id"] == row["occurrence_id"] or mapped)
            if not bound:
                raise AiclError("not_found", "Job is not part of this Render task.")
            if conn.execute("SELECT 1 FROM workflow_inference_attempt WHERE workflow_run_id=? AND state IN ('inflight','unknown')", (job_id,)).fetchone():
                raise AiclError("conflict", "Resolve the current provider attempt before requesting owner input.")
            if kind not in ("clarification", "authentication", "permission"):
                raise AiclError("validation_failed", "Choose a supported owner request.")
            auth = self._auth(conn, row["instance_id"])
            result = OwnerRequestService(self.workflow).create(auth, row["instance_id"], job_id,
                kind, title, reason, details=details, dedupe_key=dedupe_key)
            return {"request": result, "state": "waiting_owner"}

    def _browser_job_authority(self, conn, dispatch_id, task_run_id, job_id):
        """Recheck saved job authority immediately around a browser read."""
        from aicl.owner_requests.service import OwnerRequestService
        row = self._row(conn, dispatch_id, task_run_id)
        if row["state"] != "running":
            raise AiclError("denied", "The Render job is not running.")
        job = conn.execute("SELECT * FROM mock_workflow_run WHERE id=? AND instance_id=?", (job_id, row["instance_id"])).fetchone()
        mapped = conn.execute("SELECT 1 FROM render_dispatch_attempt m JOIN workflow_inference_attempt a ON a.id=m.attempt_id WHERE m.dispatch_id=? AND a.workflow_run_id=?", (dispatch_id, job_id)).fetchone()
        bound = job is not None and (job["id"] == row["continuation_run_id"] if row["kind"] == "continuation"
                                     else job["occurrence_id"] == row["occurrence_id"] or mapped)
        if not bound:
            raise AiclError("not_found", "Job is not part of this Render task.")
        auth = self._auth(conn, row["instance_id"])
        if (job["state"] in ("waiting_owner", "owner_declined")
                or OwnerRequestService(self.workflow).pending_for_job(conn, job_id)
                or conn.execute("SELECT 1 FROM owner_request WHERE workflow_run_id=? AND status='declined'", (job_id,)).fetchone()):
            raise AiclError("denied", "This job still needs an owner response.")
        self.workflow._require_demo_active(conn, auth)
        if not self.workflow._config(conn, auth, row["instance_id"])["enabled"]:
            raise AiclError("denied", "The schedule is paused.", reason="schedule_paused")
        self.commerce._controls(conn, auth, row["instance_id"])
        hold = conn.execute("SELECT state FROM budget_hold WHERE id=? AND instance_id=?", (row["hold_id"], row["instance_id"])).fetchone()
        if (not hold or hold["state"] != "held" or not row["started_at"]
                or self.clock.now() >= from_iso(row["started_at"]) + timedelta(minutes=MAX_COMPUTE_MINUTES)):
            raise AiclError("denied", "The worker's bounded compute reservation is no longer active.", reason="budget_unavailable")
        return auth, row

    def _browser_authority(self, conn, dispatch_id, task_run_id, job_id, request_id):
        auth, row = self._browser_job_authority(conn, dispatch_id, task_run_id, job_id)
        request = conn.execute("SELECT * FROM owner_request WHERE id=? AND instance_id=? AND tenant_id=? AND owner_id=? AND kind='authentication'",
                               (request_id, row["instance_id"], auth.tenant_id, auth.owner_id)).fetchone()
        if not request:
            raise AiclError("not_found", "Sign-in request is not available to this agent.")
        if request["status"] != "resolved":
            raise AiclError("denied", "This job still needs an owner response.")
        return auth, row

    def browser_prepare(self, dispatch_id, task_run_id, attempt_id):
        from aicl.browser.workflow import BrowserPreparation
        return BrowserPreparation(self).prepare(dispatch_id, task_run_id, attempt_id)

    def browser_page(self, dispatch_id, task_run_id, job_id, request_id, url):
        """A scoped page read, never raw cookies, browser control or payment authority.

        The broker owns session leases, expiration, URL policy and encrypted
        credentials. Browser I/O must not hold the application database lock.
        """
        if self.browser is None:
            raise AiclError("unavailable", "Cloud browser service is not configured.")
        with self.db.transaction() as conn:
            auth, row = self._browser_authority(conn, dispatch_id, task_run_id, job_id, request_id)
            self._event(conn, row, "browser_read_requested")
        page = self.browser.worker_page(auth, request_id, job_id, url,
            authorize=lambda conn: self._browser_authority(conn, dispatch_id, task_run_id, job_id, request_id))
        with self.db.transaction() as conn:
            _, row = self._browser_authority(conn, dispatch_id, task_run_id, job_id, request_id)
            self._event(conn, row, "browser_read_completed")
        # Defense in depth: never forward an expanded runtime result verbatim.
        if not isinstance(page, dict) or any(not isinstance(page.get(key), str) for key in ("url", "title", "text")):
            raise AiclError("unavailable", "Cloud browser returned an invalid page result.")
        try:
            parts = urlsplit(page["url"])
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                raise ValueError()
            safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except ValueError:
            raise AiclError("unavailable", "Cloud browser returned an invalid page location.") from None
        return {"url": safe_url[:2048], "title": page["title"][:500], "text": page["text"][:20000],
                "access_verified": False}

    def dispatch(self, limit=10):
        if type(limit) is not int or not 1 <= limit <= 20:
            raise AiclError("validation_failed", "Dispatch limit must be 1–20.")
        now = to_iso(self.clock.now())
        with self.db.transaction() as conn:
            due = conn.execute("SELECT c.instance_id FROM mock_workflow_config c WHERE c.enabled=1 AND c.next_due<=? AND NOT EXISTS (SELECT 1 FROM render_dispatch d WHERE d.instance_id=c.instance_id AND d.state NOT IN ('completed','blocked','attention')) ORDER BY c.next_due LIMIT ?", (now, limit)).fetchall()
            for item in due:
                iid = item["instance_id"]
                # An unresolved compute hold blocks subsequent work. Finished
                # purchase waiting is not a running task and does not block.
                if conn.execute("SELECT 1 FROM render_dispatch WHERE instance_id=? AND state NOT IN ('completed','blocked','attention')", (iid,)).fetchone():
                    continue
                auth = self._auth(conn, iid)
                config = self.workflow._config(conn, auth, iid)
                try:
                    with self.db.transaction():
                        self._enqueue(conn, auth, config, config["next_due"])
                except AiclError as error:
                    # Record a skipped cadence rather than retrying this denied
                    # agent every minute and starving later eligible agents.
                    conn.execute("UPDATE mock_workflow_config SET last_outcome=?,next_due=?,updated_at=? WHERE instance_id=?", (error.message, self.workflow._next_due(config, self.clock.now()), now, iid))
                    self.commerce.audit.append(conn, AuditEvent("work.denied", "system", "denied", auth.tenant_id, auth.owner_id, iid,
                        reason=error.extra.get("reason", error.error), details={"action": "render_schedule_blocked", "provider": "render"}))
                    continue
                # Coalesce downtime into one occurrence, never bill a catch-up
                # storm. Jobs keep the exact due time and config that was queued.
                conn.execute("UPDATE mock_workflow_config SET next_due=?,last_outcome='Queued on Render',updated_at=? WHERE instance_id=?",
                             (self.workflow._next_due(config, self.clock.now()), now, iid))
            result = []
            for row in conn.execute("SELECT d.* FROM render_dispatch d WHERE d.state IN ('queued','dispatching','submission_unknown') "
                    "AND NOT EXISTS (SELECT 1 FROM render_dispatch other WHERE other.instance_id=d.instance_id AND other.id!=d.id AND other.state IN ('dispatching','submission_unknown','submitted','running','unknown')) "
                    "AND (d.state!='queued' OR NOT EXISTS (SELECT 1 FROM render_dispatch earlier WHERE earlier.instance_id=d.instance_id AND earlier.state='queued' AND earlier.rowid<d.rowid)) "
                    "ORDER BY d.created_at LIMIT ?", (limit,)).fetchall():
                if self.workflow._demo_expired(conn, self._auth(conn, row["instance_id"]).owner_id):
                    # A never-offered job cannot have started externally. An
                    # offered job may have reached Render: retain its full hold.
                    if row["offered_at"]:
                        self.commerce.budget.mark_unknown(conn, row["hold_id"])
                        state = "unknown"
                    else:
                        self.commerce.budget.release(conn, row["hold_id"])
                        state = "blocked"
                    conn.execute("UPDATE render_dispatch SET state=?,reason='Demo workspace expired' WHERE id=?", (state, row["id"]))
                    self._event(conn, row, "render_workspace_expired", denied=True, reason="judge_demo_expired")
                    continue
                # Render launch idempotency lasts 24 h. Never cross that boundary.
                if row["offered_at"] and self.clock.now() - from_iso(row["offered_at"]) >= timedelta(hours=23):
                    conn.execute("UPDATE render_dispatch SET state='unknown',reason='Submission outcome requires reconciliation' WHERE id=?", (row["id"],))
                    self.commerce.budget.mark_unknown(conn, row["hold_id"])
                    self._event(conn, row, "render_submission_unknown", denied=True, reason="reconciliation_pending")
                    continue
                conn.execute("UPDATE render_dispatch SET state='dispatching',offered_at=COALESCE(offered_at,?) WHERE id=?", (now, row["id"]))
                result.append({"id": row["id"], "input": {"dispatch_id": row["id"]}, "idempotency_key": "habitat:" + row["id"]})
            return {"dispatches": result}

    def submitted(self, dispatch_id, task_run_id):
        self._validate_run_id(task_run_id)
        with self.db.transaction() as conn:
            row = self._row(conn, dispatch_id)
            if row["task_run_id"] and row["task_run_id"] != task_run_id:
                raise AiclError("conflict", "A different Render task is already bound.")
            conn.execute("UPDATE render_dispatch SET task_run_id=?,state=CASE WHEN state IN ('queued','dispatching','submission_unknown') THEN 'submitted' ELSE state END WHERE id=?", (task_run_id, dispatch_id))
            return {"state": self._row(conn, dispatch_id)["state"]}

    def uncertain(self, dispatch_id):
        with self.db.transaction() as conn:
            self._row(conn, dispatch_id)
            conn.execute("UPDATE render_dispatch SET state='submission_unknown' WHERE id=? AND state='dispatching'", (dispatch_id,))
            return {"state": self._row(conn, dispatch_id)["state"]}

    def _attach(self, conn, row):
        # Only one active dispatch per agent. Retries from later occurrences can
        # re-use a pre-dispatch-blocked attempt, never an inflight one.
        for attempt in conn.execute("SELECT a.id FROM workflow_inference_attempt a JOIN mock_workflow_run w ON w.id=a.workflow_run_id WHERE w.instance_id=? AND w.state NOT IN ('waiting_owner','owner_declined') AND a.state='pending'", (row["instance_id"],)).fetchall():
            conn.execute("INSERT OR IGNORE INTO render_dispatch_attempt(dispatch_id,attempt_id) VALUES (?,?)", (row["id"], attempt["id"]))

    def _attempts(self, conn, row):
        out = []
        for a in conn.execute("SELECT a.*,m.result_json FROM render_dispatch_attempt m JOIN workflow_inference_attempt a ON a.id=m.attempt_id WHERE m.dispatch_id=? AND m.completed=0 AND (a.state='pending' OR m.result_json IS NOT NULL)", (row["id"],)):
            job = conn.execute("SELECT * FROM mock_workflow_run WHERE id=?", (a["workflow_run_id"],)).fetchone()
            if job["state"] in ("waiting_owner", "owner_declined"):
                continue
            snapshot = json.loads(job["config_json"])
            # A fresh scheduled/continuation worker must discover a saved handoff
            # without retaining the old process or receiving its browser state.
            # This is response metadata, not proof that website access still works.
            browser_requests = []
            for request in conn.execute("SELECT r.id,r.details_json,b.credential_expires_at FROM owner_request r "
                                        "JOIN browser_session b ON b.id=json_extract(r.response_json,'$.browser_session_id') "
                                        "WHERE r.instance_id=? AND r.kind='authentication' AND r.status='resolved' "
                                        "AND json_extract(r.response_json,'$.decision')='session_provided' "
                                        "AND b.instance_id=r.instance_id AND b.tenant_id=r.tenant_id AND b.owner_id=r.owner_id "
                                        "AND b.request_id=r.id AND b.mode='owner' AND b.state='complete' "
                                        "AND b.domain=json_extract(r.details_json,'$.domain') "
                                        "AND b.secret_ref IS NOT NULL AND b.credential_expires_at>? "
                                        "AND NOT EXISTS (SELECT 1 FROM owner_request p WHERE p.instance_id=r.instance_id "
                                        "AND p.kind='authentication' AND p.status='pending' AND json_extract(p.details_json,'$.domain')=b.domain) "
                                        "ORDER BY r.created_at,r.id",
                                        (row["instance_id"], to_iso(self.clock.now()))):
                details = json.loads(request["details_json"])
                browser_requests.append({"request_id": request["id"], "domain": details["domain"],
                                         "requested_access": details.get("requested_access", ""),
                                         "credential_expires_at": request["credential_expires_at"],
                                         "access_verified": False})
            if browser_requests:
                snapshot["browser_requests"] = browser_requests
            out.append({"id": a["id"], "workflow_run_id": job["id"], "snapshot": snapshot, "spec": json.loads(job["spec_json"]), "feedback": a["feedback"]})
        return out

    def _result(self, conn, row):
        jobs = [r[0] for r in conn.execute("SELECT id FROM mock_workflow_run WHERE occurrence_id=? OR id=?", (row["occurrence_id"], row["continuation_run_id"]))]
        outputs = [r[0] for r in conn.execute("SELECT d.id FROM mock_workflow_deliverable d JOIN mock_workflow_run w ON w.id=d.workflow_run_id WHERE w.occurrence_id=? OR w.id=?", (row["occurrence_id"], row["continuation_run_id"]))]
        return {"dispatch_id": row["id"], "state": row["state"], "task_run_id": row["task_run_id"],
                "job_ids": jobs, "deliverable_ids": outputs, "attempts": self._attempts(conn, row) if row["state"] == "running" else []}

    def claim(self, dispatch_id, task_run_id):
        self._validate_run_id(task_run_id)
        with self.db.transaction() as conn:
            row = self._row(conn, dispatch_id)
            if row["task_run_id"] and row["task_run_id"] != task_run_id:
                raise AiclError("denied", "This Render task is not bound to the job.")
            if not row["task_run_id"]:
                conn.execute("UPDATE render_dispatch SET task_run_id=? WHERE id=?", (task_run_id, dispatch_id))
            if row["state"] in _TERMINAL or row["state"] == "running":
                return self._result(conn, self._row(conn, dispatch_id))
            if row["state"] == "queued":
                raise AiclError("denied", "The scheduler has not dispatched this work yet.")
            if row["started_at"]:
                raise AiclError("denied", "The previous execution requires reconciliation.")
            auth = self._auth(conn, row["instance_id"])
            now = to_iso(self.clock.now())
            conn.execute("UPDATE render_dispatch SET state='running',started_at=? WHERE id=?", (now, dispatch_id))
            row = self._row(conn, dispatch_id)
            try:
                with self.db.transaction():
                    self.workflow._require_demo_active(conn, auth)
                    current = self.workflow._config(conn, auth, row["instance_id"])
                    if not current["enabled"]:
                        raise AiclError("denied", "The schedule is paused.", reason="schedule_paused")
                    self.commerce._controls(conn, auth, row["instance_id"])
                    if row["kind"] == "continuation":
                        job = self.workflow._job(conn, auth, row["continuation_run_id"])
                        self.workflow._continue(conn, auth, job)
                        occurrence_id = job["occurrence_id"]
                    else:
                        view = self.workflow.advance(auth, row["instance_id"], row["scheduled_for"],
                            defer_inference=True, config_snapshot=json.loads(row["config_json"]), manage_schedule=False)
                        occurrence_id = view["occurrence"]["id"]
                    conn.execute("UPDATE render_dispatch SET occurrence_id=? WHERE id=?", (occurrence_id, dispatch_id))
                    self._attach(conn, row)
            except AiclError as error:
                self._finish_compute(conn, row, "blocked", error.message)
                self._event(conn, row, "render_execution_blocked", denied=True, reason=error.extra.get("reason", error.error))
            else:
                self._event(conn, row, "render_started")
            return self._result(conn, self._row(conn, dispatch_id))

    def _attempt(self, conn, row, attempt_id):
        mapping = conn.execute("SELECT * FROM render_dispatch_attempt WHERE dispatch_id=? AND attempt_id=?", (row["id"], attempt_id)).fetchone()
        if not mapping:
            raise AiclError("not_found", "Attempt is not part of this Render job.")
        attempt = conn.execute("SELECT * FROM workflow_inference_attempt WHERE id=?", (attempt_id,)).fetchone()
        job = conn.execute("SELECT * FROM mock_workflow_run WHERE id=?", (attempt["workflow_run_id"],)).fetchone()
        return mapping, attempt, job

    def generate(self, dispatch_id, task_run_id, attempt_id):
        with self.db.reader() as conn:
            row = self._row(conn, dispatch_id, task_run_id)
            mapping, attempt, job = self._attempt(conn, row, attempt_id)
            if mapping["result_json"]:
                return {"state": "generated", "result": json.loads(mapping["result_json"]), "spec": json.loads(job["spec_json"])}
            if row["state"] != "running":
                raise AiclError("denied", "The Render job is not running.")
            auth = self._auth(conn, row["instance_id"])
            if json.loads(job["config_json"]).get("scenario") == "browser_purchase":
                from aicl.browser.workflow import BrowserPreparation
                self._browser_job_authority(conn, dispatch_id, task_run_id, job["id"])
                if not BrowserPreparation(self).ready(conn, auth, job, attempt_id):
                    raise AiclError("denied", "Read the authorized website before preparing its purchase proposal.", reason="connection_unavailable")
        claimed = self.workflow.inference._claim(auth, attempt_id)
        if claimed is None:
            with self.db.reader() as conn:
                _, attempt, _ = self._attempt(conn, row, attempt_id)
                return {"state": attempt["state"], "result": None}
        attempt, job = claimed
        try:
            result = self.workflow.inference.generate(auth, attempt, job)
        except InferenceNoChargeError as error:
            self.workflow.inference._failure(auth, attempt, job, no_charge=True, reason=error.reason)
        except Exception:
            self.workflow.inference._failure(auth, attempt, job, no_charge=False, reason="provider_outcome_unknown")
        else:
            # Persist the exact provider result before acknowledging the network
            # request. Replays return this cache and cannot spend a second time.
            with self.db.transaction() as conn:
                conn.execute("UPDATE render_dispatch_attempt SET result_json=? WHERE dispatch_id=? AND attempt_id=? AND result_json IS NULL", (json.dumps(asdict(result)), dispatch_id, attempt_id))
            return {"state": "generated", "result": asdict(result), "spec": json.loads(job["spec_json"])}
        with self.db.reader() as conn:
            _, attempt, _ = self._attempt(conn, row, attempt_id)
            return {"state": attempt["state"], "result": None}

    def complete_attempt(self, dispatch_id, task_run_id, attempt_id, validation):
        if not isinstance(validation, dict) or type(validation.get("passed")) is not bool:
            raise AiclError("validation_failed", "Worker structural validation is required.")
        with self.db.transaction() as conn:
            row = self._row(conn, dispatch_id, task_run_id)
            mapping, attempt, job = self._attempt(conn, row, attempt_id)
            if mapping["completed"]:
                return {"state": attempt["state"]}
            if not mapping["result_json"] or row["state"] != "running":
                raise AiclError("conflict", "No cached provider response is ready for this job.")
            result = InferenceResult(**json.loads(mapping["result_json"]))
            if not validation["passed"]:
                result = replace(result, validation_error=result.validation_error or "worker_structural_check_failed")
            auth = self._auth(conn, row["instance_id"])
            # Server re-validates saved criteria, usage and content. Worker flags
            # can reject an output but cannot fabricate usage or declare success.
            self.workflow.inference._settle(auth, dict(attempt), dict(job), result,
                proposal_authorize=lambda current: self._browser_job_authority(current, dispatch_id, task_run_id, job["id"]))
            conn.execute("UPDATE render_dispatch_attempt SET completed=1 WHERE dispatch_id=? AND attempt_id=?", (dispatch_id, attempt_id))
            return {"state": conn.execute("SELECT state FROM workflow_inference_attempt WHERE id=?", (attempt_id,)).fetchone()[0]}

    def _finish_compute(self, conn, row, state, reason=None):
        elapsed = max(1, math.ceil((self.clock.now() - from_iso(row["started_at"])).total_seconds()))
        if elapsed > MAX_COMPUTE_MINUTES * 60:
            self.commerce.budget.mark_unknown(conn, row["hold_id"])
            conn.execute("UPDATE render_dispatch SET state='unknown',reason='Runtime exceeded bounded window; reconcile Render usage' WHERE id=?", (row["id"],))
            return
        minutes = max(1, math.ceil(elapsed / 60))
        usage = self.commerce.budget.settle(conn, row["hold_id"], MeasuredUsage(0, 0, minutes))
        now = to_iso(self.clock.now())
        conn.execute("INSERT OR IGNORE INTO render_compute_usage(dispatch_id,instance_id,hold_id,elapsed_seconds,charged_minutes,cost_micro_usd,created_at) VALUES (?,?,?,?,?,?,?)",
                     (row["id"], row["instance_id"], row["hold_id"], elapsed, minutes, usage.compute_micro_usd, now))
        conn.execute("UPDATE render_dispatch SET state=?,reason=?,completed_at=? WHERE id=?", (state, reason, now, row["id"]))
        self._event(conn, row, "render_" + state)

    def finish(self, dispatch_id, task_run_id):
        with self.db.transaction() as conn:
            row = self._row(conn, dispatch_id, task_run_id)
            if row["state"] in _TERMINAL:
                return self._result(conn, row)
            if row["state"] != "running":
                raise AiclError("conflict", "Claim this Render job before completing it.")
            if self._attempts(conn, row):
                return self._result(conn, row)
            if conn.execute("SELECT 1 FROM render_dispatch_attempt m JOIN workflow_inference_attempt a ON a.id=m.attempt_id WHERE m.dispatch_id=? AND a.state='inflight' AND m.result_json IS NULL", (dispatch_id,)).fetchone():
                raise AiclError("conflict", "A provider request is still in flight or unresolved. Its reservation remains held.")
            auth = self._auth(conn, row["instance_id"])
            config = self.workflow._config(conn, auth, row["instance_id"])
            if (row["kind"] == "schedule" and json.loads(row["config_json"]).get("scenario") == SCENARIO
                    and config["enabled"] and config["demo_time"] == row["scheduled_for"] and not self.workflow._demo_expired(conn, auth.owner_id)):
                try:
                    with self.db.transaction():
                        self.commerce._controls(conn, auth, row["instance_id"])
                        self.workflow._advance_ads(conn, auth, json.loads(row["config_json"]), row["occurrence_id"], row["scheduled_for"])
                        self._attach(conn, row)
                except AiclError:
                    pass  # Observed model usage still settles after pause.
            if self._attempts(conn, row):
                return self._result(conn, row)
            waiting_owner = conn.execute("SELECT 1 FROM mock_workflow_run WHERE state='waiting_owner' AND (occurrence_id=? OR id=?)", (row["occurrence_id"], row["continuation_run_id"])).fetchone()
            unresolved = conn.execute("SELECT 1 FROM render_dispatch_attempt m JOIN workflow_inference_attempt a ON a.id=m.attempt_id WHERE m.dispatch_id=? AND a.state IN ('inflight','unknown','blocked','released')", (dispatch_id,)).fetchone()
            self._finish_compute(conn, row, "attention" if unresolved or waiting_owner else "completed")
            return self._result(conn, self._row(conn, dispatch_id))

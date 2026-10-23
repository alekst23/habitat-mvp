"""One owner inbox; purchase state is projected, never copied.

Authentication requests describe the blocked work, not a credential collection
surface. A trusted browser broker can return session state for the worker to check. A permission
answer records consent for this request; it never changes capability/network
policy or substitutes for payment authorization.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import uuid

from aicl.commerce.service import _canonical
from aicl.browser.proposals import BrowserPurchaseProposalService
from aicl.control.errors import AiclError
from aicl.db import to_iso

_KINDS = frozenset(("clarification", "authentication", "permission"))
_STATES = frozenset(("pending", "resolved", "declined", "all"))
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


class OwnerRequestService:
    def __init__(self, workflow, *, browser_enabled=False):
        self.workflow = workflow
        self.db, self.clock = workflow.db, workflow.clock
        self.browser_enabled = browser_enabled
        self.browser_cancel = None
        self.browser_proposals = BrowserPurchaseProposalService(workflow)

    def _text(self, value, name, limit, *, optional=False):
        return self.workflow._text(value, name, limit, optional=optional)

    def _details(self, kind, details):
        if not isinstance(details, dict):
            raise AiclError("validation_failed", "Request details must be an object.")
        allowed = {"clarification": {"question", "options"},
                   "authentication": {"domain", "requested_access", "account_label"},
                   "permission": {"action", "scope"}}[kind]
        if details.keys() - allowed:
            raise AiclError("validation_failed", "Request details include unsupported fields.")
        result = {}
        for key, value in details.items():
            if key == "options":
                if not isinstance(value, list) or len(value) > 8:
                    raise AiclError("validation_failed", "Provide at most eight suggested answers.")
                result[key] = [self._text(option, "Suggested answer", 300) for option in value]
            else:
                result[key] = self._text(value, key.replace("_", " ").title(), 2000 if key == "question" else 500)
        if kind == "authentication":
            domain = result.get("domain", "").lower().rstrip(".")
            if len(domain) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain):
                raise AiclError("validation_failed", "Provide the actual website hostname, without a URL or credentials.")
            labels = domain.split(".")
            if len(labels) < 2 or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
                raise AiclError("validation_failed", "Provide a valid public website hostname.")
            try:
                ipaddress.ip_address(domain)
            except ValueError:
                pass
            else:
                raise AiclError("validation_failed", "Sign-in requests need a website hostname.")
            if domain.endswith((".local", ".localhost", ".internal")):
                raise AiclError("validation_failed", "Sign-in requests need a public website hostname.")
            result["domain"] = domain
        if kind == "permission" and not (result.get("action") and result.get("scope")):
            raise AiclError("validation_failed", "Describe the exact proposed action and its scope.")
        return result

    def _owned(self, conn, auth, request_id):
        self.workflow._auth(auth)
        row = conn.execute("SELECT * FROM owner_request WHERE id=? AND tenant_id=? AND owner_id=?",
                           (request_id, auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Request not found.")
        self.workflow._instance(conn, auth, row["instance_id"])
        return row

    @staticmethod
    def pending_for_job(conn, job_id):
        return [dict(row) for row in conn.execute(
            "SELECT * FROM owner_request WHERE workflow_run_id=? AND status='pending' ORDER BY created_at,id", (job_id,))]

    @staticmethod
    def answers_for_job(conn, job_id):
        # Never provide authentication material to inference. Answers are scoped
        # to this immutable job rather than rewriting future agent configuration.
        return [{"request_id": row["id"], "kind": row["kind"], "question": json.loads(row["details_json"]).get("question", row["title"]),
                 "reason": row["reason"], "answer": json.loads(row["response_json"]).get("answer", ""),
                 "decision": json.loads(row["response_json"]).get("decision", ""),
                 "scope": json.loads(row["details_json"]).get("scope")}
                for row in conn.execute("SELECT * FROM owner_request WHERE workflow_run_id=? AND status='resolved' "
                                        "AND kind IN ('clarification','permission') ORDER BY created_at,id", (job_id,))]

    def _project(self, conn, auth, row):
        inst = self.workflow._instance(conn, auth, row["instance_id"])
        job = self.workflow._job(conn, auth, row["workflow_run_id"])
        snapshot, spec = json.loads(job["config_json"]), json.loads(job["spec_json"])
        details = json.loads(row["details_json"])
        browser_state = None
        if row["kind"] == "authentication":
            browser = conn.execute("SELECT id,state,expires_at,credential_expires_at FROM browser_session WHERE request_id=? AND mode='owner' ORDER BY rowid DESC LIMIT 1", (row["id"],)).fetchone()
            if browser:
                browser_state = browser["state"]
                expiry = browser["credential_expires_at"] if browser_state == "complete" else browser["expires_at"]
                if browser_state in ("starting", "active", "saving", "complete") and expiry and expiry <= to_iso(self.clock.now()):
                    browser_state = "expired" if browser_state == "complete" else "closing"
                if conn.execute("SELECT 1 FROM browser_session WHERE parent_session_id=? AND state='closing'", (browser["id"],)).fetchone():
                    browser_state = "closing"
        return {"id": row["id"], "kind": row["kind"], "title": row["title"], "reason": row["reason"],
                "status": row["status"], "stage": row["status"], "version": row["version"],
                "instance_id": row["instance_id"], "agent_name": inst["name"], "job_id": job["id"],
                "job_name": spec["name"], "goal": snapshot["goal"], "job_state": job["state"],
                "created_at": row["created_at"], "updated_at": row["updated_at"], "resolved_at": row["resolved_at"],
                "continuation": row["continuation"], "paused_state": row["paused_state"],
                "details": details, "response": json.loads(row["response_json"]) if row["response_json"] else None,
                "browser_state": browser_state,
                "capability": "available" if row["kind"] != "authentication" or self.browser_enabled else "unavailable",
                "capability_message": ("Sign in through the isolated browser, then return the session so the agent can check access. Sign-in does not approve purchases." if self.browser_enabled else "Secure cloud-browser sign-in is not connected yet. This job remains paused; passwords and login codes must not be entered here.") if row["kind"] == "authentication" else None,
                "purchase": None, "purchase_id": None, "order_id": None}

    def _purchase(self, conn, auth, purchase_id):
        self.workflow.commerce._owned_resource(conn, auth, "mock_commerce_purchase", purchase_id)
        row = conn.execute("SELECT p.*,w.workflow_run_id FROM mock_commerce_purchase p "
                           "LEFT JOIN mock_workflow_purchase w ON w.purchase_id=p.id WHERE p.id=?", (purchase_id,)).fetchone()
        purchase = self.workflow._purchase_review_projection(conn, auth, row)
        order = self.workflow.commerce.order(auth, purchase["order_id"]) if purchase["order_id"] else None
        stage = "expired" if purchase["expired"] else purchase["state"]
        status = "resolved" if stage == "paid" else "declined" if stage in ("declined", "cancelled", "expired") else "pending"
        # Includes checkout reconciliation state and continuation: a stale tab
        # cannot approve or overwrite a decision made in another surface.
        version = hashlib.sha256(_canonical({"purchase": purchase, "order": order}).encode()).hexdigest()
        quote = purchase["quote"]
        title = quote.get("item_name") or quote.get("name") or quote.get("description") or "Purchase approval"
        return {"id": "purchase:" + purchase_id, "kind": "purchase", "title": title,
                "reason": purchase["purchase_reason"], "status": status, "stage": stage, "version": version,
                "instance_id": purchase["instance_id"], "agent_name": purchase["agent_name"],
                "job_id": purchase["workflow_run_id"], "job_name": purchase["deliverable_name"],
                "goal": purchase["goal"], "job_state": purchase["workflow_state"],
                "created_at": row["created_at"], "updated_at": row["updated_at"], "resolved_at": None,
                "continuation": purchase["continuation"], "details": {"amount_minor": purchase["amount_minor"], "currency": quote.get("currency", "USD")},
                "response": None, "capability": "available", "capability_message": None,
                "purchase": purchase, "purchase_id": purchase_id, "order_id": purchase["order_id"], "order": order}

    def _browser_purchase(self, conn, auth, proposal_id):
        proposal = self.browser_proposals.get(auth, proposal_id)
        job = self.workflow._job(conn, auth, proposal["workflow_run_id"])
        inst = self.workflow._instance(conn, auth, proposal["instance_id"])
        snapshot, spec = json.loads(job["config_json"]), json.loads(job["spec_json"])
        source = conn.execute("SELECT id,state,version FROM mock_workflow_deliverable WHERE id=? AND workflow_run_id=?", (proposal["deliverable_id"], job["id"])).fetchone()
        proposal["source_deliverable"] = dict(source) if source else None
        status = {"pending": "pending", "approved": "resolved", "declined": "declined", "superseded": "resolved"}[proposal["state"]]
        return {"id": "browser-purchase:" + proposal_id, "kind": "purchase", "title": proposal["description"],
                "reason": proposal["rationale"], "status": status,
                "stage": "awaiting_approval" if status == "pending" else proposal["state"],
                "version": proposal["version"], "instance_id": inst["id"], "agent_name": inst["name"],
                "job_id": job["id"], "job_name": spec["name"], "goal": snapshot["goal"], "job_state": job["state"],
                "created_at": proposal["created_at"], "updated_at": proposal["updated_at"], "resolved_at": proposal["decided_at"],
                "continuation": None, "details": {"amount_minor": proposal["amount_minor"], "currency": proposal["currency"]},
                "response": None, "capability": "available", "capability_message": None,
                "proposal": proposal, "purchase": None, "purchase_id": None, "order_id": None}

    def create(self, auth, instance_id, job_id, kind, title, reason, *, details=None, dedupe_key, continuation="now"):
        if not isinstance(kind, str) or kind not in _KINDS:
            raise AiclError("validation_failed", "Choose clarification, authentication or permission.")
        title, reason = self._text(title, "Request title", 180), self._text(reason, "Reason", 2000)
        details = self._details(kind, {} if details is None else details)
        if not isinstance(dedupe_key, str) or not _KEY.fullmatch(dedupe_key):
            raise AiclError("validation_failed", "Provide a stable short request identifier.")
        if continuation not in ("now", "schedule"):
            raise AiclError("validation_failed", "Choose now or schedule for continuation.")
        with self.db.transaction() as conn:
            self.workflow._instance(conn, auth, instance_id)
            self.workflow._require_demo_active(conn, auth)
            job = self.workflow._job(conn, auth, job_id)
            if job["instance_id"] != instance_id:
                raise AiclError("not_found", "Job not found for this agent.")
            existing = conn.execute("SELECT * FROM owner_request WHERE workflow_run_id=? AND kind=? AND dedupe_key=?",
                                    (job_id, kind, dedupe_key)).fetchone()
            if existing:
                if (existing["title"], existing["reason"], existing["details_json"]) != (title, reason, _canonical(details)):
                    raise AiclError("conflict", "This request identifier already belongs to different work.")
                return self._project(conn, auth, existing)
            if job["state"] in ("submitted", "accepted", "completed", "declined", "cancelled", "owner_declined"):
                raise AiclError("invalid_transition", "This job is no longer waiting to perform work.")
            first = conn.execute("SELECT paused_state FROM owner_request WHERE workflow_run_id=? ORDER BY rowid DESC LIMIT 1", (job_id,)).fetchone() if job["state"] == "waiting_owner" else None
            paused_state = first[0] if first else job["state"]
            request_id, now = str(uuid.uuid4()), to_iso(self.clock.now())
            conn.execute("INSERT INTO owner_request(id,tenant_id,owner_id,instance_id,workflow_run_id,kind,title,reason,details_json,dedupe_key,paused_state,continuation,created_at,updated_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (request_id, auth.tenant_id, auth.owner_id, instance_id, job_id, kind, title, reason, _canonical(details), dedupe_key, paused_state, continuation, now, now))
            conn.execute("UPDATE mock_workflow_run SET state='waiting_owner',blocked_reason='owner_request',updated_at=? WHERE id=?", (now, job_id))
            self.workflow.commerce._event(conn, auth, instance_id, "commerce.policy_changed", action="owner_request_created", run_id=job_id, target_kind=kind, confirmation_id=request_id)
            return self._project(conn, auth, self._owned(conn, auth, request_id))

    def get(self, auth, request_id):
        with self.db.reader() as conn:
            self.workflow._auth(auth)
            if isinstance(request_id, str) and request_id.startswith("browser-purchase:"):
                return self._browser_purchase(conn, auth, request_id.removeprefix("browser-purchase:"))
            if isinstance(request_id, str) and request_id.startswith("purchase:"):
                return self._purchase(conn, auth, request_id.removeprefix("purchase:"))
            return self._project(conn, auth, self._owned(conn, auth, request_id))

    def list(self, auth, instance_id=None, status="pending", kind=None):
        if status not in _STATES or kind not in (*_KINDS, "purchase", None, "all"):
            raise AiclError("validation_failed", "Choose a supported request filter.")
        with self.db.reader() as conn:
            self.workflow._auth(auth)
            if instance_id:
                self.workflow._instance(conn, auth, instance_id)
            selected_instance = instance_id or None
            params = (auth.tenant_id, auth.owner_id, selected_instance, selected_instance)
            result = []
            if kind != "purchase":
                for row in conn.execute("SELECT * FROM owner_request WHERE tenant_id=? AND owner_id=? "
                                        "AND (? IS NULL OR instance_id=?)", params):
                    if (kind in (None, "all") or row["kind"] == kind) and (status == "all" or row["status"] == status):
                        result.append(self._project(conn, auth, row))
            if kind in (None, "all", "purchase"):
                for row in conn.execute("SELECT id FROM browser_purchase_proposal WHERE tenant_id=? AND owner_id=? "
                                        "AND (? IS NULL OR instance_id=?)", params):
                    item = self._browser_purchase(conn, auth, row["id"])
                    if status == "all" or item["status"] == status:
                        result.append(item)
                for row in conn.execute("SELECT id FROM mock_commerce_purchase WHERE tenant_id=? AND owner_id=? "
                                        "AND (? IS NULL OR instance_id=?)", params):
                    item = self._purchase(conn, auth, row["id"])
                    if status == "all" or item["status"] == status:
                        result.append(item)
            return sorted(result, key=lambda item: (item["created_at"], item["id"]), reverse=True)

    def pending_count(self, auth, instance_id=None):
        return len(self.list(auth, instance_id=instance_id))

    def respond(self, auth, request_id, expected_version, answer="", decision="", continuation=None):
        if isinstance(request_id, str) and request_id.startswith(("purchase:", "browser-purchase:")):
            raise AiclError("invalid_transition", "Use the purchase review and checkout controls for this request.")
        if type(expected_version) is not int or expected_version < 1:
            raise AiclError("validation_failed", "A request version is required.")
        if continuation not in (None, "now", "schedule"):
            raise AiclError("validation_failed", "Choose now or schedule for continuation.")
        with self.db.transaction() as conn:
            row = self._owned(conn, auth, request_id)
            if row["version"] != expected_version or row["status"] != "pending":
                raise AiclError("conflict", "This request changed. Reload before responding.", current_version=row["version"])
            self.workflow._require_demo_active(conn, auth)
            if decision == "decline":
                response = {"decision": "decline", "answer": self._text(answer, "Reason", 4000, optional=True)}
                status = "declined"
            elif row["kind"] == "authentication":
                raise AiclError("unavailable", "Use the secure browser handoff for this request. A text response cannot provide or verify a sign-in session.")
            elif row["kind"] == "clarification" and decision in ("", "answer"):
                response = {"decision": "answer", "answer": self._text(answer, "Answer", 4000)}
                status = "resolved"
            elif row["kind"] == "permission" and decision == "approve":
                response = {"decision": "approve", "answer": "", "scope": json.loads(row["details_json"])["scope"]}
                status = "resolved"
            else:
                raise AiclError("validation_failed", "Choose a valid response to this request.")
            now, choice = to_iso(self.clock.now()), continuation or row["continuation"]
            conn.execute("UPDATE owner_request SET status=?,response_json=?,continuation=?,version=version+1,updated_at=?,resolved_at=? WHERE id=?", (status, _canonical(response), choice, now, now, request_id))
            conn.execute("UPDATE mock_workflow_run SET continuation=?,updated_at=? WHERE id=?", (choice, now, row["workflow_run_id"]))
            self.workflow.commerce._event(conn, auth, row["instance_id"], "commerce.policy_changed", action="owner_request_" + status, run_id=row["workflow_run_id"], target_kind=row["kind"], confirmation_id=request_id, version=expected_version + 1)
            if status == "declined":
                conn.execute("UPDATE mock_workflow_run SET state='owner_declined',blocked_reason='The owner declined this request.',updated_at=? WHERE id=?", (now, row["workflow_run_id"]))
            elif not self.pending_for_job(conn, row["workflow_run_id"]) and not conn.execute(
                    "SELECT 1 FROM owner_request WHERE workflow_run_id=? AND status='declined'", (row["workflow_run_id"],)).fetchone():
                # Hook checks schedule, budget, lifecycle and all other controls.
                # Keep the answer even when continuation is temporarily gated.
                hook = getattr(self.workflow, "owner_request_resolved", None)
                if hook:
                    try:
                        with self.db.transaction():
                            hook(auth, row["workflow_run_id"], choice)
                    except AiclError as error:
                        self.workflow._record_block(conn, auth, self.workflow._job(conn, auth, row["workflow_run_id"]), error)
            result = self._project(conn, auth, self._owned(conn, auth, request_id))
        if status == "declined" and row["kind"] == "authentication" and self.browser_cancel:
            self.browser_cancel(auth, request_id)
        if status == "resolved" and choice == "now" and self.workflow.execution_mode == "local" and self.workflow.inference:
            self.workflow.inference.drain(auth, row["instance_id"])
            return self.get(auth, request_id)
        return result

    def complete_browser_session(self, auth, request_id, session_id, expected_version, continuation=None):
        """Broker-only transition. A durable encrypted, closed handoff is required.

        No HTTP route exposes this method or accepts a caller supplied success flag.
        The result deliberately says session_provided, never authenticated/verified.
        """
        if not self.browser_enabled:
            raise AiclError("unavailable", "The private browser service is not configured.")
        if continuation not in (None, "now", "schedule"):
            raise AiclError("validation_failed", "Choose now or schedule for continuation.")
        with self.db.transaction() as conn:
            row = self._owned(conn, auth, request_id)
            if row["kind"] != "authentication" or row["status"] != "pending" or type(expected_version) is not int or row["version"] != expected_version:
                raise AiclError("conflict", "This sign-in request changed. Reload before continuing.")
            self.workflow._require_demo_active(conn, auth)
            if self.workflow._job(conn, auth, row["workflow_run_id"])["state"] != "waiting_owner":
                raise AiclError("conflict", "This job is no longer waiting for sign-in.")
            browser = conn.execute("SELECT * FROM browser_session WHERE id=? AND tenant_id=? AND owner_id=? AND instance_id=? AND request_id=? AND workflow_run_id=? AND request_version=? AND mode='owner' AND state='complete' AND secret_ref IS NOT NULL AND credential_expires_at>?", (session_id, auth.tenant_id, auth.owner_id, row["instance_id"], request_id, row["workflow_run_id"], expected_version, to_iso(self.clock.now()))).fetchone()
            if browser is None or browser["domain"] != json.loads(row["details_json"])["domain"]:
                raise AiclError("denied", "A current browser handoff is required to resolve this request.", reason="connection_unavailable")
            now, choice = to_iso(self.clock.now()), continuation or row["continuation"]
            response = {"decision": "session_provided", "browser_session_id": session_id, "domain": browser["domain"], "access_verified": False}
            conn.execute("UPDATE owner_request SET status='resolved',response_json=?,continuation=?,version=version+1,updated_at=?,resolved_at=? WHERE id=?", (_canonical(response), choice, now, now, request_id))
            conn.execute("UPDATE mock_workflow_run SET continuation=?,updated_at=? WHERE id=?", (choice, now, row["workflow_run_id"]))
            self.workflow.commerce._event(conn, auth, row["instance_id"], "commerce.policy_changed", action="browser_session_provided", run_id=row["workflow_run_id"], target_kind="authentication", confirmation_id=request_id, version=expected_version + 1)
            if not self.pending_for_job(conn, row["workflow_run_id"]) and not conn.execute("SELECT 1 FROM owner_request WHERE workflow_run_id=? AND status='declined'", (row["workflow_run_id"],)).fetchone():
                hook = getattr(self.workflow, "owner_request_resolved", None)
                if hook:
                    try:
                        with self.db.transaction():
                            hook(auth, row["workflow_run_id"], choice)
                    except AiclError as error:
                        self.workflow._record_block(conn, auth, self.workflow._job(conn, auth, row["workflow_run_id"]), error)
            return self._project(conn, auth, self._owned(conn, auth, request_id))

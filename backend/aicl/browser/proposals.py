"""Immutable browser-sourced proposals; owner decisions never initiate checkout.

Only the trusted browser workflow creates these records after checking observed
evidence. There is intentionally no worker-facing create/approve API here and no
merchant/order mapping. An approved proposal is a recorded decision, not payment
authority or a reservation against a funding balance.
"""
from __future__ import annotations

import ipaddress
import json
import re
import uuid
from urllib.parse import urlparse

from aicl.commerce.service import _canonical
from aicl.control.errors import AiclError
from aicl.db import to_iso


class BrowserPurchaseProposalService:
    def __init__(self, workflow):
        self.workflow = workflow
        self.db, self.clock = workflow.db, workflow.clock

    def _payload(self, payload):
        if not isinstance(payload, dict) or set(payload) != {
            "seller", "domain", "amount_minor", "currency", "description", "rationale", "evidence"
        }:
            raise AiclError("validation_failed", "Provide the seller, website, proposed budget, description, rationale and browser evidence.")
        data = {key: self.workflow._text(payload[key], key.title(), limit) for key, limit in (
            ("seller", 180), ("domain", 253), ("description", 2000), ("rationale", 4000))}
        domain = data["domain"].lower().rstrip(".")
        labels = domain.split(".")
        if (not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain) or len(labels) < 2
                or any(not part or len(part) > 63 or part.startswith("-") or part.endswith("-") for part in labels)
                or domain.endswith((".local", ".localhost", ".internal"))):
            raise AiclError("validation_failed", "Provide the public website hostname for this proposal.")
        try:
            ipaddress.ip_address(domain)
        except ValueError:
            pass
        else:
            raise AiclError("validation_failed", "A proposal must name a website, not an IP address.")
        amount = payload["amount_minor"]
        if type(amount) is not int or not 0 < amount <= 100_000_000 or payload["currency"] != "USD":
            raise AiclError("validation_failed", "Provide a positive USD proposed budget in whole cents.")
        evidence = payload["evidence"]
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
            raise AiclError("validation_failed", "Include one to eight observations from the browser.")
        observations = []
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"url", "title", "excerpt"}:
                raise AiclError("validation_failed", "Each observation needs its source URL, page title and exact excerpt.")
            observation = {key: self.workflow._text(item[key], "Evidence " + key, limit) for key, limit in (
                ("url", 2000), ("title", 200), ("excerpt", 2000))}
            try:
                url = urlparse(observation["url"])
                valid = (url.scheme == "https" and url.hostname == domain and url.port in (None, 443)
                         and not url.username and not url.password and not url.query and not url.fragment
                         and not any(char.isspace() or ord(char) < 32 for char in observation["url"]))
            except ValueError:
                valid = False
            if not valid:
                raise AiclError("validation_failed", "Evidence must use the proposal website's HTTPS URL, without login tokens or URL parameters.")
            observations.append(observation)
        return {**data, "domain": domain, "amount_minor": amount, "currency": "USD", "evidence": observations}

    def _owned(self, conn, auth, proposal_id):
        self.workflow._auth(auth)
        row = conn.execute("SELECT * FROM browser_purchase_proposal WHERE id=? AND tenant_id=? AND owner_id=?",
                           (proposal_id, auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Purchase proposal not found.")
        self.workflow._instance(conn, auth, row["instance_id"])
        return row

    @staticmethod
    def _project(row):
        result = dict(row)
        result["evidence"] = json.loads(result.pop("evidence_json"))
        return result

    @staticmethod
    def _same_payload(row, payload):
        return all(row[key] == value for key, value in payload.items() if key != "evidence") and row["evidence_json"] == _canonical(payload["evidence"])

    def _controls(self, conn, auth, job, amount, *, exclude_id=""):
        self.workflow._require_demo_active(conn, auth)
        self.workflow.commerce._controls(conn, auth, job["instance_id"])
        if job["state"] in ("cancelled", "declined", "owner_declined") or conn.execute(
                "SELECT 1 FROM owner_request WHERE workflow_run_id=? AND status IN ('pending','declined')", (job["id"],)).fetchone():
            raise AiclError("denied", "Resolve the job's outstanding owner requests before approving a purchase proposal.", reason="owner_request")
        # Proposals do not reserve or spend money. This conservative check limits
        # the combined pending/approved recommendations plus existing purchases;
        # a future checkout must make its own current quote and budget reservation.
        recommendations = conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM browser_purchase_proposal "
                                       "WHERE instance_id=? AND state IN ('pending','approved') AND id<>?",
                                       (job["instance_id"], exclude_id)).fetchone()[0]
        self.workflow.commerce._purchase_policy(conn, job["instance_id"], additional=amount + recommendations)

    @staticmethod
    def _latest_output(conn, job_id):
        return conn.execute("SELECT * FROM mock_workflow_deliverable WHERE workflow_run_id=? ORDER BY version DESC LIMIT 1", (job_id,)).fetchone()

    def _invalidate(self, conn, auth, job):
        if conn.execute("SELECT 1 FROM browser_purchase_proposal WHERE workflow_run_id=? AND state='approved'", (job["id"],)).fetchone():
            raise AiclError("invalid_transition", "This job has an approved proposal. Keep that decision and its source work unchanged.")
        now = to_iso(self.clock.now())
        rows = conn.execute("SELECT id,version FROM browser_purchase_proposal WHERE workflow_run_id=? AND state='pending'", (job["id"],)).fetchall()
        for row in rows:
            conn.execute("UPDATE browser_purchase_proposal SET state='superseded',version=version+1,updated_at=?,decided_at=? WHERE id=?", (now, now, row["id"]))
            self.workflow.commerce._event(conn, auth, job["instance_id"], "commerce.policy_changed",
                                          action="browser_purchase_superseded", run_id=job["id"],
                                          confirmation_id=row["id"], version=row["version"] + 1)
        return len(rows)

    def invalidate(self, auth, job_id):
        """Supersede pending decisions when the owner requests an output revision."""
        with self.db.transaction() as conn:
            job = self.workflow._job(conn, auth, job_id)
            return self._invalidate(conn, auth, job)

    def propose(self, auth, job_id, payload):
        data = self._payload(payload)
        with self.db.transaction() as conn:
            job = self.workflow._job(conn, auth, job_id)
            source = self._latest_output(conn, job_id)
            if not source:
                raise AiclError("invalid_transition", "Submit the supporting deliverable before proposing a purchase.")
            existing = conn.execute("SELECT * FROM browser_purchase_proposal WHERE deliverable_id=?", (source["id"],)).fetchone()
            if existing:
                if not self._same_payload(existing, data):
                    raise AiclError("conflict", "This deliverable already has a different immutable purchase proposal.")
                return self._project(existing)
            if source["state"] != "submitted":
                raise AiclError("invalid_transition", "Submit the supporting deliverable before proposing a purchase.")
            self._invalidate(conn, auth, job)
            self._controls(conn, auth, job, data["amount_minor"])
            proposal_id, now = str(uuid.uuid4()), to_iso(self.clock.now())
            conn.execute("INSERT INTO browser_purchase_proposal(id,tenant_id,owner_id,instance_id,workflow_run_id,deliverable_id,"
                         "seller,domain,amount_minor,currency,description,rationale,evidence_json,created_at,updated_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (proposal_id, auth.tenant_id, auth.owner_id, job["instance_id"], job_id, source["id"],
                         data["seller"], data["domain"], data["amount_minor"], data["currency"], data["description"], data["rationale"],
                         _canonical(data["evidence"]), now, now))
            self.workflow.commerce._event(conn, auth, job["instance_id"], "commerce.policy_changed",
                                          action="browser_purchase_proposed", run_id=job_id,
                                          confirmation_id=proposal_id, amount_minor=data["amount_minor"], version=1)
            return self._project(self._owned(conn, auth, proposal_id))

    def get(self, auth, proposal_id):
        with self.db.reader() as conn:
            return self._project(self._owned(conn, auth, proposal_id))

    def list(self, auth, instance_id=None):
        with self.db.reader() as conn:
            self.workflow._auth(auth)
            params, where = [auth.tenant_id, auth.owner_id], "tenant_id=? AND owner_id=?"
            if instance_id:
                self.workflow._instance(conn, auth, instance_id)
                where += " AND instance_id=?"
                params.append(instance_id)
            return [self._project(row) for row in conn.execute("SELECT * FROM browser_purchase_proposal WHERE " + where + " ORDER BY created_at,id", params)]

    def decide(self, auth, proposal_id, decision, expected_version):
        if decision not in ("approve", "decline") or type(expected_version) is not int or expected_version < 1:
            raise AiclError("validation_failed", "Choose approve or decline for the current proposal version.")
        with self.db.transaction() as conn:
            row = self._owned(conn, auth, proposal_id)
            if row["version"] != expected_version or row["state"] != "pending":
                raise AiclError("conflict", "This proposal changed. Reload before responding.", current_version=row["version"])
            if decision == "approve":
                source = self._latest_output(conn, row["workflow_run_id"])
                if not source or source["id"] != row["deliverable_id"] or source["state"] not in ("submitted", "accepted"):
                    raise AiclError("conflict", "The supporting work has changed. Review its new proposal before approving.")
                job = self.workflow._job(conn, auth, row["workflow_run_id"])
                self._controls(conn, auth, job, row["amount_minor"], exclude_id=row["id"])
            state, now = ("approved" if decision == "approve" else "declined"), to_iso(self.clock.now())
            conn.execute("UPDATE browser_purchase_proposal SET state=?,version=version+1,updated_at=?,decided_at=? WHERE id=?",
                         (state, now, now, proposal_id))
            self.workflow.commerce._event(conn, auth, row["instance_id"], "commerce.policy_changed",
                                          action="browser_purchase_" + state, run_id=row["workflow_run_id"],
                                          confirmation_id=proposal_id, version=expected_version + 1)
            return self._project(self._owned(conn, auth, proposal_id))

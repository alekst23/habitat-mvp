"""Bounded browser preparation for a scheduled purchase recommendation.

Only observations are collected. No merchant draft, checkout or payment action
is available here. Website content is untrusted evidence for owner review.
"""
import json
from urllib.parse import urlsplit

from aicl.control.errors import AiclError
from aicl.db import to_iso
from aicl.owner_requests.service import OwnerRequestService


def request_signin(workflow, conn, auth, job, *, reason="The agent needs your account to inspect this website."):
    task = json.loads(job["config_json"])["browser_task"]
    domain = urlsplit(task["service_url"]).hostname
    pending = conn.execute("SELECT id FROM owner_request WHERE workflow_run_id=? AND kind='authentication' AND status='pending'", (job["id"],)).fetchone()
    if pending:
        return {"state": "waiting_owner", "request_id": pending[0]}
    count = conn.execute("SELECT COUNT(*) FROM owner_request WHERE workflow_run_id=? AND kind='authentication'", (job["id"],)).fetchone()[0]
    if count >= 5:
        raise AiclError("denied", "This job reached its sign-in retry limit. Review the website and job before continuing.", reason="request_limit")
    request = OwnerRequestService(workflow, browser_enabled=True).create(auth, job["instance_id"], job["id"],
        "authentication", "Sign in to " + domain, reason,
        details={"domain": domain, "requested_access": ("Read account information to prepare this proposal: " + task["objective"])[:500]},
        dedupe_key=f"browser-signin-{count + 1}", continuation="schedule")
    return {"state": "waiting_owner", "request_id": request["id"]}


class BrowserPreparation:
    def __init__(self, execution):
        self.execution, self.workflow = execution, execution.workflow
        self.db, self.clock = execution.db, execution.clock

    def _grant(self, conn, job, domain):
        return conn.execute("SELECT r.id FROM owner_request r JOIN browser_session b ON b.id=json_extract(r.response_json,'$.browser_session_id') "
            "WHERE r.instance_id=? AND r.kind='authentication' AND r.status='resolved' AND b.state='complete' "
            "AND b.mode='owner' AND b.secret_ref IS NOT NULL AND b.credential_expires_at>? AND b.domain=? "
            "AND b.tenant_id=r.tenant_id AND b.owner_id=r.owner_id AND b.instance_id=r.instance_id AND b.request_id=r.id "
            "AND NOT EXISTS(SELECT 1 FROM owner_request p WHERE p.instance_id=r.instance_id AND p.kind='authentication' "
            "AND p.status='pending' AND json_extract(p.details_json,'$.domain')=b.domain) ORDER BY r.rowid DESC LIMIT 1",
            (job["instance_id"], to_iso(self.clock.now()), domain)).fetchone()

    def ready(self, conn, auth, job, attempt_id):
        task = json.loads(job["config_json"])["browser_task"]
        evidence = conn.execute("SELECT * FROM browser_attempt_evidence WHERE attempt_id=? AND workflow_run_id=?", (attempt_id, job["id"])).fetchone()
        grant = self._grant(conn, job, urlsplit(task["service_url"]).hostname)
        return bool(evidence and grant and evidence["request_id"] == grant["id"])

    def prepare(self, dispatch_id, task_run_id, attempt_id):
        execution = self.execution
        with self.db.transaction() as conn:
            row = execution._row(conn, dispatch_id, task_run_id)
            mapping, attempt, job = execution._attempt(conn, row, attempt_id)
            auth, _ = execution._browser_job_authority(conn, dispatch_id, task_run_id, job["id"])
            config = json.loads(job["config_json"])
            if config.get("scenario") != "browser_purchase":
                raise AiclError("invalid_transition", "This job has no browser preparation stage.")
            if mapping["result_json"] or self.ready(conn, auth, job, attempt_id):
                return {"state": "ready"}
            if attempt["state"] != "pending":
                raise AiclError("conflict", "Resolve the current inference attempt before preparing browser evidence.")
            task = config["browser_task"]
            grant = self._grant(conn, job, urlsplit(task["service_url"]).hostname)
            if not grant:
                return request_signin(self.workflow, conn, auth, job)
            job_id, request_id = job["id"], grant["id"]
        try:
            page = execution.browser_page(dispatch_id, task_run_id, job_id, request_id, task["service_url"])
        except AiclError as error:
            with self.db.transaction() as conn:
                auth, _ = execution._browser_job_authority(conn, dispatch_id, task_run_id, job_id)
                job = self.workflow._job(conn, auth, job_id)
                if error.extra.get("reason") == "connection_unavailable":
                    return request_signin(self.workflow, conn, auth, job, reason="Saved access expired or was revoked. Sign in again so this job can continue.")
                # A runtime outage is not evidence that login failed. Keep the
                # attempt retryable at the next scheduled occurrence.
                conn.execute("UPDATE workflow_inference_attempt SET state='blocked',validation_error='browser_unavailable' WHERE id=?", (attempt_id,))
                conn.execute("UPDATE mock_workflow_run SET state='inference_blocked',blocked_reason=? WHERE id=?", ("The browser could not read the website. The schedule will retry.", job_id))
                return {"state": "blocked"}
        with self.db.transaction() as conn:
            auth, _ = execution._browser_authority(conn, dispatch_id, task_run_id, job_id, request_id)
            job = self.workflow._job(conn, auth, job_id)
            if conn.execute("SELECT state FROM workflow_inference_attempt WHERE id=?", (attempt_id,)).fetchone()[0] != "pending":
                raise AiclError("conflict", "This attempt advanced while browser evidence was being read.")
            grant = self._grant(conn, job, urlsplit(task["service_url"]).hostname)
            if not grant or grant["id"] != request_id:
                return request_signin(self.workflow, conn, auth, job)
            if page["url"] != "https://" + urlsplit(task["service_url"]).hostname:
                return request_signin(self.workflow, conn, auth, job, reason="The website redirected away from the requested service. Complete its sign-in and return access.")
            evidence = {"url": "https://" + urlsplit(task["service_url"]).hostname,
                        "title": page["title"][:200], "text": page["text"].encode("utf-8")[:4000].decode("utf-8", errors="ignore"),
                        "observed_at": to_iso(self.clock.now())}
            conn.execute("INSERT INTO browser_attempt_evidence(attempt_id,workflow_run_id,request_id,evidence_json,observed_at) VALUES(?,?,?,?,?) "
                         "ON CONFLICT(attempt_id) DO UPDATE SET request_id=excluded.request_id,evidence_json=excluded.evidence_json,observed_at=excluded.observed_at",
                         (attempt_id, job_id, request_id, json.dumps(evidence), evidence["observed_at"]))
            return {"state": "ready"}

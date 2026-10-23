"""Durable, bounded model calls for the explicitly advanced PocketPlan demo.

Preparing/claiming, provider I/O, and settlement are separate phases. A process
interruption after claiming is an unresolved charge, never permission to resend.
No background scheduler, payment approval, or real advertising is added here.
"""
from __future__ import annotations

import json
import uuid

from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.db import to_iso

MODEL = "gpt-6-sol"
PRICE_VERSION = "gpt-6-sol-2026-10-22"
MAX_INPUT_TOKENS = 16000
MAX_OUTPUT_TOKENS = 2000
MAX_COST = 52000


def uses_model(snapshot, spec):
    return snapshot.get("scenario") == "pocketplan_ads" and spec.get("ad_kind", spec["key"]) in (
        "campaign_plan", "performance_report")


class WorkflowInference:
    def __init__(self, workflow, adapter, max_spend_micro_usd):
        if type(max_spend_micro_usd) is not int or max_spend_micro_usd <= 0:
            raise ValueError("inference_max_spend_micro_usd must be a positive integer")
        self.workflow, self.adapter, self.cap = workflow, adapter, max_spend_micro_usd
        self.db, self.clock, self.commerce = workflow.db, workflow.clock, workflow.commerce

    def stage(self, conn, auth, job, version, feedback):
        now = to_iso(self.clock.now())
        conn.execute("INSERT OR IGNORE INTO workflow_inference_attempt "
                     "(id,workflow_run_id,version,state,feedback,created_at,updated_at) VALUES (?,?,?,'pending',?,?,?)",
                     (str(uuid.uuid4()), job["id"], version, feedback, now, now))
        # Only a proven pre-dispatch denial may be tried at a later owner tick.
        conn.execute("UPDATE workflow_inference_attempt SET state='pending',validation_error=NULL,updated_at=? "
                     "WHERE workflow_run_id=? AND version=? AND state='blocked'", (now, job["id"], version))
        attempt = conn.execute("SELECT * FROM workflow_inference_attempt WHERE workflow_run_id=? AND version=? ORDER BY rowid DESC LIMIT 1",
                               (job["id"], version)).fetchone()
        if attempt["state"] == "pending":
            conn.execute("UPDATE mock_workflow_run SET state='generating',blocked_reason=NULL,updated_at=? WHERE id=?",
                         (now, job["id"]))

    def _claim(self, auth, attempt_id):
        with self.db.transaction() as conn:
            attempt = conn.execute("SELECT * FROM workflow_inference_attempt WHERE id=?", (attempt_id,)).fetchone()
            if attempt is None or attempt["state"] != "pending":
                return None
            job = self.workflow._job(conn, auth, attempt["workflow_run_id"])
            try:
                with self.db.transaction():
                    config = self.workflow._config(conn, auth, job["instance_id"])
                    if not config["enabled"]:
                        raise AiclError("denied", "Enable the schedule before generating work.", reason="schedule_paused")
                    self.commerce._controls(conn, auth, job["instance_id"])
                    if conn.execute("SELECT 1 FROM workflow_inference_attempt WHERE state IN ('inflight','unknown')").fetchone():
                        raise AiclError("denied", "Another real inference request is in progress or unresolved. Its outcome must be known before further dispatch.", reason="reconciliation_pending")
                    outstanding = conn.execute("SELECT COALESCE(SUM(CASE WHEN state='settled' THEN cost_micro_usd "
                                               "WHEN state IN ('inflight','unknown') THEN max_cost_micro_usd ELSE 0 END),0) "
                                               "FROM workflow_inference_attempt").fetchone()[0]
                    if outstanding + MAX_COST > self.cap:
                        raise AiclError("denied", "The server's real inference spend ceiling is reached. Demo funding cannot increase it.", reason="inference_spend_ceiling")
                    if conn.execute("SELECT 1 FROM workflow_inference_attempt WHERE validation_error='usage_exceeded_bound'").fetchone():
                        raise AiclError("denied", "A previous provider response exceeded its reserved bound; review usage before any further dispatch.", reason="reconciliation_pending")
                    if self.commerce._balance(conn, job["instance_id"]) < MAX_COST:
                        raise AiclError("denied", "Service credit must cover the full bounded inference estimate.", reason="credit_insufficient")
                    hold = self.commerce.budget.reserve(conn, job["instance_id"], "workflow-inference:" + attempt_id,
                        Estimate(MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS, 0), price_table_version=PRICE_VERSION)
                    now = to_iso(self.clock.now())
                    conn.execute("UPDATE workflow_inference_attempt SET state='inflight',hold_id=?,updated_at=? WHERE id=?",
                                 (hold.id, now, attempt_id))
                    self.commerce._event(conn, auth, job["instance_id"], "budget.reserved", mode="openai", provider="openai",
                                         run_id=job["id"], hold_id=hold.id, micro_usd=MAX_COST, price_table_version=PRICE_VERSION)
            except AiclError as error:
                conn.execute("UPDATE workflow_inference_attempt SET state='blocked',validation_error=?,updated_at=? WHERE id=?",
                             (error.extra.get("reason", error.error), to_iso(self.clock.now()), attempt_id))
                conn.execute("UPDATE mock_workflow_run SET state='inference_blocked' WHERE id=?", (job["id"],))
                self.workflow._record_block(conn, auth, job, error)
                return None
            return dict(attempt) | {"hold_id": hold.id}, dict(job)

    def _failure(self, auth, attempt, job, *, no_charge, reason):
        with self.db.transaction() as conn:
            current = conn.execute("SELECT state FROM workflow_inference_attempt WHERE id=?", (attempt["id"],)).fetchone()
            if current[0] != "inflight":
                return
            if no_charge:
                self.commerce.budget.release(conn, attempt["hold_id"])
                state, message = "released", "The model request was not accepted. No inference charge was recorded."
            else:
                self.commerce.budget.mark_unknown(conn, attempt["hold_id"])
                state, message = "unknown", "The inference outcome is unresolved. Its budget and credit remain reserved; the request will not be sent again."
            now = to_iso(self.clock.now())
            conn.execute("UPDATE workflow_inference_attempt SET state=?,validation_error=?,updated_at=? WHERE id=?",
                         (state, reason, now, attempt["id"]))
            conn.execute("UPDATE mock_workflow_run SET state=?,blocked_reason=?,updated_at=? WHERE id=?",
                         ("inference_failed" if no_charge else "inference_unknown", message, now, job["id"]))
            self.commerce._event(conn, auth, job["instance_id"], "commerce.denied", "denied", mode="openai", provider="openai",
                                 reason=reason, run_id=job["id"], hold_id=attempt["hold_id"], action="inference_failed")

    def _checked_output(self, result, snapshot, spec):
        """Schema/source checks are not semantic verification of model claims."""
        criteria = result.criteria
        error = getattr(result, "validation_error", None)
        if not error and (not isinstance(result.content, str) or not result.content.strip() or len(result.content) > 30000):
            error = "invalid_content"
        if not error and (not isinstance(criteria, list) or len(criteria) != len(spec["criteria"]) or any(
                not isinstance(c, dict) or c.get("criterion") != expected or type(c.get("passed")) is not bool
                or not isinstance(c.get("reason"), str) or len(c["reason"]) > 3000
                for c, expected in zip(criteria, spec["criteria"]))):
            error = "invalid_criteria"
        if error:
            return "The model response did not pass output validation. Review this job before requesting further work.", [
                {"criterion": c, "passed": False, "reason": "No validated model output was returned."} for c in spec["criteria"]], "needs_work", error
        criteria = [{**c, "reason": "Model self-assessment (not independent verification): " + c["reason"].removeprefix(
            "Model self-assessment (not independent verification): ")} for c in criteria]
        content = result.content.strip()
        report = spec.get("ad_report")
        if report:
            # These facts/calculations come from the stored campaign ledger, not
            # from the model. The narrative still requires owner quality review.
            facts = ["Verified source record (demo advertising metrics)", "Reported at: " + report["reported_at"]]
            if report.get("organic"):
                facts.append("Paid advertising was declined. Paid spend: $0.00. No paid delivery or installs are claimed.")
            else:
                spend, clicks, installs = report["spend_minor"], report["clicks"], report["attributed_installs"]
                facts += [f"Campaign state: {report['state']}", f"Prepaid funds: ${report['funding_minor']/100:.2f}; consumed: ${report['consumed_minor']/100:.2f}; remaining: ${report['remaining_minor']/100:.2f}.",
                    f"Day spend: ${spend/100:.2f}; impressions: {report['impressions']}; clicks: {clicks}; attributed installs: {installs}.",
                    f"CPC = ${spend/100:.2f} / {clicks} clicks = " + (f"${spend/clicks/100:.2f}" if clicks else "unavailable (zero clicks)"),
                    f"CPI = ${spend/100:.2f} / {installs} installs = " + (f"${spend/installs/100:.2f}" if installs else "unavailable (zero installs)")]
            content += "\n\n" + "\n".join(facts)
        else:
            content += "\n\nVerified merchant constraints: the initial campaign quote is $30 total, $10 per day, for three days. The exact fixture creative, audience and destination are displayed separately for owner approval. This model output cannot authorize a purchase."
        content += "\n\nGenerated with GPT-6 Sol from saved inputs. Model checks are self-assessments; the owner reviews quality. Advertising and audience evidence remain supplied demo fixtures."
        return content, criteria, "submitted" if all(c["passed"] for c in criteria) else "needs_work", None

    def _settle(self, auth, attempt, job, result):
        values = (result.input_tokens, result.output_tokens)
        if any(type(v) is not int or v < 0 for v in values) or result.model != MODEL or not isinstance(result.response_id, str) or not result.response_id:
            self._failure(auth, attempt, job, no_charge=False, reason="invalid_provider_usage")
            return
        snapshot, spec = json.loads(job["config_json"]), json.loads(job["spec_json"])
        content, criteria, output_state, error = self._checked_output(result, snapshot, spec)
        if values[0] > MAX_INPUT_TOKENS or values[1] > MAX_OUTPUT_TOKENS:
            error, output_state = "usage_exceeded_bound", "needs_work"
        with self.db.transaction() as conn:
            current = conn.execute("SELECT state FROM workflow_inference_attempt WHERE id=?", (attempt["id"],)).fetchone()
            if current[0] != "inflight":
                return
            # Always settle observed usage, even after pause/revocation or invalid
            # output. A real provider charge cannot be undone by a local rollback.
            usage = self.commerce.budget.settle(conn, attempt["hold_id"], MeasuredUsage(*values, 0))
            cost, now = usage.inference_micro_usd, to_iso(self.clock.now())
            conn.execute("INSERT INTO mock_commerce_ledger (id,instance_id,kind,delta_micro_usd,reference,hold_id,created_at) "
                         "VALUES (?,?,'inference_usage',?,?,?,?)", (str(uuid.uuid4()), job["instance_id"], -cost, "inference:" + job["id"] + ":" + attempt["id"], attempt["hold_id"], now))
            conn.execute("UPDATE workflow_inference_attempt SET state='settled',cost_micro_usd=?,input_tokens=?,output_tokens=?,response_id=?,validation_error=?,updated_at=? WHERE id=?",
                         (cost, *values, result.response_id, error, now, attempt["id"]))
            conn.execute("INSERT INTO mock_workflow_deliverable(id,workflow_run_id,version,content,criteria_json,state,created_at) VALUES (?,?,?,?,?,?,?)",
                         (str(uuid.uuid4()), job["id"], attempt["version"], content, json.dumps(criteria), output_state, now))
            conn.execute("UPDATE mock_workflow_run SET state=?,blocked_reason=?,updated_at=? WHERE id=?",
                         (output_state, "Provider usage exceeded the reserved bound; further dispatch is blocked." if error == "usage_exceeded_bound" else None, now, job["id"]))
            conn.execute("UPDATE mock_commerce_run SET state='completed',output=?,inference_cost_micro_usd=inference_cost_micro_usd+?,input_tokens=input_tokens+?,output_tokens=output_tokens+?,updated_at=? WHERE id=?",
                         (content, cost, *values, now, job["commerce_run_id"]))
            self.commerce._event(conn, auth, job["instance_id"], "budget.settled", mode="openai", provider="openai", run_id=job["id"], hold_id=attempt["hold_id"], micro_usd=cost, price_table_version=PRICE_VERSION)
            self.commerce._event(conn, auth, job["instance_id"], "commerce.run_completed", mode="openai", provider="openai", run_id=job["id"], action=output_state, version=attempt["version"])

    def drain(self, auth, instance_id):
        # Import lazily: fixture-only installations never construct a real client.
        from aicl.workflow.openai_inference import InferenceNoChargeError
        if getattr(self.db._local, "conn", None) is not None:
            raise RuntimeError("Provider dispatch must run outside a database transaction")
        with self.db.reader() as conn:
            self.workflow._instance(conn, auth, instance_id)
            ids = [r[0] for r in conn.execute("SELECT a.id FROM workflow_inference_attempt a JOIN mock_workflow_run w ON w.id=a.workflow_run_id "
                                             "WHERE w.instance_id=? AND a.state='pending' ORDER BY a.rowid", (instance_id,))]
        dispatched = 0
        for attempt_id in ids:
            claimed = self._claim(auth, attempt_id)
            if claimed is None:
                continue
            attempt, job = claimed
            dispatched += 1
            try:
                result = self.adapter.generate(json.loads(job["config_json"]), json.loads(job["spec_json"]), attempt["feedback"])
            except InferenceNoChargeError as error:
                self._failure(auth, attempt, job, no_charge=True, reason=getattr(error, "reason", "provider_rejected"))
            except Exception:
                # Never include remote exception text; it can contain bodies or
                # credentials. Ambiguous dispatch keeps both ceilings reserved.
                self._failure(auth, attempt, job, no_charge=False, reason="provider_outcome_unknown")
            else:
                self._settle(auth, attempt, job, result)
        return dispatched


def provenance(conn, run_id, version):
    row = conn.execute("SELECT * FROM workflow_inference_attempt WHERE workflow_run_id=? AND version=? AND state='settled'", (run_id, version)).fetchone()
    if not row:
        return None
    return {"provider": "openai", **{key: row[key] for key in ("model", "response_id", "input_tokens", "output_tokens", "cost_micro_usd", "validation_method", "validation_error")}}

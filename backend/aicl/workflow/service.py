"""Persistent, deterministic owner-workflow fixtures, never background execution.

The demo clock advances only schedule occurrences. Authentication, payment expiry,
controls and accounting use the real injected clock. Reading projections has no
side effects; every transition is explicit, owner-scoped and transactional.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aicl.commerce.service import MockCommerceService, _canonical
from aicl.control.errors import AiclError
from aicl.creation.operations import SqliteInstanceOperations
from aicl.db import from_iso, to_iso
from aicl.workflow.ad_scenario import AdWorkflowMixin, SCENARIO, ad_content
from aicl.workflow.inference_service import WorkflowInference, provenance, uses_model

_MAX_VERSIONS = 5
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _id():
    return str(uuid.uuid4())


class MockWorkflowService(AdWorkflowMixin):
    def __init__(self, db, clock, commerce=None, *, inference=None, inference_max_spend_micro_usd=1_000_000, execution_mode="local",
                 render_max_spend_micro_usd=1_000_000, render_max_dispatches=100):
        if type(render_max_spend_micro_usd) is not int or render_max_spend_micro_usd <= 0:
            raise ValueError("render_max_spend_micro_usd must be a positive integer")
        if type(render_max_dispatches) is not int or render_max_dispatches <= 0:
            raise ValueError("render_max_dispatches must be a positive integer")
        self.db, self.clock = db, clock
        self.commerce = commerce or MockCommerceService(db, clock)
        self.inference = WorkflowInference(self, inference, inference_max_spend_micro_usd) if inference is not None else None
        self.execution_mode = execution_mode
        self.render_max_spend_micro_usd = render_max_spend_micro_usd
        self.render_max_dispatches = render_max_dispatches

    def _demo_expired(self, conn, owner_id):
        demo = conn.execute("SELECT expires_at FROM judge_demo_workspace WHERE owner_id=?", (owner_id,)).fetchone()
        return demo is not None and from_iso(demo["expires_at"]) <= self.clock.now()

    def _require_demo_active(self, conn, auth):
        if self._demo_expired(conn, auth.owner_id):
            raise AiclError("denied", "This demo workspace has expired. New work is stopped.", reason="judge_demo_expired")

    def _auth(self, auth):
        if auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "Sign in to continue.")

    def _instance(self, conn, auth, instance_id):
        return self.commerce._owned_instance(conn, auth, instance_id)

    def _job(self, conn, auth, run_id):
        row = conn.execute("SELECT * FROM mock_workflow_run WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise AiclError("not_found", "Scheduled job not found.")
        self._instance(conn, auth, row["instance_id"])
        return row

    def _config(self, conn, auth, instance_id):
        inst = self._instance(conn, auth, instance_id)
        row = conn.execute("SELECT * FROM mock_workflow_config WHERE instance_id = ?", (instance_id,)).fetchone()
        if not row:
            saved_brief = conn.execute("SELECT draft_brief_json FROM mock_commerce_account WHERE instance_id=?", (instance_id,)).fetchone()
            brief = json.loads(saved_brief[0]) if saved_brief else {}
            return {"instance_id": instance_id, "scenario": "generic", "goal": brief.get("goal", inst["instructions"]),
                    "inputs": "\n".join(value for value in (brief.get("product_name"), brief.get("audience")) if value), "deliverables": [],
                    "cadence": "daily", "timezone": "UTC", "version": 1, "saved": False,
                    "enabled": False, "next_due": None, "demo_time": None, "last_outcome": None,
                    "name": inst["name"], "instance_version": inst["version"]}
        return {"scenario": "generic", **json.loads(row["data_json"]), "instance_id": instance_id, "name": inst["name"],
                "version": row["version"], "saved": True, "enabled": bool(row["enabled"]),
                "next_due": row["next_due"], "demo_time": row["demo_time"], "last_outcome": row["last_outcome"],
                "instance_version": inst["version"]}

    def config(self, auth, instance_id):
        with self.db.reader() as conn:
            return self._config(conn, auth, instance_id)

    def _text(self, value, name, limit, *, optional=False):
        if not isinstance(value, str) or len(value.strip()) > limit or (not optional and not value.strip()):
            raise AiclError("validation_failed", f"{name} must contain {'0' if optional else '1'}–{limit} characters.")
        return value.strip()

    def _normalize(self, data):
        if not isinstance(data, dict):
            raise AiclError("validation_failed", "Complete the workflow configuration.")
        scenario_id = data.get("scenario", "generic")
        if scenario_id not in ("generic", SCENARIO):
            raise AiclError("validation_failed", "Choose a supported workflow example.")
        goal = self._text(data.get("goal"), "Goal", 2000)
        inputs = self._text(data.get("inputs", ""), "Inputs", 4000, optional=True)
        cadence, timezone = data.get("cadence", "daily"), data.get("timezone", "UTC")
        if cadence not in ("hourly", "daily"):
            raise AiclError("validation_failed", "Choose an hourly or daily schedule.")
        try:
            if not isinstance(timezone, str) or len(timezone) > 80:
                raise ValueError()
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise AiclError("validation_failed", "Choose a valid IANA timezone, such as America/New_York.")
        specs = data.get("deliverables")
        if not isinstance(specs, list) or not 1 <= len(specs) <= 6:
            raise AiclError("validation_failed", "Configure one to six deliverables.")
        normalized, keys = [], set()
        for index, spec in enumerate(specs):
            if not isinstance(spec, dict):
                raise AiclError("validation_failed", "Each deliverable needs a name and completion criteria.")
            key = spec.get("key") or f"d{index + 1}"
            if not isinstance(key, str) or not _KEY.fullmatch(key) or key in keys:
                raise AiclError("validation_failed", "Deliverable identifiers must be unique short names.")
            keys.add(key)
            criteria = spec.get("criteria")
            if not isinstance(criteria, list) or not 1 <= len(criteria) <= 12:
                raise AiclError("validation_failed", "Define one to twelve completion criteria for each deliverable.")
            scenario = spec.get("validation_scenario", "pass")
            if scenario not in ("pass", "needs_work_once"):
                raise AiclError("validation_failed", "Choose a supported validation example.")
            purchase = spec.get("purchase_required", False)
            if type(purchase) is not bool:
                raise AiclError("validation_failed", "Purchase dependency must be true or false.")
            normalized.append({"key": key, "name": self._text(spec.get("name"), "Deliverable name", 120),
                "description": self._text(spec.get("description", ""), "Expected content", 2000, optional=True),
                "criteria": [self._text(c, "Completion criterion", 500) for c in criteria],
                "purchase_required": purchase, "validation_scenario": scenario})
        if scenario_id == SCENARIO:
            if keys != {"campaign_plan", "ad_creative", "performance_report"}:
                raise AiclError("validation_failed", "The PocketPlan example needs its campaign plan, ad creative and performance report.")
            if any(spec["purchase_required"] for spec in normalized):
                raise AiclError("validation_failed", "PocketPlan outputs exist independently of campaign purchase approval.")
        return {"scenario": scenario_id, "goal": goal, "inputs": inputs, "deliverables": normalized, "cadence": cadence, "timezone": timezone}

    def _next_due(self, config, after):
        local = after.astimezone(ZoneInfo(config["timezone"]))
        if config["cadence"] == "hourly":
            # UTC stepping avoids duplicate/nonexistent local hours around DST.
            next_time = after.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_time = local.replace(hour=9, minute=0, second=0, microsecond=0)
            if next_time <= local:
                next_time += timedelta(days=1)
        return to_iso(next_time)

    def save_config(self, auth, instance_id, data, expected_version):
        normalized = self._normalize(data)
        if self.execution_mode == "render" and normalized["scenario"] != SCENARIO:
            raise AiclError("validation_failed", "This release runs the reviewed PocketPlan marketing agent. Choose the app marketing example before saving.")
        if type(expected_version) is not int or expected_version < 1:
            raise AiclError("validation_failed", "A configuration version is required.")
        with self.db.transaction() as conn:
            current = self._config(conn, auth, instance_id)
            if current["version"] != expected_version:
                raise AiclError("conflict", "Configuration changed. Reload before saving.", current_version=current["version"])
            now = to_iso(self.clock.now())
            version = expected_version + 1
            next_due = current["next_due"]
            if current["enabled"] and (normalized["cadence"], normalized["timezone"]) != (current["cadence"], current["timezone"]):
                anchor = max(self.clock.now(), from_iso(current["demo_time"]) if current["demo_time"] else self.clock.now())
                next_due = self._next_due(normalized, anchor)
            conn.execute("INSERT INTO mock_workflow_config (instance_id,data_json,version,updated_at) VALUES (?,?,?,?) "
                         "ON CONFLICT(instance_id) DO UPDATE SET data_json=excluded.data_json,version=excluded.version,updated_at=excluded.updated_at",
                         (instance_id, _canonical(normalized), version, now))
            if next_due:
                conn.execute("UPDATE mock_workflow_config SET next_due=? WHERE instance_id=?", (next_due, instance_id))
            self.commerce._event(conn, auth, instance_id, "commerce.policy_changed", action="workflow_configured", version=version)
            return self._config(conn, auth, instance_id)

    def schedule(self, auth, instance_id, enabled, expected_version=None, expected_instance_version=None):
        if type(enabled) is not bool:
            raise AiclError("validation_failed", "Enabled must be true or false.")
        with self.db.transaction() as conn:
            config = self._config(conn, auth, instance_id)
            for supplied, actual in ((expected_version, config["version"]), (expected_instance_version, config["instance_version"])):
                if supplied is not None and (type(supplied) is not int or supplied != actual):
                    raise AiclError("conflict", "Agent or schedule settings changed. Reload before changing the schedule.", current_version=config["version"])
            if not config["saved"]:
                raise AiclError("validation_failed", "Save goals and deliverables before enabling the schedule.")
            # Idempotent enable must not undo a separate AICL pause in another tab.
            if config["enabled"] == enabled:
                return config
            if enabled:
                self._require_demo_active(conn, auth)
                if self.execution_mode == "render" and (config.get("scenario") != SCENARIO or self.inference is None):
                    raise AiclError("validation_failed", "Render scheduling requires the reviewed PocketPlan marketing configuration and enabled model inference.")
                inst = self._instance(conn, auth, instance_id)
                if inst["lifecycle"] in ("draft", "paused"):
                    SqliteInstanceOperations(self.db, self.clock).set_lifecycle(
                        auth, instance_id, inst["version"], "activate" if inst["lifecycle"] == "draft" else "resume")
                self.commerce._controls(conn, auth, instance_id)
            anchor = max(self.clock.now(), from_iso(config["demo_time"]) if config["demo_time"] else self.clock.now())
            next_due = self._next_due(config, anchor) if enabled else config["next_due"]
            if enabled and self.execution_mode == "render" and config["next_due"] is None and conn.execute(
                    "SELECT 1 FROM judge_demo_workspace WHERE owner_id=?", (auth.owner_id,)).fetchone():
                # Only the first activation starts at the next scheduler tick.
                # Persisted next_due survives pause/resume, preventing toggles
                # from becoming a manual-run shortcut around the saved cadence.
                next_due = to_iso(self.clock.now())
            conn.execute("UPDATE mock_workflow_config SET enabled=?,next_due=?,updated_at=?,last_outcome=?,version=version+1 WHERE instance_id=?",
                         (int(enabled), next_due, to_iso(self.clock.now()), "Scheduled" if enabled else "Paused", instance_id))
            self.commerce._event(conn, auth, instance_id, "commerce.policy_changed", action="schedule_enabled" if enabled else "schedule_paused", enabled=enabled)
            return self._config(conn, auth, instance_id)

    def _latest(self, conn, run_id):
        return conn.execute("SELECT * FROM mock_workflow_deliverable WHERE workflow_run_id=? ORDER BY version DESC LIMIT 1", (run_id,)).fetchone()

    def _current_purchase(self, conn, job):
        return conn.execute("SELECT * FROM mock_commerce_purchase WHERE run_id=?", (job["commerce_run_id"],)).fetchone()

    def _candidate_content(self, snapshot, spec, feedback, failed):
        """A few original writing fixtures, not interpretation of arbitrary criteria."""
        if snapshot.get("scenario") == SCENARIO:
            return ad_content(snapshot, spec, feedback, failed)
        goal, inputs = snapshot["goal"], snapshot["inputs"]
        context = " ".join((goal, inputs, spec["description"])).lower()
        kind = spec["name"].lower()
        parts = [spec["name"], f"Goal: {goal}"]
        if inputs:
            parts.append(f"Working context\n{inputs}")
        if "garden" in context:
            parts.extend([
                "Headline\nA shared garden starts with one shared hour.",
                "Community invitation\nBring a neighbor and help shape a garden everyone can use. "
                "Start with one shared session to choose priorities, divide small jobs and make room for new volunteers. "
                "No gardening experience is needed to help with planning, welcoming people or keeping the group informed.",
                "Proposed work plan\n1. Ask residents which activities they would join and when they are available.\n"
                "2. Agree on a first session and assign one coordinator to each small task.\n"
                "3. Share a short sign-up message with the time commitment and a contact person.\n"
                "4. After the session, record what was done and invite suggestions for the next one.",
            ])
            next_action = "Ask the owner to choose the first session and confirm the volunteer contact before sharing the invitation."
        elif any(word in kind for word in ("copy", "newsletter", "post", "message", "pitch")):
            parts.extend([
                "Headline\nOne useful change. One clear next step.",
                f"Draft message\nOur focus is simple: {goal.rstrip('.')}. "
                "We are starting with a small, practical first step and inviting feedback before expanding it. "
                "Take a look at the proposal, tell us what would make it useful to you, and help choose what happens next.",
                "Publishing checklist\nConfirm the intended audience, choose one place to share the message, "
                "and nominate someone to collect responses. Keep the first message focused on a single invitation.",
            ])
            next_action = "Choose the invitation link or contact, confirm the audience and approve the draft message for use."
        else:
            parts.extend([
                "Recommendation\nStart with one small, reviewable outcome and use the owner's feedback to decide the next step. "
                "Keep the first cycle narrow enough that its result can be inspected without a separate explanation.",
                f"Scope for this cycle\n{spec['description'] or goal}",
                "Action plan\n1. Confirm the intended reader and the decision this output should support.\n"
                "2. Prepare a concise first draft with a recommendation and a practical next action.\n"
                "3. Review the draft against the configured requirements and flag unresolved details.\n"
                "4. Ask the owner to accept the result or identify a specific revision for the next cycle.",
                "Owner decision\nApprove the proposed scope, or identify the one change that would make this result more useful.",
            ])
            next_action = "Confirm the proposed scope and assign the first action before the next scheduled cycle."
        if feedback:
            lower = feedback.lower()
            if any(word in lower for word in ("deadline", "date", "sign-up")):
                revision = ("Proposed deadline: close sign-ups at 5 p.m. on the Friday before the next session. "
                            "The coordinator confirms attendance and shares the final task list afterward. "
                            "The owner must confirm this proposed timing before it is used.")
                next_action = "Confirm the proposed sign-up deadline and coordinator, then add both to the invitation."
            elif any(word in lower for word in ("short", "concise", "brief")):
                revision = f"Short version: {goal.rstrip('.')}. Start with one agreed action, review the result, and decide what to improve next."
                next_action = "Review the shorter version and select one invitation or action to retain."
            elif any(word in lower for word in ("budget", "cost", "spend")):
                revision = ("Proposed spending constraint: use existing resources first. List any additional resource separately, "
                            "with its purpose and quoted price, and wait for the owner's purchase decision before relying on it.")
                next_action = "Review the existing-resource option before considering a new purchase request."
            else:
                revision = ("Revised decision block: separate the recommendation from its implementation. "
                            "The owner first selects the smallest useful outcome; the next action then names its coordinator, "
                            "required input and review point. Any unresolved detail stays open for owner confirmation.")
                next_action = "Review the new decision block against the requested change before accepting this version."
            parts.extend([f"Owner change request\n{feedback}", "Proposed revision\n" + revision])
        if not failed:
            parts.append("Next action\n" + next_action)
        else:
            parts.append("Unfinished draft\nThe final review step is intentionally missing in this example; a correction is queued.")
        parts.append("Scripted demo draft. Proposed details and completion checks require owner review.")
        return "\n\n".join(parts)

    def _produce(self, conn, auth, job, *, already_charged=False):
        self.commerce._controls(conn, auth, job["instance_id"])
        latest = self._latest(conn, job["id"])
        version = latest["version"] + 1 if latest else 1
        if version > _MAX_VERSIONS:
            raise AiclError("denied", "This example has reached its five-version limit. Configure a new job to change scope.", reason="revision_limit")
        snapshot, spec = json.loads(job["config_json"]), json.loads(job["spec_json"])
        if self.inference and uses_model(snapshot, spec):
            self.inference.stage(conn, auth, job, version, latest["feedback"] if latest else "")
            return
        if not already_charged and not (self.inference and snapshot.get("scenario") == SCENARIO):
            self.commerce._charge_inference(conn, auth, job["instance_id"], job["commerce_run_id"], f"workflow-v{version}")
        failed = spec["validation_scenario"] == "needs_work_once" and version == 1
        criteria = [{"criterion": criterion, "passed": not (failed and index == len(spec["criteria"]) - 1),
                     "reason": "Demo fixture marked this check complete; no model or semantic validation ran." if not (failed and index == len(spec["criteria"]) - 1)
                     else "Demo fixture marked this criterion incomplete; correction is queued for the next scheduled occurrence."}
                    for index, criterion in enumerate(spec["criteria"])]
        content = self._candidate_content(snapshot, spec, latest["feedback"] if latest else "", failed)
        purchase = self._current_purchase(conn, job)
        if purchase and purchase["state"] == "paid" and snapshot.get("scenario") != SCENARIO:
            content += "\n\nApproved resource: " + json.loads(purchase["fulfillment_json"])["name"]
        state, now = ("needs_work" if failed else "submitted"), to_iso(self.clock.now())
        conn.execute("INSERT INTO mock_workflow_deliverable (id,workflow_run_id,version,content,criteria_json,state,created_at) VALUES (?,?,?,?,?,?,?)",
                     (_id(), job["id"], version, content, _canonical(criteria), state, now))
        conn.execute("UPDATE mock_workflow_run SET state=?,blocked_reason=NULL,updated_at=? WHERE id=?", (state, now, job["id"]))
        conn.execute("UPDATE mock_commerce_run SET state='completed',output=?,updated_at=? WHERE id=?", (content, now, job["commerce_run_id"]))
        self.commerce._event(conn, auth, job["instance_id"], "commerce.run_completed", run_id=job["id"], action=state, version=version)

    def _continue(self, conn, auth, job):
        if self._ad_activate(conn, auth, job):
            return  # A campaign can start after funding; output already exists.
        if self._latest(conn, job["id"]):
            return  # Already claimed by another payment callback or scheduled occurrence.
        config = self._config(conn, auth, job["instance_id"])
        if not config["enabled"]:
            raise AiclError("denied", "Enable the agent schedule before continuing this waiting job.", reason="schedule_paused")
        purchase = self._current_purchase(conn, job)
        if not purchase or purchase["state"] != "paid" or not purchase["fulfillment_json"]:
            raise AiclError("denied", "Complete checkout and resource delivery before continuing.", reason="payment_incomplete")
        self._produce(conn, auth, job)

    def _record_block(self, conn, auth, job, error):
        reason = error.message
        conn.execute("UPDATE mock_workflow_run SET blocked_reason=?,updated_at=? WHERE id=?", (reason, to_iso(self.clock.now()), job["id"]))
        self.commerce._event(conn, auth, job["instance_id"], "commerce.denied", "denied", reason=error.extra.get("reason", error.error), run_id=job["id"], action="workflow_blocked")

    def advance(self, auth, instance_id, expected_due, *, defer_inference=False, config_snapshot=None, manage_schedule=True):
        with self.db.transaction() as conn:
            current = self._config(conn, auth, instance_id)
            config = config_snapshot or current
            existing = conn.execute("SELECT * FROM mock_workflow_occurrence WHERE instance_id=? AND scheduled_for=?", (instance_id, expected_due)).fetchone()
            if existing:
                occurrence = {**dict(existing), "replayed": True}
            else:
                if not current["enabled"]:
                    raise AiclError("denied", "Enable the schedule before advancing demo time.", reason="schedule_paused")
                if not isinstance(expected_due, str) or expected_due != config["next_due"]:
                    raise AiclError("conflict", "The next occurrence changed. Reload before advancing demo time.")
                now, occurrence_id = to_iso(self.clock.now()), _id()
                conn.execute("INSERT INTO mock_workflow_occurrence (id,instance_id,scheduled_for,config_version,state,created_at) VALUES (?,?,?,?,'processed',?)",
                             (occurrence_id, instance_id, expected_due, config["version"], now))
                if manage_schedule:
                    conn.execute("UPDATE mock_workflow_config SET demo_time=?,next_due=?,updated_at=? WHERE instance_id=?",
                                 (expected_due, self._next_due(config, from_iso(expected_due)), now, instance_id))
                else:
                    conn.execute("UPDATE mock_workflow_config SET demo_time=?,updated_at=? WHERE instance_id=?", (expected_due, now, instance_id))
                outcomes = []
                # First give existing work its next opportunity, retaining its original requirements.
                existing_jobs = conn.execute("SELECT * FROM mock_workflow_run WHERE instance_id=? ORDER BY rowid", (instance_id,)).fetchall()
                for job in existing_jobs:
                    if job["state"] not in ("waiting_purchase", "needs_work", "changes_requested", "inference_blocked", "inference_failed"):
                        continue
                    purchase = self._current_purchase(conn, job)
                    if job["state"] == "waiting_purchase" and purchase and purchase["state"] in ("declined", "cancelled"):
                        conn.execute("UPDATE mock_workflow_run SET state=?,blocked_reason=NULL,updated_at=? WHERE id=?", (purchase["state"], now, job["id"]))
                        continue
                    if job["state"] == "waiting_purchase" and (not purchase or purchase["state"] != "paid"):
                        continue
                    try:
                        with self.db.transaction():
                            if job["state"] == "waiting_purchase":
                                self._continue(conn, auth, job)
                            else:
                                self._produce(conn, auth, job)
                        outcomes.append("continued")
                    except AiclError as error:
                        self._record_block(conn, auth, job, error)
                        outcomes.append(str(error.message))
                if config.get("scenario") == SCENARIO:
                    outcomes.extend(self._advance_ads(conn, auth, config, occurrence_id, expected_due))
                for spec in ([] if config.get("scenario") == SCENARIO else config["deliverables"]):
                    pending = conn.execute("SELECT 1 FROM mock_workflow_run WHERE instance_id=? AND spec_key=? "
                                           "AND state IN ('waiting_purchase','needs_work','submitted','changes_requested')", (instance_id, spec["key"])).fetchone()
                    if pending:
                        continue
                    try:
                        with self.db.transaction():
                            reusable = conn.execute("SELECT 1 FROM mock_commerce_purchase WHERE instance_id=? AND state='paid' AND fulfillment_json IS NOT NULL AND json_extract(fulfillment_json,'$.kind') IS NOT 'prepaid_ad_credit' LIMIT 1", (instance_id,)).fetchone()
                            needs_purchase = spec["purchase_required"] and not reusable
                            brief = {"product_name": spec["name"], "audience": (config["inputs"] or "The agent owner")[:240], "goal": config["goal"][:600]}
                            commerce_run = self.commerce._start_workflow_run(conn, auth, instance_id, f"wf:{occurrence_id}:{spec['key']}", brief, purchase_required=needs_purchase)
                            run_id = _id()
                            snapshot = {key: config[key] for key in ("goal", "inputs", "deliverables", "cadence", "timezone", "version", "scenario")}
                            conn.execute("INSERT INTO mock_workflow_run (id,instance_id,occurrence_id,commerce_run_id,spec_key,config_version,config_json,spec_json,state,created_at,updated_at) "
                                         "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (run_id, instance_id, occurrence_id, commerce_run["id"], spec["key"], config["version"], _canonical(snapshot), _canonical(spec), "waiting_purchase" if needs_purchase else "running", now, now))
                            job = self._job(conn, auth, run_id)
                            if needs_purchase:
                                conn.execute("INSERT INTO mock_workflow_purchase (purchase_id,workflow_run_id) VALUES (?,?)", (commerce_run["purchase_id"], run_id))
                            else:
                                self._produce(conn, auth, job, already_charged=True)
                            outcomes.append("purchase requested" if needs_purchase else "output checked")
                    except AiclError as error:
                        outcomes.append(str(error.message))
                        self.commerce._event(conn, auth, instance_id, "commerce.denied", "denied", reason=error.extra.get("reason", error.error), action="scheduled_work_blocked")
                summary = "; ".join(outcomes) if outcomes else "Waiting for owner review or purchase decisions"
                conn.execute("UPDATE mock_workflow_config SET last_outcome=? WHERE instance_id=?", (summary, instance_id))
                conn.execute("UPDATE mock_workflow_occurrence SET reason=? WHERE id=?", (summary, occurrence_id))
                occurrence = dict(conn.execute("SELECT * FROM mock_workflow_occurrence WHERE id=?", (occurrence_id,)).fetchone()) | {"replayed": False}
        if self.inference and not defer_inference:
            dispatched = self.inference.drain(auth, instance_id)
            # Model outputs become available after the occurrence transaction.
            # Only then may the existing quote flow link submitted supporting
            # work. It still creates an owner request, never a payment approval.
            with self.db.transaction() as conn:
                config = self._config(conn, auth, instance_id)
                if (not occurrence["replayed"] or dispatched) and config["demo_time"] == expected_due and config["enabled"] and config.get("scenario") == SCENARIO:
                    try:
                        self.commerce._controls(conn, auth, instance_id)
                        self._advance_ads(conn, auth, config, occurrence["id"], expected_due)
                    except AiclError:
                        pass  # Results persist if owner controls changed during I/O.
            self.inference.drain(auth, instance_id)
        return self.overview(auth, instance_id) | {"occurrence": occurrence}

    def _resume_or_enqueue(self, conn, auth, job, *, retry_blocked=False):
        if self.execution_mode == "render":
            from aicl.render.service import RenderExecution
            RenderExecution(self).enqueue_continuation(conn, auth, job, retry_blocked=retry_blocked)
        else:
            self._continue(conn, auth, job)

    def review(self, auth, deliverable_id, decision, feedback, expected_version):
        if isinstance(deliverable_id, str) and deliverable_id.startswith("legacy:"):
            self.deliverable(auth, deliverable_id)
            raise AiclError("invalid_transition", "Earlier task results are read-only; configure completion criteria for future work.")
        if decision not in ("accept", "request_changes"):
            raise AiclError("validation_failed", "Choose Accept or Request changes.")
        feedback = self._text(feedback or "", "Review feedback", 2000, optional=decision == "accept")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM mock_workflow_deliverable WHERE id=?", (deliverable_id,)).fetchone()
            if not row:
                raise AiclError("not_found", "Deliverable not found.")
            job = self._job(conn, auth, row["workflow_run_id"])
            latest = self._latest(conn, job["id"])
            if type(expected_version) is not int or row["version"] != expected_version or latest["id"] != deliverable_id:
                raise AiclError("conflict", "This review applies to an older version. Open the latest output.")
            state = "accepted" if decision == "accept" else "changes_requested"
            if row["state"] == state and row["feedback"] == feedback:
                return self.deliverable(auth, deliverable_id)
            if row["state"] != "submitted" or not all(c["passed"] for c in json.loads(row["criteria_json"])):
                raise AiclError("invalid_transition", "Only a validated, submitted version can be reviewed.")
            if decision == "request_changes" and row["version"] >= _MAX_VERSIONS:
                raise AiclError("denied", "This example has reached its five-version limit. Configure a new job to change scope.", reason="revision_limit")
            now = to_iso(self.clock.now())
            conn.execute("UPDATE mock_workflow_deliverable SET state=?,feedback=?,reviewed_at=? WHERE id=?", (state, feedback, now, deliverable_id))
            conn.execute("UPDATE mock_workflow_run SET state=?,updated_at=? WHERE id=?", (state, now, job["id"]))
            self.commerce._event(conn, auth, job["instance_id"], "commerce.run_completed", run_id=job["id"], action=state, version=row["version"])
            return self.deliverable(auth, deliverable_id)

    def job_for_purchase(self, auth, purchase_id):
        with self.db.reader() as conn:
            self.commerce._owned_resource(conn, auth, "mock_commerce_purchase", purchase_id)
            link = conn.execute("SELECT workflow_run_id FROM mock_workflow_purchase WHERE purchase_id=?", (purchase_id,)).fetchone()
            return self._run_projection(conn, auth, self._job(conn, auth, link[0])) if link else None

    def set_continuation(self, auth, purchase_id, choice):
        if choice not in ("now", "schedule"):
            raise AiclError("validation_failed", "Choose Run now or Resume on schedule.")
        with self.db.transaction() as conn:
            purchase = self.commerce._owned_resource(conn, auth, "mock_commerce_purchase", purchase_id)
            link = conn.execute("SELECT workflow_run_id FROM mock_workflow_purchase WHERE purchase_id=?", (purchase_id,)).fetchone()
            if not link:
                raise AiclError("not_found", "This purchase is not part of a scheduled job.")
            job = self._job(conn, auth, link[0])
            if purchase["run_id"] != job["commerce_run_id"]:
                raise AiclError("conflict", "This proposal was replaced. Open the latest request.")
            if purchase["state"] in ("declined", "cancelled", "expired"):
                raise AiclError("invalid_transition", "Closed purchases cannot continue work.")
            conn.execute("UPDATE mock_workflow_run SET continuation=?,updated_at=? WHERE id=?", (choice, to_iso(self.clock.now()), job["id"]))
            self.commerce._event(conn, auth, job["instance_id"], "commerce.purchase_changed", purchase_id=purchase_id, run_id=job["id"], action="continue_" + choice)
            if choice == "now" and purchase["state"] == "paid":
                try:
                    with self.db.transaction():
                        self._resume_or_enqueue(conn, auth, self._job(conn, auth, job["id"]), retry_blocked=True)
                except AiclError as error:
                    self._record_block(conn, auth, job, error)
            return self._run_projection(conn, auth, self._job(conn, auth, job["id"]))

    def payment_completed(self, auth, order):
        order_id = order["id"] if isinstance(order, dict) else order
        with self.db.transaction() as conn:
            row = self.commerce._owned_resource(conn, auth, "mock_commerce_order", order_id)
            if not row["purchase_id"]:
                return None
            link = conn.execute("SELECT workflow_run_id FROM mock_workflow_purchase WHERE purchase_id=?", (row["purchase_id"],)).fetchone()
            if not link:
                return None
            job = self._job(conn, auth, link[0])
            if row["state"] == "completed" and job["continuation"] == "now" and row["purchase_id"] == (self._current_purchase(conn, job) or {})["id"]:
                try:
                    with self.db.transaction():
                        self._resume_or_enqueue(conn, auth, job)
                except AiclError as error:
                    self._record_block(conn, auth, job, error)
            return self._run_projection(conn, auth, self._job(conn, auth, job["id"]))

    def refresh_purchase(self, auth, purchase_id):
        with self.db.transaction() as conn:
            purchase = self.commerce._owned_resource(conn, auth, "mock_commerce_purchase", purchase_id)
            link = conn.execute("SELECT workflow_run_id FROM mock_workflow_purchase WHERE purchase_id=?", (purchase_id,)).fetchone()
            if not link:
                raise AiclError("not_found", "Scheduled purchase not found.")
            job = self._job(conn, auth, link[0])
            current = self._current_purchase(conn, job)
            if current["id"] != purchase_id:
                return self.commerce._purchase_projection(conn, current)
            if purchase["state"] == "paid" or purchase["state"] in ("declined", "cancelled"):
                raise AiclError("invalid_transition", "Only expired proposals can be refreshed.")
            if purchase["expires_at"] > to_iso(self.clock.now()):
                raise AiclError("invalid_transition", "This proposal is still current.")
            if self.commerce._payment_outstanding(conn, purchase_id):
                raise AiclError("denied", "Check the existing payment status before refreshing the proposal.", reason="reconciliation_pending")
            if purchase["state"] != "expired":
                self.commerce._end_purchase(conn, auth, purchase, "expired")
            source = self.commerce._owned_resource(conn, auth, "mock_commerce_run", job["commerce_run_id"])
            run = self.commerce._start_workflow_run(conn, auth, job["instance_id"], f"refresh:{purchase_id}", json.loads(source["brief_json"]), purchase_required=True, charge=False, offer_id=json.loads(purchase["quote_json"]).get("offer_id"))
            conn.execute("UPDATE mock_workflow_run SET commerce_run_id=?,continuation='schedule',blocked_reason=NULL,updated_at=? WHERE id=?", (run["id"], to_iso(self.clock.now()), job["id"]))
            conn.execute("INSERT INTO mock_workflow_purchase (purchase_id,workflow_run_id) VALUES (?,?)", (run["purchase_id"], job["id"]))
            return run["purchase"]

    def _run_projection(self, conn, auth, row):
        inst = self._instance(conn, auth, row["instance_id"])
        purchase = self._current_purchase(conn, row)
        snapshot, spec = json.loads(row["config_json"]), json.loads(row["spec_json"])
        latest = self._latest(conn, row["id"])
        occurrence = conn.execute("SELECT scheduled_for FROM mock_workflow_occurrence WHERE id=?", (row["occurrence_id"],)).fetchone()
        commerce_ids = [row["commerce_run_id"]] + [r[0] for r in conn.execute(
            "SELECT p.run_id FROM mock_commerce_purchase p JOIN mock_workflow_purchase w ON w.purchase_id=p.id WHERE w.workflow_run_id=?", (row["id"],))]
        marks = ",".join("?" for _ in set(commerce_ids))
        costs = conn.execute(f"SELECT COALESCE(SUM(inference_cost_micro_usd),0),COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0) FROM mock_commerce_run WHERE id IN ({marks})", tuple(set(commerce_ids))).fetchone()
        state = row["state"]
        blocked_reason = row["blocked_reason"]
        inference_attempt = None
        attempt = conn.execute("SELECT * FROM workflow_inference_attempt WHERE workflow_run_id=? ORDER BY rowid DESC LIMIT 1", (row["id"],)).fetchone()
        if attempt:
            attempt_state = attempt["state"]
            if attempt_state == "inflight" and self.clock.now() - from_iso(attempt["updated_at"]) >= timedelta(seconds=120):
                # Projection only: elapsed time cannot prove that a provider did
                # not charge. Keep the durable reservation and never resend.
                state, attempt_state = "inference_unknown", "unknown"
                blocked_reason = "The model request was interrupted or has not returned. Its outcome is unresolved; budget and credit remain reserved, and it will not be sent again."
            inference_attempt = {"id": attempt["id"], "provider": "openai", "model": attempt["model"], "state": attempt_state,
                                 "reserved_micro_usd": attempt["max_cost_micro_usd"] if attempt["state"] in ("inflight", "unknown") else 0}
        if state == "waiting_purchase" and purchase and purchase["state"] in ("declined", "cancelled", "expired"):
            state = purchase["state"]
        execution = conn.execute("SELECT id,task_run_id,state,created_at,started_at,completed_at,reason FROM render_dispatch WHERE occurrence_id=? OR continuation_run_id=? ORDER BY created_at DESC LIMIT 1", (row["occurrence_id"], row["id"])).fetchone()
        return {"id": row["id"], "instance_id": row["instance_id"], "agent_name": inst["name"],
                "execution": dict(execution) if execution else None,
                "goal": snapshot["goal"], "deliverable_name": spec["name"], "spec_key": row["spec_key"],
                "deliverable_description": spec["description"], "completion_criteria": spec["criteria"],
                "supporting_work": spec.get("source_work", []),
                "timezone": snapshot["timezone"],
                "state": state, "scheduled_for": occurrence[0], "created_at": row["created_at"],
                "config_version": row["config_version"], "config_snapshot": snapshot,
                "purchase_id": purchase["id"] if purchase else None, "continuation": row["continuation"],
                "purchase": self.commerce._purchase_projection(conn, purchase) if purchase else None,
                "latest_deliverable": {"id": latest["id"], "name": spec["name"], "state": latest["state"],
                                       "version": latest["version"]} if latest else None,
                "blocked_reason": blocked_reason, "inference_attempt": inference_attempt, "inference_cost_micro_usd": costs[0],
                "input_tokens": costs[1], "output_tokens": costs[2]}

    def _purchase_review_projection(self, conn, auth, row):
        """Link a quote to the work snapshot which requested it, never today's config."""
        inst = self._instance(conn, auth, row["instance_id"])
        item = self.commerce._purchase_projection(conn, row)
        job_row = self._job(conn, auth, row["workflow_run_id"]) if row["workflow_run_id"] else None
        job = self._run_projection(conn, auth, job_row) if job_row else None
        source_job, legacy_source = None, None
        source_work = []
        if job:
            source_job = {key: job[key] for key in (
                "id", "scheduled_for", "created_at", "config_version", "timezone", "deliverable_name",
                "deliverable_description", "completion_criteria", "state", "latest_deliverable", "supporting_work")}
            spec = json.loads(job_row["spec_json"])
            reason = ("This job’s saved requirements call for a purchased resource before completing the output."
                      if spec["purchase_required"] else "This request is linked to the saved job requirements.")
            if job["config_snapshot"].get("scenario") == SCENARIO:
                campaign_quote = item["quote"].get("campaign", {})
                reason = campaign_quote.get("rationale", "This bounded advertising test buys distribution for the prepared PocketPlan creative.")
                source_work = spec.get("source_work", [])
        else:
            run = self.commerce._owned_resource(conn, auth, "mock_commerce_run", row["run_id"])
            brief = json.loads(run["brief_json"])
            legacy_source = {"id": run["id"], "created_at": run["created_at"], "state": run["state"],
                             "goal": brief.get("goal", ""), "brief": brief,
                             "deliverable_id": "legacy:" + run["id"] if run["state"] == "completed" and run["output"] else None}
            reason = "Requested by an earlier manual task. Its saved brief is available below."
        item.update({
            "agent_name": inst["name"], "workflow_run_id": job["id"] if job else None,
            "deliverable_name": job["deliverable_name"] if job else legacy_source["brief"].get("product_name", "Earlier task"),
            "goal": job["goal"] if job else legacy_source["goal"],
            "source_job": source_job, "source_work": source_work, "legacy_source": legacy_source, "purchase_reason": reason,
            "continuation": job["continuation"] if job else "schedule",
            "blocked_reason": job["blocked_reason"] if job else None,
            "workflow_state": job["state"] if job else None,
            "next_due": self._config(conn, auth, row["instance_id"])["next_due"],
            "amount_minor": row["amount_minor"], "created_at": row["created_at"],
            "expired": row["expires_at"] <= to_iso(self.clock.now()) and row["state"] in ("awaiting_approval", "awaiting_checkout"),
            "current_proposal": not job or job_row["commerce_run_id"] == row["run_id"],
        })
        return item

    def job(self, auth, run_id):
        """Read one owned scheduled job, including replaced quotes and output versions."""
        with self.db.reader() as conn:
            row = self._job(conn, auth, run_id)
            result = self._run_projection(conn, auth, row)
            result["purchases"] = [self._purchase_review_projection(conn, auth, purchase) for purchase in conn.execute(
                "SELECT p.*, w.workflow_run_id FROM mock_commerce_purchase p "
                "JOIN mock_workflow_purchase w ON w.purchase_id=p.id WHERE w.workflow_run_id=? ORDER BY p.rowid DESC",
                (run_id,))]
            result["deliverables"] = [self._deliverable_projection(conn, auth, output) for output in conn.execute(
                "SELECT * FROM mock_workflow_deliverable WHERE workflow_run_id=? ORDER BY version DESC", (run_id,))]
            return result

    def _deliverable_projection(self, conn, auth, row):
        job = self._job(conn, auth, row["workflow_run_id"])
        inst = self._instance(conn, auth, job["instance_id"])
        snapshot, spec = json.loads(job["config_json"]), json.loads(job["spec_json"])
        latest = self._latest(conn, job["id"])
        return {"id": row["id"], "instance_id": job["instance_id"], "agent_name": inst["name"],
                "run_id": job["id"], "spec_key": job["spec_key"], "name": spec["name"], "content": row["content"],
                "state": row["state"], "version": row["version"], "criteria": json.loads(row["criteria_json"]),
                "inference": provenance(conn, job["id"], row["version"]),
                "goal": snapshot["goal"], "created_at": row["created_at"], "reviewed_at": row["reviewed_at"],
                "feedback": row["feedback"], "config_version": job["config_version"],
                "config_snapshot": snapshot, "latest": latest["id"] == row["id"], "legacy": False,
                "next_due": self._config(conn, auth, job["instance_id"])["next_due"]}

    def _legacy_deliverable(self, conn, auth, row):
        inst = self._instance(conn, auth, row["instance_id"])
        brief = json.loads(row["brief_json"])
        return {"id": "legacy:" + row["id"], "instance_id": row["instance_id"], "agent_name": inst["name"],
                "run_id": row["id"], "spec_key": None, "name": "Completed task: " + brief.get("product_name", inst["name"]),
                "content": row["output"], "state": "completed", "version": 1, "criteria": [],
                "goal": brief.get("goal", ""), "created_at": row["updated_at"], "reviewed_at": None,
                "feedback": "", "config_version": None, "config_snapshot": {"goal": brief.get("goal", ""), "brief": brief},
                "latest": True, "legacy": True, "next_due": None}

    def deliverable(self, auth, deliverable_id):
        with self.db.reader() as conn:
            if isinstance(deliverable_id, str) and deliverable_id.startswith("legacy:"):
                row = self.commerce._owned_resource(conn, auth, "mock_commerce_run", deliverable_id.removeprefix("legacy:"))
                linked = conn.execute("SELECT 1 FROM mock_workflow_run WHERE commerce_run_id=? UNION SELECT 1 FROM mock_workflow_purchase w JOIN mock_commerce_purchase p ON p.id=w.purchase_id WHERE p.run_id=?", (row["id"], row["id"])).fetchone()
                if linked or row["state"] != "completed" or not row["output"]:
                    raise AiclError("not_found", "Completed task output not found.")
                result = self._legacy_deliverable(conn, auth, row)
                return result | {"versions": [dict(result)]}
            row = conn.execute("SELECT * FROM mock_workflow_deliverable WHERE id=?", (deliverable_id,)).fetchone()
            if not row:
                raise AiclError("not_found", "Deliverable not found.")
            result = self._deliverable_projection(conn, auth, row)
            result["versions"] = [self._deliverable_projection(conn, auth, item) for item in conn.execute(
                "SELECT * FROM mock_workflow_deliverable WHERE workflow_run_id=? ORDER BY version DESC", (row["workflow_run_id"],))]
            return result

    def overview(self, auth, instance_id=None):
        self._auth(auth)
        with self.db.reader() as conn:
            if instance_id:
                self._instance(conn, auth, instance_id)
            instances = conn.execute("SELECT * FROM agent_instance WHERE tenant_id=? AND owner_id=? AND (? IS NULL OR id=?) ORDER BY rowid DESC",
                                     (auth.tenant_id, auth.owner_id, instance_id, instance_id)).fetchall()
            agents, runs, purchases, deliverables, cost_rows, events, campaigns = [], [], [], [], [], [], []
            totals = {"service_balance_micro_usd": 0, "inference_cost_micro_usd": 0, "funding_micro_usd": 0,
                      "purchase_spent_minor": 0, "purchase_held_minor": 0, "run_count": 0,
                      "submitted_count": 0, "accepted_count": 0, "needs_work_count": 0,
                      "ad_funding_minor": 0, "ad_consumed_minor": 0, "ad_remaining_minor": 0,
                      "compute_estimate_micro_usd": 0}
            for inst in instances:
                iid, name = inst["id"], inst["name"]
                config = self._config(conn, auth, iid)
                ad_campaigns = [self._ad_campaign_projection(conn, auth, row) for row in conn.execute(
                    "SELECT * FROM mock_ad_campaign WHERE instance_id=? ORDER BY rowid", (iid,))]
                campaigns.extend(ad_campaigns)
                for campaign in ad_campaigns:
                    for field, target in (("funding_minor", "ad_funding_minor"), ("consumed_minor", "ad_consumed_minor"), ("remaining_minor", "ad_remaining_minor")):
                        totals[target] += campaign[field]
                jobs = conn.execute("SELECT * FROM mock_workflow_run WHERE instance_id=? ORDER BY rowid DESC", (iid,)).fetchall()
                runs.extend(self._run_projection(conn, auth, job) for job in jobs)
                outputs = [self._deliverable_projection(conn, auth, row) for row in conn.execute(
                    "SELECT d.* FROM mock_workflow_deliverable d JOIN mock_workflow_run w ON d.workflow_run_id=w.id WHERE w.instance_id=? ORDER BY d.rowid DESC", (iid,))]
                legacy_outputs = [self._legacy_deliverable(conn, auth, row) for row in conn.execute(
                    "SELECT r.* FROM mock_commerce_run r WHERE r.instance_id=? AND r.state='completed' AND r.output IS NOT NULL "
                    "AND NOT EXISTS (SELECT 1 FROM mock_workflow_run w WHERE w.commerce_run_id=r.id) "
                    "AND NOT EXISTS (SELECT 1 FROM mock_workflow_purchase w JOIN mock_commerce_purchase p ON p.id=w.purchase_id WHERE p.run_id=r.id) ORDER BY r.rowid DESC", (iid,))]
                outputs.extend(legacy_outputs)
                outputs.sort(key=lambda item: item["created_at"], reverse=True)
                deliverables.extend(outputs)
                all_purchases = conn.execute("SELECT p.*, w.workflow_run_id FROM mock_commerce_purchase p LEFT JOIN mock_workflow_purchase w ON w.purchase_id=p.id WHERE p.instance_id=? ORDER BY p.rowid DESC", (iid,)).fetchall()
                for purchase in all_purchases:
                    purchases.append(self._purchase_review_projection(conn, auth, purchase))
                policy = self.commerce._policy(conn, iid)
                balance = self.commerce._balance(conn, iid)
                totals["service_balance_micro_usd"] += balance
                totals["purchase_spent_minor"] += policy["spent_minor"]
                totals["purchase_held_minor"] += policy["held_minor"]
                for ledger in conn.execute("SELECT * FROM mock_commerce_ledger WHERE instance_id=? ORDER BY rowid DESC", (iid,)):
                    funding = ledger["kind"] == "service_topup"
                    totals["funding_micro_usd" if funding else "inference_cost_micro_usd"] += abs(ledger["delta_micro_usd"])
                    cost_rows.append({"id": ledger["id"], "created_at": ledger["created_at"], "agent_name": name, "instance_id": iid,
                                      "category": "Service funding" if funding else "Inference usage", "amount_usd": abs(ledger["delta_micro_usd"]) / 1_000_000,
                                      "status": "Recorded", "run_id": ledger["reference"].split(":")[1] if not funding else None})
                for purchase in all_purchases:
                    if purchase["quota_state"] in ("held", "spent"):
                        ads = bool(json.loads(purchase["quote_json"]).get("campaign"))
                        cost_rows.append({"id": purchase["id"], "created_at": purchase["created_at"], "agent_name": name, "instance_id": iid,
                                          "category": ("Ad funding" if ads else "Merchant purchase") if purchase["quota_state"] == "spent" else "Purchase reservation",
                                          "amount_usd": purchase["amount_minor"] / 100, "status": purchase["state"],
                                          "run_id": purchase["workflow_run_id"] or purchase["run_id"]})
                for runtime in conn.execute("SELECT u.*,d.task_run_id,d.occurrence_id FROM render_compute_usage u JOIN render_dispatch d ON d.id=u.dispatch_id WHERE u.instance_id=? ORDER BY u.created_at DESC", (iid,)):
                    totals["compute_estimate_micro_usd"] += runtime["cost_micro_usd"]
                    source_job = conn.execute("SELECT id FROM mock_workflow_run WHERE occurrence_id=? ORDER BY rowid LIMIT 1", (runtime["occurrence_id"],)).fetchone()
                    cost_rows.append({"id": runtime["dispatch_id"], "created_at": runtime["created_at"], "agent_name": name,
                                      "instance_id": iid, "category": "Render compute estimate", "amount_usd": runtime["cost_micro_usd"] / 1_000_000,
                                      "status": "Estimated runtime", "run_id": source_job[0] if source_job else None})
                for event in conn.execute("SELECT * FROM audit_event WHERE tenant_id=? AND owner_id=? AND instance_id=? ORDER BY seq DESC", (auth.tenant_id, auth.owner_id, iid)):
                    details = json.loads(event["details"])
                    events.append({"id": event["id"], "occurred_at": event["occurred_at"], "event_type": event["event_type"],
                                   "action": details.get("action", event["event_type"].replace(".", " ").replace("_", " ")),
                                   "instance_id": iid, "agent_name": name, "run_id": details.get("run_id"),
                                   "purchase_id": details.get("purchase_id"), "reason": event["reason"], "outcome": event["outcome"]})
                pending_count = sum(p["state"] in ("awaiting_approval", "awaiting_checkout", "payment_pending") for p in all_purchases)
                agents.append({"id": iid, **config, "balance_micro_usd": balance, "pending_purchase_count": pending_count,
                               "latest_deliverable": outputs[0] if outputs else None, "lifecycle": inst["lifecycle"], "gated_reason": inst["gated_reason"]})
            totals["run_count"] = len(runs)
            for state in ("submitted", "accepted", "needs_work"):
                totals[state + "_count"] = sum(item["latest"] and item["state"] == state for item in deliverables)
            return {"mode": "local_simulation", "payment_transport": self.commerce.payment_transport,
                    "agents": agents, "runs": runs, "purchases": purchases, "campaigns": campaigns,
                    "deliverables": deliverables, "events": sorted(events, key=lambda item: item["occurred_at"], reverse=True),
                    "totals": totals, "cost_rows": sorted(cost_rows, key=lambda item: item["created_at"], reverse=True)}

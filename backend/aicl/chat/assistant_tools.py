"""Owner-assistant reads and proposals; only the owner confirmation route commits.

Model tools cannot activate work, change budgets, approve purchases or access
credentials. Proposal versions bind the owner's button click to reviewed data.
"""

from __future__ import annotations

import json
import unicodedata
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aicl.control.errors import AiclError
from aicl.creation import service as creation
from aicl.creation.models import CreateInstanceRequest
from aicl.db import to_iso
from aicl.workflow.ad_scenario import SCENARIO
from aicl.workflow.factory import workflow_service


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Inspect(_Input):
    instance_id: str = Field(min_length=1, max_length=80)


class _Deliverable(_Input):
    key: Literal["campaign_plan", "ad_creative", "performance_report"]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=2000)
    criteria: list[str] = Field(min_length=1, max_length=12)


class _Create(_Input):
    name: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1, max_length=2000)
    inputs: str = Field(max_length=4000)
    cadence: Literal["hourly", "daily"]
    timezone: str = Field(min_length=1, max_length=80)
    deliverables: list[_Deliverable] = Field(min_length=3, max_length=3)
    budget_notes: str = Field(max_length=1000)


class _Schedule(_Inspect):
    enabled: bool


_TOOLS = {
    "get_supported_capabilities": (_Input, "Read the supported worker, limitations and owner-only controls before interviewing or proposing an agent."),
    "list_agents": (_Input, "List up to 10 of this owner's agents with status and workflow links."),
    "inspect_agent": (_Inspect, "Read an owned agent's saved configuration, limits, credit, recent work, deliverables and purchase requests. This never runs work."),
    "save_agent_proposal": (_Create, "Prepare or revise a reviewed PocketPlan app-marketing draft for owner review. Use only when the owner wants this supported workflow; do not substitute it for arbitrary work. Requires campaign_plan, ad_creative and performance_report. Budget notes are informational. Does not create or activate an agent."),
    "validate_agent_proposal": (_Input, "Validate the current proposal and explain the owner confirmation and remaining setup steps; does not commit."),
    "propose_schedule_change": (_Schedule, "Prepare an exact pause/enable schedule change for an owned agent. Only an owner confirmation button applies it; this tool never runs or schedules work."),
}


def _clip(value, length=300):
    # Bound serialized JSON too: a single Unicode character may escape to 12 bytes.
    result, size = [], 0
    for char in str(value or "")[:length]:
        size += len(json.dumps(char, ensure_ascii=True)) - 2
        if size > length:
            break
        result.append(char)
    return "".join(result)


def _bounded_inspection(result):
    """Keep tool context small even with unusually verbose saved configuration."""
    def size():
        return len(json.dumps(result, ensure_ascii=True))
    # Counts and direct Audit links survive truncation.
    for key in ("inputs", "goal"):
        if size() > 3800:
            result["workflow"][key] = _clip(result["workflow"][key], 80)
    for key in ("recent_runs", "recent_deliverables", "recent_purchases"):
        while size() > 3800 and len(result[key]) > 1:
            result[key].pop()
    while size() > 3800 and result["workflow"]["deliverables"]:
        result["workflow"]["deliverables"].pop()
    return result


class AssistantTools:
    def __init__(self, ctx, auth, session_id):
        self.ctx, self.auth, self.session_id = ctx, auth, session_id
        self.db, self.clock = ctx.db, ctx.clock
        self.workflow = workflow_service(ctx)
        with self.db.reader() as conn:
            self._session(conn)

    def _session(self, conn):
        if self.auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "Sign in to continue.")
        row = conn.execute("SELECT id FROM assistant_session WHERE id=? AND tenant_id=? AND owner_id=?",
                           (self.session_id, self.auth.tenant_id, self.auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Assistant conversation not found.")

    def schemas(self):
        return [{"name": name, "description": description, "parameters": model.model_json_schema()}
                for name, (model, description) in _TOOLS.items()]

    def invoke(self, name, args):
        if name not in _TOOLS:
            raise AiclError("denied", "This action is not available to the assistant.")
        try:
            payload = _TOOLS[name][0].model_validate(args)
        except ValidationError:
            raise AiclError("validation_failed", "Supply only the documented fields and types for this tool.") from None
        with self.db.reader() as conn:
            self._session(conn)
        return getattr(self, "_" + name)(**payload.model_dump())

    def _get_supported_capabilities(self):
        live = self.ctx.settings.inference_mode == "openai"
        return {
            "worker": {"id": SCENARIO, "name": "Reviewed PocketPlan app-marketing worker",
                       "purpose": "Plan and evaluate a bounded advertising campaign for the PocketPlan mobile app.",
                       "deliverable_keys": ["campaign_plan", "ad_creative", "performance_report"],
                       "model_generation": ["campaign_plan", "performance_report"] if live else [],
                       "inference_mode": "openai" if live else "fixture",
                       "limitations": "Ad creative, advertising delivery and metrics remain scenario data. Arbitrary agents, live ads and custom tools are not supported by this worker."},
            "schedule": {"cadences": ["hourly", "daily"], "daily_time": "09:00 in the configured timezone"},
            "creation": "An owner-confirmed proposal creates a draft with inference permission only, zero budgets, no funding and a disabled schedule.",
            "owner_only": ["Funding checkout", "Budget and permission changes", "Purchase approval", "Applying schedule proposals"],
            "generic_workflows": "Existing generic workflows use fixtures; the assistant does not create or promise a general-purpose autonomous worker.",
        }

    def _list_agents(self):
        with self.db.reader() as conn:
            rows = conn.execute("SELECT id,name,lifecycle,gated_reason,version FROM agent_instance WHERE tenant_id=? AND owner_id=? ORDER BY rowid DESC LIMIT 11",
                                (self.auth.tenant_id, self.auth.owner_id)).fetchall()
            return {"agents": [{**dict(row), "name": _clip(row["name"], 80),
                                "url": f"/instances/{row['id']}/workflow"} for row in rows[:10]],
                    "has_more": len(rows) > 10, "workspace_url": "/workspace"}

    def _inspect_agent(self, instance_id):
        with self.db.reader() as conn:
            inst = self.workflow._instance(conn, self.auth, instance_id)
            config = self.workflow._config(conn, self.auth, instance_id)
            snapshot = creation.read_instance_snapshot_conn(conn, self.auth, instance_id, clock=self.clock)
            jobs = conn.execute("SELECT * FROM mock_workflow_run WHERE instance_id=? ORDER BY rowid DESC LIMIT 3", (instance_id,)).fetchall()
            runs = []
            for row in jobs:
                item = self.workflow._run_projection(conn, self.auth, row)
                latest = item["latest_deliverable"]
                attempt = item["inference_attempt"]
                runs.append({key: item[key] for key in ("id", "state", "scheduled_for", "inference_cost_micro_usd", "input_tokens", "output_tokens")} |
                            {"latest_deliverable": {key: latest[key] for key in ("id", "state", "version")} if latest else None,
                             "inference_attempt": {key: attempt[key] for key in ("state", "model", "reserved_micro_usd")} if attempt else None,
                             "deliverable_name": _clip(item["deliverable_name"], 80), "blocked_reason": _clip(item["blocked_reason"], 160),
                             "url": f"/audit/jobs/{row['id']}"})
            purchases = []
            for row in conn.execute("SELECT id,state,amount_minor,quote_json,run_id FROM mock_commerce_purchase WHERE instance_id=? ORDER BY rowid DESC LIMIT 3", (instance_id,)):
                quote = json.loads(row["quote_json"])
                purchases.append({"id": row["id"], "state": row["state"], "amount_minor": row["amount_minor"],
                                  "item": _clip(quote.get("item_name"), 80), "currency": "USD",
                                  "source_run_id": row["run_id"], "url": f"/audit?view=purchases&instance_id={instance_id}"})
            outputs = [{key: row[key] for key in ("id", "state", "version", "created_at", "workflow_run_id")} |
                       {"name": _clip(json.loads(row["spec_json"])["name"], 80), "excerpt": _clip(row["content"], 120),
                        "url": f"/audit/deliverables/{row['id']}"} for row in conn.execute(
                "SELECT d.id,d.state,d.version,d.created_at,d.workflow_run_id,d.content,w.spec_json FROM mock_workflow_deliverable d JOIN mock_workflow_run w ON w.id=d.workflow_run_id WHERE w.instance_id=? ORDER BY d.rowid DESC LIMIT 3", (instance_id,))]
            from aicl.owner_requests.service import OwnerRequestService
            pending_requests = OwnerRequestService(self.workflow).list(self.auth, instance_id=instance_id)
            counts = {"runs": conn.execute("SELECT count(*) FROM mock_workflow_run WHERE instance_id=?", (instance_id,)).fetchone()[0],
                      "purchases": conn.execute("SELECT count(*) FROM mock_commerce_purchase WHERE instance_id=?", (instance_id,)).fetchone()[0],
                      "purchases_awaiting_approval": conn.execute("SELECT count(*) FROM mock_commerce_purchase WHERE instance_id=? AND state='awaiting_approval'", (instance_id,)).fetchone()[0],
                      "deliverables": conn.execute("SELECT count(*) FROM mock_workflow_deliverable d JOIN mock_workflow_run w ON w.id=d.workflow_run_id WHERE w.instance_id=?", (instance_id,)).fetchone()[0],
                      "deliverables_awaiting_review": conn.execute("SELECT count(*) FROM mock_workflow_deliverable d JOIN mock_workflow_run w ON w.id=d.workflow_run_id WHERE w.instance_id=? AND d.state='submitted'", (instance_id,)).fetchone()[0]}
            held = conn.execute("SELECT COALESCE(SUM(inference_micro_usd+compute_micro_usd),0) FROM budget_hold WHERE instance_id=? AND state IN ('held','unknown')", (instance_id,)).fetchone()[0]
            result = {"id": instance_id, "name": _clip(inst["name"], 100), "status": snapshot.status, "gated_reason": snapshot.gated_reason,
                    "version": snapshot.version, "capabilities": snapshot.capabilities,
                    "limits_micro_usd": {key: inst[key] for key in ("inference_daily_micro_usd", "inference_monthly_micro_usd", "compute_daily_micro_usd", "compute_monthly_micro_usd")},
                    "available_service_credit_micro_usd": self.workflow.commerce._balance(conn, instance_id),
                    "reserved_or_unknown_micro_usd": held, "purchase_policy": self.workflow.commerce._policy(conn, instance_id),
                    "workflow": {key: config[key] for key in ("scenario", "cadence", "timezone", "version", "saved", "enabled", "next_due")} |
                                {"goal": _clip(config["goal"], 200), "inputs": _clip(config["inputs"], 200),
                                 "deliverable_count": len(config["deliverables"]),
                                 "deliverables": [{"key": spec["key"], "name": _clip(spec["name"], 80),
                                                   "description": _clip(spec["description"], 80), "criteria_count": len(spec["criteria"]),
                                                   "criteria": [_clip(value, 80) for value in spec["criteria"][:2]]} for spec in config["deliverables"][:3]]},
                    "recent_runs": runs, "recent_purchases": purchases, "recent_deliverables": outputs,
                    "total_counts": {**counts, "requests_awaiting_response": len(pending_requests)},
                    "pending_requests": [{"id": r["id"], "kind": r["kind"], "title": _clip(r["title"], 100)} for r in pending_requests[:3]],
                    "requests_url": f"/requests?instance_id={instance_id}",
                    "url": f"/instances/{instance_id}/workflow", "audit_url": f"/audit?instance_id={instance_id}",
                    "note": "Summaries and excerpts are truncated; recent lists show at most three items. Compare total_counts to the shown lists and use Audit for full history. Reserved or unknown funds are unavailable for new work."}
            return _bounded_inspection(result)

    def _create_data(self, data):
        payload = _Create.model_validate(data).model_dump()
        name = unicodedata.normalize("NFC", payload["name"]).strip()
        if not name or any(unicodedata.category(char) == "Cc" for char in name):
            raise AiclError("validation_failed", "Choose a name without control characters.")
        if any(unicodedata.category(char) == "Cc" and char not in "\n\t" for char in payload["goal"]):
            raise AiclError("validation_failed", "The goal contains unsupported control characters.")
        config = self.workflow._normalize({"scenario": SCENARIO, **{key: payload[key] for key in ("goal", "inputs", "cadence", "timezone", "deliverables")}})
        normalized = {"name": name, **{key: config[key] for key in ("goal", "inputs", "cadence", "timezone", "deliverables")},
                      "budget_notes": payload["budget_notes"].strip()}
        if len(json.dumps(normalized, ensure_ascii=False).encode("utf-8")) > 4500:
            raise AiclError("validation_failed", "Keep the complete proposal under 4,500 UTF-8 bytes. Summarize inputs and use a few concise, measurable criteria for each deliverable.")
        return normalized

    def _save_agent_proposal(self, **data):
        return self._store("create", self._create_data(data), None)

    def _propose_schedule_change(self, instance_id, enabled):
        with self.db.transaction() as conn:
            self._session(conn)
            config = self.workflow._config(conn, self.auth, instance_id)
            if not config["saved"]:
                raise AiclError("validation_failed", "Save the agent's goals and deliverables before changing its schedule.")
            data = {"name": config["name"], "enabled": enabled, "old_enabled": config["enabled"],
                    "cadence": config["cadence"], "timezone": config["timezone"],
                    "expected_version": config["version"], "expected_instance_version": config["instance_version"],
                    "expected_policy_version": self.workflow.commerce._policy(conn, instance_id)["version"]}
            return self._store("schedule", data, instance_id)

    def _store(self, kind, data, instance_id):
        with self.db.transaction() as conn:
            self._session(conn)
            current = self._pending(conn)
            now = to_iso(self.clock.now())
            if current and current["kind"] == kind:
                conn.execute("UPDATE assistant_proposal SET version=version+1,data_json=?,instance_id=?,updated_at=? WHERE id=?",
                             (json.dumps(data), instance_id, now, current["id"]))
                proposal_id = current["id"]
            else:
                if current:
                    conn.execute("UPDATE assistant_proposal SET state='superseded',updated_at=? WHERE id=?", (now, current["id"]))
                proposal_id = str(uuid.uuid4())
                conn.execute("INSERT INTO assistant_proposal (id,session_id,tenant_id,owner_id,version,kind,data_json,state,instance_id,created_at,updated_at) VALUES (?,?,?,?,1,?,?,'pending',?,?,?)",
                             (proposal_id, self.session_id, self.auth.tenant_id, self.auth.owner_id, kind, json.dumps(data), instance_id, now, now))
            row = conn.execute("SELECT * FROM assistant_proposal WHERE id=?", (proposal_id,)).fetchone()
            return {"proposal": self._summary(self._view(row)), "message": "Prepared for owner review. No agent, schedule or policy has changed."}

    def _pending(self, conn):
        return conn.execute("SELECT * FROM assistant_proposal WHERE session_id=? AND tenant_id=? AND owner_id=? AND state='pending' ORDER BY rowid DESC LIMIT 1",
                            (self.session_id, self.auth.tenant_id, self.auth.owner_id)).fetchone()

    @staticmethod
    def _view(row):
        return {key: row[key] for key in ("id", "version", "kind", "state", "instance_id")} | {"data": json.loads(row["data_json"])}

    @staticmethod
    def _summary(proposal):
        data = proposal["data"]
        summary = {key: proposal[key] for key in ("id", "version", "kind", "state", "instance_id")} | {
            "name": _clip(data["name"], 100), "cadence": data["cadence"], "timezone": data["timezone"]}
        if proposal["kind"] == "create":
            summary["deliverables"] = [{"key": spec["key"], "name": _clip(spec["name"], 80),
                                        "criteria_count": len(spec["criteria"])} for spec in data["deliverables"]]
            summary["controls"] = "Draft; inference permission only; budgets $0; unfunded; schedule disabled. Budget notes are not spending authority."
        else:
            summary.update(enabled=data["enabled"], old_enabled=data["old_enabled"])
        return summary

    def proposal(self, *, include_committed=False):
        with self.db.reader() as conn:
            self._session(conn)
            row = self._pending(conn)
            if row is None and include_committed:
                row = conn.execute("SELECT * FROM assistant_proposal WHERE session_id=? AND tenant_id=? AND owner_id=? "
                                   "AND state='committed' ORDER BY rowid DESC LIMIT 1",
                                   (self.session_id, self.auth.tenant_id, self.auth.owner_id)).fetchone()
            return self._view(row) if row else None

    def _validate_agent_proposal(self):
        proposal = self.proposal()
        if proposal is None:
            raise AiclError("not_found", "There is no pending proposal to validate.")
        if proposal["kind"] == "create":
            # Normalized deliverables contain internal fixture flags; validate the public shape again.
            data = dict(proposal["data"])
            data["deliverables"] = [{key: spec[key] for key in ("key", "name", "description", "criteria")} for spec in data["deliverables"]]
            self._create_data(data)
        else:
            with self.db.reader() as conn:
                self._check_schedule(conn, proposal)
        return {"valid": True, "proposal": self._summary(proposal), "requires_owner_confirmation": True,
                "message": "Review the exact proposal and use its confirmation button. Draft creation leaves budgets at zero and the schedule disabled; enabling a schedule rechecks all existing controls."}

    def _check_schedule(self, conn, proposal):
        data, instance_id = proposal["data"], proposal["instance_id"]
        config = self.workflow._config(conn, self.auth, instance_id)
        policy = self.workflow.commerce._policy(conn, instance_id)
        if (config["version"] != data["expected_version"] or config["instance_version"] != data["expected_instance_version"]
                or config["enabled"] != data["old_enabled"] or policy["version"] != data["expected_policy_version"]):
            raise AiclError("conflict", "The agent's configuration or controls changed. Prepare and review a fresh proposal.")

    def confirm(self, proposal_id, version):
        """Owner-route entry point; deliberately absent from the model tool registry."""
        if type(version) is not int or version < 1:
            raise AiclError("validation_failed", "A proposal version is required.")
        with self.db.transaction() as conn:
            self._session(conn)
            row = conn.execute("SELECT * FROM assistant_proposal WHERE id=? AND session_id=? AND tenant_id=? AND owner_id=?",
                               (proposal_id, self.session_id, self.auth.tenant_id, self.auth.owner_id)).fetchone()
            if row is None:
                raise AiclError("not_found", "Proposal not found.")
            proposal = self._view(row)
            if row["version"] != version or row["state"] == "superseded":
                raise AiclError("conflict", "The proposal changed. Review its current version before confirming.")
            if row["state"] == "committed":
                return self._confirmed(proposal)
            if row["state"] != "pending":
                raise AiclError("invalid_state", "This proposal cannot be applied.")
            data = proposal["data"]
            if row["kind"] == "create":
                public = dict(data)
                public["deliverables"] = [{key: spec[key] for key in ("key", "name", "description", "criteria")} for spec in data["deliverables"]]
                data = self._create_data(public)
                result = creation.create_instance(self.auth, CreateInstanceRequest(
                    idempotency_key="assistant_" + uuid.UUID(proposal_id).hex, template_id="default",
                    name=data["name"], instructions=data["goal"], enabled_capabilities=frozenset({"inference"})),
                    actor_kind="chat", surface="chat", clock=self.clock)
                instance_id = result.instance.id
                self.workflow.save_config(self.auth, instance_id, {"scenario": SCENARIO, **{key: data[key] for key in ("goal", "inputs", "cadence", "timezone", "deliverables")}}, expected_version=1)
            elif row["kind"] == "schedule":
                self._check_schedule(conn, proposal)
                instance_id = row["instance_id"]
                self.workflow.schedule(self.auth, instance_id, data["enabled"],
                                       expected_version=data["expected_version"], expected_instance_version=data["expected_instance_version"])
            else:
                raise AiclError("invalid_state", "Unsupported proposal type.")
            conn.execute("UPDATE assistant_proposal SET state='committed',instance_id=?,updated_at=? WHERE id=?",
                         (instance_id, to_iso(self.clock.now()), proposal_id))
            return self._confirmed(proposal | {"instance_id": instance_id})

    @staticmethod
    def _confirmed(proposal):
        created = proposal["kind"] == "create"
        return {"instance_id": proposal["instance_id"], "url": f"/instances/{proposal['instance_id']}/workflow",
                "message": "Created a draft with saved goals and deliverables. Set budgets, add funding and enable its schedule when ready." if created
                else "Schedule enabled. Future work remains subject to AICL controls." if proposal["data"]["enabled"]
                else "Schedule paused. No new scheduled work will start; work already dispatched is not cancelled."}

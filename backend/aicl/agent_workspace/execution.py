"""One owner-reviewed definition and admission path for all workspace runs.

Views only project persisted state. Both owner starts and durable schedule ticks
use the same definition, grants, readiness check and AgentRuntime. The scheduler
retains an unpaid or occupied occurrence until it can be admitted; it neither
resumes paused work nor creates a backlog of overlapping runs.
"""
from __future__ import annotations

from datetime import timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aicl.agent_runtime.chat_service import RuntimeChatService
from aicl.agent_runtime.contracts import RunDefinition
from aicl.agent_runtime.storage import Repository
from aicl.agent_workspace.models import run_definition
from aicl.agent_workspace.setup_accounting import WorkspaceSetupAccounting, usage as setup_usage
from aicl.control.audit import AuditEvent, SqliteAuditLog
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso
from aicl.workflow.runtime_projection import RuntimeAuditProjection, audit_reader


_TERMINAL = {"completed", "cancelled", "failed"}


def next_due(config, after):
    """Next occurrence strictly after an instant, with one daily DST occurrence.

Hourly work advances in UTC. A daily time in a spring-forward gap moves forward
by the gap; a repeated fall-back time uses its first occurrence only.
"""
    if config.get("cadence") == "manual":
        return None
    if config.get("cadence") == "hourly":
        utc = after.astimezone(timezone.utc)
        return to_iso(utc.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    try:
        if config.get("cadence") != "daily":
            raise ValueError
        zone = ZoneInfo(config["timezone"])
        hour, minute = map(int, config["time_of_day"].split(":"))
        local = after.astimezone(zone)
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
        if candidate.astimezone(timezone.utc) <= after.astimezone(timezone.utc):
            candidate = (candidate + timedelta(days=1)).replace(fold=0)
        return to_iso(candidate)
    except (KeyError, ValueError, TypeError, ZoneInfoNotFoundError):
        raise AiclError("validation_failed", "Review the schedule time and timezone before enabling it.") from None


class WorkspaceExecution:
    def __init__(self, ctx):
        self.ctx, self.db, self.clock = ctx, ctx.db, ctx.clock
        self.runtime = getattr(ctx, "agent_runtime", None)
        self.repo = Repository(self.db, self.clock)
        self.chat = RuntimeChatService(ctx)
        self.setup = WorkspaceSetupAccounting(ctx)

    def _owned(self, conn, auth, workspace_id):
        if auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "Sign in to continue.")
        row = conn.execute("SELECT * FROM agent_workspace WHERE id=? AND tenant_id=? AND owner_id=?",
                           (workspace_id, auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Agent workspace not found.")
        return dict(row)

    def _require_runtime(self):
        if self.runtime is None:
            raise AiclError("unavailable", "Agent execution is not enabled on this server.")
        return self.runtime

    def _runs(self, conn, auth, workspace):
        # The legacy chat join keeps a previously blocked run recoverable even
        # before a workspace import has persisted its history link.
        rows = conn.execute(
            "SELECT r.id FROM agent_run r WHERE r.tenant_id=? AND r.owner_id=? AND r.instance_id=? AND "
            "(EXISTS (SELECT 1 FROM agent_workspace_run w WHERE w.workspace_id=? AND w.run_id=r.id) "
            "OR EXISTS (SELECT 1 FROM agent_chat_run c WHERE c.session_id=? AND c.run_id=r.id)) "
            "ORDER BY CASE WHEN r.status IN ('completed','cancelled','failed') THEN 1 ELSE 0 END,"
            "r.created_at DESC,r.rowid DESC LIMIT 30",
            (auth.tenant_id, auth.owner_id, workspace["instance_id"], workspace["id"], workspace["session_id"])).fetchall()
        return [self.repo.owned_run(conn, auth, row["id"]) for row in rows]

    def _owned_run(self, conn, auth, workspace, run_id):
        row = conn.execute(
            "SELECT 1 FROM agent_workspace_run WHERE workspace_id=? AND run_id=? UNION ALL "
            "SELECT 1 FROM agent_chat_run WHERE session_id=? AND run_id=? LIMIT 1",
            (workspace["id"], run_id, workspace["session_id"], run_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Work not found in this agent workspace.")
        run = self.repo.owned_run(conn, auth, run_id)
        if run["instance_id"] != workspace["instance_id"]:
            raise AiclError("not_found", "Work not found in this agent workspace.")
        return run

    @staticmethod
    def _schedule(conn, workspace_id):
        row = conn.execute("SELECT enabled,next_due,last_outcome FROM agent_workspace_schedule WHERE workspace_id=?",
                           (workspace_id,)).fetchone()
        return {"enabled": bool(row["enabled"]), "next_due": row["next_due"], "last_outcome": row["last_outcome"]} if row else {
            "enabled": False, "next_due": None, "last_outcome": None}

    def _configuration_blockers(self, conn, auth, workspace):
        from aicl.agent_workspace.service import WorkspaceService

        blockers = []
        service = WorkspaceService(self.ctx)
        published = service._saved_draft(conn, workspace, "published_json") if workspace["published_json"] else None
        if not published or service._saved_draft(conn, workspace) != published:
            blockers.append({"reason": "unapplied_changes", "message": "Review and apply the visible settings before starting work."})
        if not workspace["instance_id"]:
            return blockers
        instance = self.runtime.accounting.commerce._owned_instance(conn, auth, workspace["instance_id"]) if self.runtime else None
        config = conn.execute("SELECT version,enabled FROM mock_workflow_config WHERE instance_id=?",
                              (workspace["instance_id"],)).fetchone()
        if ((instance and instance["version"] != workspace["source_instance_version"])
                or (config and config["version"] != workspace["source_workflow_version"])):
            blockers.append({"reason": "external_changes", "message": "Agent controls changed elsewhere. Reload and review them before starting work."})
        if config and config["enabled"]:
            blockers.append({"reason": "legacy_schedule_active", "message": "Apply this workspace to move the existing schedule to the shared runner."})
        if conn.execute("SELECT 1 FROM render_dispatch WHERE instance_id=? AND state IN "
                        "('queued','dispatching','submission_unknown','submitted','running','unknown')",
                        (workspace["instance_id"],)).fetchone() or conn.execute(
                        "SELECT 1 FROM mock_workflow_run WHERE instance_id=? AND state IN "
                        "('queued','generating','running','inference_blocked','inference_failed','inference_unknown',"
                        "'context_blocked','permission_blocked','waiting_owner','waiting_purchase','changes_requested','owner_declined') "
                        "OR instance_id=? AND state IN ('needs_work','submitted') AND json_extract(config_json,'$.scenario') IS NOT 'general'",
                        (workspace["instance_id"], workspace["instance_id"])).fetchone():
            blockers.append({"reason": "legacy_work_active", "message": "Finish or resolve the existing scheduled work before starting another run."})
        if self.runtime and published:
            advertised = {spec["name"] for spec in self.runtime.tools.specs() if spec["name"] != "artifact.read"}
            research = getattr(self.runtime, "public_research", None)
            if research:
                advertised.update({"web.read", "web.search"})
            for name in published.get("tools", []):
                if name not in advertised:
                    blockers.append({"reason": "tool_unavailable", "message": "An approved tool is unavailable. Review the available tools before starting work."})
                    break
                if name in {"web.read", "web.search"}:
                    release = conn.execute("SELECT id FROM workspace_public_research_release WHERE workspace_id=? AND revoked_at IS NULL",
                                           (workspace["id"],)).fetchone()
                    if not research or not release:
                        blockers.append({"reason": "disclosure_approval_required", "message": "Review and approve Web access before starting work."})
                        break
                    kwargs = {"mode": "agent"} if published.get("web_access") else {}
                    status = research.status(tools=published["tools"], **kwargs)
                    if not status["available"]:
                        blockers.append({"reason": status.get("reason") or "research_unavailable", "message": status["message"]})
                        break
                    from aicl.agent_workspace.models import WorkspaceDraft
                    current = service._research_state(conn, workspace, WorkspaceDraft.model_validate(published).model_dump(mode="json"))
                    if current["approval_required"]:
                        blockers.append({"reason": "disclosure_approval_required", "message": "The public disclosure or recipient changed. Review and approve it before starting."})
                        break
                    capability = "network.search" if name == "web.search" else "network.fetch"
                    tool = SimpleNamespace(capability=capability, scripted=False)
                else:
                    tool = self.runtime.tools.get(name)
                if not getattr(tool, "scripted", False) and not self.runtime.allow_live:
                    blockers.append({"reason": "tool_unavailable", "message": "An approved tool is unavailable. Review the available tools before starting work."})
                    break
                grant = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability=?",
                                     (workspace["instance_id"], tool.capability)).fetchone()
                if (not grant or not grant[0] or (tool.capability == "network.fetch" and not published.get("web_access")
                                                 and not json.loads(instance["network_domains"]))):
                    blockers.append({"reason": "capability_disabled", "message": "Review the tool permissions and approved domains before starting work."})
                    break
        return blockers

    def _readiness(self, conn, auth, workspace, *, run=None):
        if not workspace["instance_id"]:
            amounts = setup_usage(conn, workspace["id"])
            result = {"ready": False, "balance_micro_usd": -amounts["pending_micro_usd"] - amounts["held_micro_usd"],
                      "required_micro_usd": None, "funding_order_id": None,
                      "blockers": [{"reason": "unapplied_changes", "message": "Review and apply the visible settings before starting work."}]}
        else:
            result = self.chat.readiness(conn, auth, workspace["instance_id"], run=run)
            if run is None:
                result["blockers"] = self._configuration_blockers(conn, auth, workspace) + result["blockers"]
                research = getattr(self.runtime, "public_research", None) if self.runtime else None
                release = conn.execute("SELECT id FROM workspace_public_research_release WHERE workspace_id=? AND revoked_at IS NULL",
                                       (workspace["id"],)).fetchone()
                if research and release and result["required_micro_usd"] is not None:
                    estimate = research.estimate_for_release(release["id"])
                    _, costs = self.runtime.accounting._price_estimate(conn, estimate, research.price_version)
                    public_cost = sum(costs.values())
                    result["research_required_micro_usd"] = public_cost
                    result["required_micro_usd"] += public_cost
                    if result["balance_micro_usd"] < result["required_micro_usd"]:
                        result["blockers"].append({"reason": "credit_insufficient", "message": "Add enough credit for public research and the first analysis step."})
        return self._setup_readiness(conn, workspace, result, continuing=run is not None)

    @staticmethod
    def _setup_readiness(conn, workspace, result, *, continuing=False):
        amounts = setup_usage(conn, workspace["id"])
        outstanding = amounts["pending_micro_usd"] + amounts["held_micro_usd"]
        result["setup"] = amounts
        result["credit_before_setup_micro_usd"] = result["balance_micro_usd"] + outstanding
        result["activation_required_micro_usd"] = (
            result["required_micro_usd"] + outstanding if result["required_micro_usd"] is not None else None)
        if amounts["unknown"]:
            result["blockers"].insert(0, {"reason": "setup_unresolved", "message": "Resolve the pending setup usage before activating or continuing this agent."})
        elif amounts["busy"] and not continuing:
            result["blockers"].insert(0, {"reason": "setup_in_progress", "message": "Wait for the setup assistant to finish before activating or continuing this agent."})
        result["ready"] = not result["blockers"]
        return result

    def _charge_continuation(self, auth, workspace, readiness):
        # An existing run keeps its reviewed definition while the management
        # assistant works. Pending costs and holds still reduce its credit;
        # record the settled charge at the next ready owner continuation.
        if readiness["ready"] and not readiness["setup"]["busy"]:
            self.setup.charge(auth, workspace["id"])

    def _research_requires_restart(self, conn, auth, run):
        """A recorded failed research batch cannot be replayed inside its run."""
        steps = conn.execute("SELECT state,output_ref FROM agent_step WHERE run_id=? AND tool_name='public.research'",
                             (run["id"],)).fetchall()
        if len(steps) != 1 or steps[0]["state"] != "applied" or not steps[0]["output_ref"]:
            return False
        receipt = self.repo.get_content(conn, auth, run["id"], steps[0]["output_ref"])
        return type(receipt) is not dict or "error" not in receipt or receipt["error"] is not None or "adapter_error" in receipt

    def _project(self, conn, auth, workspace, run):
        checkpoint = self.repo.get_content(conn, auth, run["id"], run["checkpoint_ref"])
        definition = RunDefinition.model_validate(self.repo.get_content(conn, auth, run["id"], run["definition_ref"])).model_dump(mode="json")
        artifacts = []
        for name, item in checkpoint["artifacts"].items():
            content = self.repo.get_content(conn, auth, run["id"], item["ref"])
            artifacts.append({"name": name, "version": item["version"], "content": content["content"],
                              "completed": name in checkpoint["completed_artifacts"]})
        readiness = self._readiness(conn, auth, workspace, run=run)
        terminal = run["status"] in _TERMINAL
        uncertain = conn.execute("SELECT 1 FROM agent_step WHERE run_id=? AND state IN ('dispatching','unknown')",
                                 (run["id"],)).fetchone() is not None
        restart = self._restart_state(conn, auth, workspace, run)
        research_restart_required = self._research_requires_restart(conn, auth, run)
        local_read_recovery = bool(self.runtime and uncertain and self.runtime.can_reconcile_local_artifact_read(conn, auth, run))
        published = self._definition(workspace).model_dump(mode="json") if workspace["published_json"] else None
        return {"id": run["id"], "instance_id": run["instance_id"], "version": run["version"],
                "status": run["status"], "reason": run["reason"], "objective": definition["objective"],
                "public_research": self.runtime.research_status(conn, auth, run) if self.runtime else None,
                "allowed_tools": definition["allowed_tools"], "settings_changed": published is not None and definition != published,
                **restart, "research_restart_required": research_restart_required,
                "local_read_recovery_available": local_read_recovery,
                "plan": list(checkpoint["plan"].values()), "artifacts": artifacts, "question": checkpoint["question"],
                "activity_log": RuntimeAuditProjection(self.db, self.clock).activity_log(conn, auth, run["id"]),
                "readiness": readiness, "can_pause": bool(self.runtime and not terminal and run["status"] != "paused"),
                "can_resume": bool(self.runtime and run["status"] in {"paused", "blocked"} and not research_restart_required and (local_read_recovery or not uncertain and readiness["ready"])),
                "can_cancel": bool(self.runtime and not terminal),
                "can_advance": bool(self.runtime and run["status"] == "queued" and not research_restart_required and readiness["ready"])}

    def _restart_state(self, conn, auth, workspace, run):
        readiness = self._readiness(conn, auth, workspace)
        blockers = []
        if run["status"] not in {"waiting_owner", "paused", "blocked"}:
            blockers.append({"reason": "restart_run_state", "message": "Pause this work or wait until it needs your input before restarting."})
        # A planned tool with no reservation or receipt has never dispatched.
        # Cancelling its old run preserves that plan without replaying it, which
        # permits recovery after the owner removes the tool's grant. Any trace
        # of paid dispatch remains a blocker, even on an inconsistent prepared row.
        if conn.execute("SELECT 1 FROM agent_step s WHERE s.run_id=? AND (s.state IN ('dispatching','received','unknown') "
                        "OR s.state='prepared' AND (s.kind<>'tool' OR s.hold_id IS NOT NULL OR s.output_ref IS NOT NULL "
                        "OR s.usage_json IS NOT NULL OR s.receipt_metadata_json<>'{}' "
                        "OR EXISTS (SELECT 1 FROM agent_runtime_hold r WHERE r.operation_id=s.id) "
                        "OR EXISTS (SELECT 1 FROM budget_hold h WHERE h.work_id='runtime:'||s.id)) "
                        "OR s.tool_name='public.research' AND EXISTS (SELECT 1 FROM budget_hold h WHERE h.id=s.hold_id "
                        "AND h.state IN ('held','unknown'))) LIMIT 1",
                        (run["id"],)).fetchone():
            blockers.append({"reason": "restart_pending_work", "message": "Finish or resolve this run's pending step before restarting. Its existing receipts and reservations must be preserved."})
        if conn.execute("SELECT 1 FROM agent_run WHERE instance_id=? AND id<>? AND status NOT IN ('completed','cancelled','failed') LIMIT 1",
                        (workspace["instance_id"], run["id"])).fetchone():
            blockers.append({"reason": "work_in_progress", "message": "Finish the other active work before restarting this run."})
        blockers.extend(readiness["blockers"])
        return {"can_restart": bool(self.runtime and not blockers), "restart_blockers": blockers,
                "restart_readiness": readiness}

    def view(self, auth, workspace_id):
        with audit_reader(self.db) as conn:
            workspace = self._owned(conn, auth, workspace_id)
            runs = self._runs(conn, auth, workspace)
            run = runs[0] if runs else None
            active = run if run and run["status"] not in _TERMINAL else None
            messages = []
            if run:
                for event in self.repo.events(conn, auth, run["id"]):
                    if event["kind"] in {"owner_message", "owner_answer", "assistant_message", "question"}:
                        messages.append({"id": event["id"], "role": "user" if event["kind"].startswith("owner_") else "assistant",
                                         "text": event["payload"]["text"]})
            readiness = self._readiness(conn, auth, workspace, run=active)
            return {"runtime_available": self.runtime is not None, "run": self._project(conn, auth, workspace, run) if run else None,
                    "readiness": readiness, "can_start": bool(not active and readiness["ready"]),
                    "schedule": self._schedule(conn, workspace_id), "messages": messages,
                    "history": [{key: item[key] for key in ("id", "status", "reason", "created_at", "updated_at")} for item in runs]}

    def _definition(self, workspace):
        definition = run_definition(json.loads(workspace["published_json"]))
        if set(definition.allowed_tools) & {"web.read", "web.search"}:
            with self.db.reader() as conn:
                release = conn.execute("SELECT id FROM workspace_public_research_release WHERE workspace_id=? AND instance_id=? AND revoked_at IS NULL",
                                       (workspace["id"], workspace["instance_id"])).fetchone()
            if release:
                definition = definition.model_copy(update={"public_research_release_id": release["id"]})
        return definition

    def _activate_draft(self, conn, auth, workspace):
        self.setup.charge(auth, workspace["id"])
        instance = self.runtime.accounting.commerce._owned_instance(conn, auth, workspace["instance_id"])
        if instance["lifecycle"] == "draft":
            from aicl.creation.operations import SqliteInstanceOperations
            SqliteInstanceOperations(self.db, self.clock).set_lifecycle(auth, instance["id"], instance["version"], "activate")
            current = conn.execute("SELECT version FROM agent_instance WHERE id=?", (instance["id"],)).fetchone()[0]
            conn.execute("UPDATE agent_workspace SET source_instance_version=?,updated_at=? WHERE id=? AND source_instance_version=?",
                         (current, to_iso(self.clock.now()), workspace["id"], instance["version"]))

    def _start(self, conn, auth, workspace, request_id, *, scheduled=False):
        runtime = self._require_runtime()
        if type(request_id) is not str or not request_id.strip() or len(request_id) > 128 or any(ord(c) < 32 for c in request_id):
            raise AiclError("validation_failed", "A bounded request identity is required.")
        key = f"workspace:{workspace['id']}:{'schedule' if scheduled else 'manual'}:{request_id}"
        existing = conn.execute("SELECT id FROM agent_run WHERE tenant_id=? AND owner_id=? AND instance_id=? AND request_key=?",
                                (auth.tenant_id, auth.owner_id, workspace["instance_id"], key)).fetchone()
        if existing:
            return self._owned_run(conn, auth, workspace, existing["id"])
        if workspace["instance_id"] and conn.execute(
                "SELECT 1 FROM agent_run WHERE instance_id=? AND status NOT IN ('completed','cancelled','failed')",
                (workspace["instance_id"],)).fetchone():
            raise AiclError("conflict", "Finish or resume the current work before starting another run.", reason="work_in_progress")
        self.chat._require_ready(self._readiness(conn, auth, workspace))
        definition = self._definition(workspace)
        self._activate_draft(conn, auth, workspace)
        runtime.accounting._controls(conn, auth, workspace["instance_id"])
        run = runtime.create_run(auth, workspace["instance_id"], key, definition)
        conn.execute("INSERT INTO agent_workspace_run(workspace_id,run_id,created_at) VALUES (?,?,?)",
                     (workspace["id"], run["id"], to_iso(self.clock.now())))
        return run

    def start(self, auth, workspace_id, request_id):
        with self.db.transaction() as conn:
            return self._start(conn, auth, self._owned(conn, auth, workspace_id), request_id)

    def restart(self, auth, workspace_id, run_id, request_id, expected_version, expected_run_version):
        """Replace explicitly reviewed idle work without rewriting its history."""
        runtime = self._require_runtime()
        if type(request_id) is not str or not request_id.strip() or len(request_id) > 128 or any(ord(c) < 32 for c in request_id):
            raise AiclError("validation_failed", "A bounded request identity is required.")
        restart_id = "restart-" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        with self.db.transaction() as conn:
            workspace = self._owned(conn, auth, workspace_id)
            original = self._owned_run(conn, auth, workspace, run_id)
            key = f"workspace:{workspace_id}:manual:{restart_id}"
            prior = conn.execute("SELECT id FROM agent_run WHERE tenant_id=? AND owner_id=? AND instance_id=? AND request_key=?",
                                 (auth.tenant_id, auth.owner_id, workspace["instance_id"], key)).fetchone()
            request = {"source_run_id": run_id, "source_run_version": expected_run_version, "workspace_version": expected_version}
            if prior:
                event = conn.execute("SELECT payload_ref FROM agent_event WHERE run_id=? AND request_key='workspace-restart'",
                                     (prior["id"],)).fetchone()
                if (event is None or self.repo.get_content(conn, auth, prior["id"], event["payload_ref"]) != request
                        or type(expected_version) is not int or type(expected_run_version) is not int):
                    raise AiclError("conflict", "This restart identity already belongs to different work or settings.")
                return self._owned_run(conn, auth, workspace, prior["id"])
            if type(expected_version) is not int or expected_version != workspace["version"]:
                raise AiclError("conflict", "The workspace changed. Reload before restarting work.", current_version=workspace["version"])
            if type(expected_run_version) is not int or expected_run_version != original["version"]:
                raise AiclError("conflict", "This run changed. Reload before restarting work.", current_run_version=original["version"])
            runs = self._runs(conn, auth, workspace)
            if not runs or runs[0]["id"] != run_id:
                raise AiclError("conflict", "Restart only the current run in this workspace.")
            restart = self._restart_state(conn, auth, workspace, original)
            if not restart["can_restart"]:
                blocker = restart["restart_blockers"][0]
                raise AiclError("denied", blocker["message"], reason=blocker["reason"], readiness=restart["restart_readiness"])
            guidance = [event for event in self.repo.events(conn, auth, run_id)
                        if event["kind"] in {"owner_message", "owner_answer"}]
            runtime.cancel(auth, run_id)
            replacement = self._start(conn, auth, workspace, restart_id)
            self.repo.append_event(conn, auth, replacement["id"], "workspace_restart", request, "workspace-restart")
            for event in guidance:
                replacement = runtime.append_owner_message(auth, replacement["id"], event["payload"]["text"],
                                                           "restart-owner:" + event["id"])
            # Preserve owner guidance in full. If it no longer fits alongside
            # the new definition, rollback the replacement and cancellation.
            context = runtime._context(conn, auth, replacement, runtime._checkpoint(conn, auth, replacement))
            if hasattr(runtime.model, "validate_context"):
                from aicl.workflow.openai_inference import InferenceNoChargeError
                try:
                    runtime.model.validate_context(context)
                except InferenceNoChargeError as error:
                    raise AiclError("denied", "Review the saved instructions and owner messages before restarting this work.",
                                    reason=error.reason) from None
            return replacement

    def control(self, auth, workspace_id, run_id, action, *, expected_run_version=None):
        runtime = self._require_runtime()
        with self.db.transaction() as conn:
            workspace = self._owned(conn, auth, workspace_id)
            run = self._owned_run(conn, auth, workspace, run_id)
            if action in {"resume", "advance"} and self._research_requires_restart(conn, auth, run):
                raise AiclError("denied", "This research attempt cannot continue. Use Retry research to start a new run; existing history and charges are kept.",
                                reason="research_restart_required")
            if action == "resume" and runtime.can_reconcile_local_artifact_read(conn, auth, run):
                run = runtime.reconcile_local_artifact_read(auth, run_id, expected_run_version)
                readiness = self._readiness(conn, auth, workspace, run=run)
                if not readiness["ready"]:
                    # Keep the proven local reconciliation even when later paid
                    # work cannot be admitted. No reservation or dispatch occurs.
                    return runtime._save(conn, auth, run, runtime._checkpoint(conn, auth, run),
                                         status="blocked", reason=readiness["blockers"][0]["reason"])
            if action == "resume" and run["status"] in {"queued", "running"}:
                if run["status"] == "queued":
                    readiness = self._readiness(conn, auth, workspace, run=run)
                    self.chat._require_ready(readiness)
                    self._charge_continuation(auth, workspace, readiness)
                    runtime.repo._wakeup(conn, run_id, run["version"], to_iso(self.clock.now()))
                return run
            if action in {"pause", "resume", "cancel"}:
                if action == "resume" and run["status"] in {"paused", "blocked"}:
                    readiness = self._readiness(conn, auth, workspace, run=run)
                    self.chat._require_ready(readiness)
                    self._charge_continuation(auth, workspace, readiness)
                return getattr(runtime, action)(auth, run_id)
            if action == "advance":
                if run["status"] != "queued":
                    raise AiclError("conflict", "This work is not ready to continue.")
                readiness = self._readiness(conn, auth, workspace, run=run)
                self.chat._require_ready(readiness)
                self._charge_continuation(auth, workspace, readiness)
                runtime.repo._wakeup(conn, run_id, run["version"], to_iso(self.clock.now()))
                return run
            raise AiclError("not_found", "Unknown work control.")

    def message(self, auth, workspace_id, run_id, request_id, text, question_id=None):
        runtime = self._require_runtime()
        with self.db.transaction() as conn:
            workspace = self._owned(conn, auth, workspace_id)
            run = self._owned_run(conn, auth, workspace, run_id)
            if question_id:
                updated = runtime.answer(auth, run_id, question_id, text, request_id)
            else:
                updated = runtime.append_owner_message(auth, run_id, text, request_id)
            # Accept owner context even while setup is running or credit is
            # insufficient. Dispatch checks remain authoritative, and replay
            # never authorizes a charge for setup that accrued after the message.
            if updated["owner_cursor"] != run["owner_cursor"] and updated["status"] in {"queued", "running"}:
                self._charge_continuation(auth, workspace, self._readiness(conn, auth, workspace, run=updated))
            return updated

    def lifecycle(self, auth, workspace_id, action, expected_version):
        """Explicit owner controls for the agent, separate from one run's state."""
        from aicl.creation.operations import SqliteInstanceOperations
        if type(action) is not str or action not in {"activate", "pause", "resume", "archive"}:
            raise AiclError("validation_failed", "Choose an available agent control.")
        with self.db.transaction() as conn:
            workspace = self._owned(conn, auth, workspace_id)
            if type(expected_version) is not int or expected_version != workspace["version"]:
                raise AiclError("conflict", "The workspace changed. Reload before changing agent controls.", current_version=workspace["version"])
            instance = conn.execute("SELECT * FROM agent_instance WHERE id=? AND tenant_id=? AND owner_id=?",
                                    (workspace["instance_id"], auth.tenant_id, auth.owner_id)).fetchone()
            if instance is None:
                raise AiclError("invalid_state", "Apply the agent settings before changing its controls.")
            config = conn.execute("SELECT version FROM mock_workflow_config WHERE instance_id=?", (instance["id"],)).fetchone()
            sources_match = (instance["version"] == workspace["source_instance_version"] and
                             (config["version"] if config else None) == workspace["source_workflow_version"])
            if action in {"activate", "resume"} and not sources_match:
                raise AiclError("conflict", "Agent controls changed elsewhere. Reload their current values before resuming.", external_conflict=True)
            if action in {"activate", "resume"}:
                runs = self._runs(conn, auth, workspace)
                active = next((run for run in runs if run["status"] not in _TERMINAL), None)
                readiness = self._setup_readiness(conn, workspace, self.chat.readiness(conn, auth, instance["id"], run=active))
                # This explicit owner action supplies the missing lifecycle
                # transition; all funding, usage and permission checks remain.
                readiness["blockers"] = [item for item in readiness["blockers"] if item["reason"] != "instance_not_active"]
                readiness["ready"] = not readiness["blockers"]
                self.chat._require_ready(readiness)
                self.setup.charge(auth, workspace_id)
            SqliteInstanceOperations(self.db, self.clock).set_lifecycle(auth, instance["id"], instance["version"], action)
            current = conn.execute("SELECT version,lifecycle FROM agent_instance WHERE id=?", (instance["id"],)).fetchone()
            # A restrictive action remains available after an external edit, but
            # must not mark that unrelated edit as reviewed.
            source_version = current["version"] if sources_match else workspace["source_instance_version"]
            conn.execute("UPDATE agent_workspace SET source_instance_version=?,version=version+1,updated_at=? WHERE id=?",
                         (source_version, to_iso(self.clock.now()), workspace_id))
            return {"lifecycle": current["lifecycle"], "source_instance_version": source_version, "version": workspace["version"] + 1}

    def schedule(self, auth, workspace_id, enabled, expected_version):
        if type(enabled) is not bool:
            raise AiclError("validation_failed", "Enabled must be true or false.")
        with self.db.transaction() as conn:
            workspace = self._owned(conn, auth, workspace_id)
            if type(expected_version) is not int or expected_version != workspace["version"]:
                raise AiclError("conflict", "The workspace changed. Reload before updating its schedule.", current_version=workspace["version"])
            current = self._schedule(conn, workspace_id)
            if current["enabled"] == enabled:
                return current
            due = current["next_due"]
            if enabled:
                self._require_runtime()
                self.chat._require_ready(self._readiness(conn, auth, workspace))
                definition = json.loads(workspace["published_json"])
                due = next_due(definition, self.clock.now())
                if due is None:
                    raise AiclError("validation_failed", "Choose an hourly or daily cadence before enabling the schedule.")
                self._activate_draft(conn, auth, workspace)
                self.runtime.accounting._controls(conn, auth, workspace["instance_id"])
            now = to_iso(self.clock.now())
            conn.execute("INSERT INTO agent_workspace_schedule(workspace_id,enabled,next_due,last_outcome,updated_at) VALUES (?,?,?,?,?) "
                         "ON CONFLICT(workspace_id) DO UPDATE SET enabled=excluded.enabled,next_due=excluded.next_due,"
                         "last_outcome=excluded.last_outcome,updated_at=excluded.updated_at",
                         (workspace_id, int(enabled), due, "Scheduled" if enabled else "Paused", now))
            conn.execute("UPDATE agent_workspace SET version=version+1,updated_at=? WHERE id=?", (now, workspace_id))
            SqliteAuditLog(self.clock).append(conn, AuditEvent(
                "commerce.policy_changed", "owner", "committed", auth.tenant_id, auth.owner_id, workspace["instance_id"],
                details={"action": "workspace_schedule_enabled" if enabled else "workspace_schedule_paused", "version": workspace["version"] + 1}))
            return self._schedule(conn, workspace_id)

    def admit_due(self, *, worker_id="workspace-scheduler", limit=8):
        """Admit due occurrences only; the ordinary runtime worker dispatches them."""
        self._require_runtime()
        with self.db.reader() as conn:
            due_rows = conn.execute(
                "SELECT w.id,w.tenant_id,w.owner_id FROM agent_workspace w JOIN agent_workspace_schedule s ON s.workspace_id=w.id "
                "WHERE s.enabled=1 AND s.next_due<=? ORDER BY s.updated_at,s.next_due,w.id LIMIT ?", (to_iso(self.clock.now()), limit)).fetchall()
        admitted = 0
        for row in due_rows:
            auth = AuthContext(row["owner_id"], row["tenant_id"], worker_id, self.clock.now() + timedelta(minutes=10))
            with self.db.transaction() as conn:
                workspace = self._owned(conn, auth, row["id"])
                schedule = self._schedule(conn, workspace["id"])
                if not schedule["enabled"] or not schedule["next_due"] or from_iso(schedule["next_due"]) > self.clock.now():
                    continue
                due = schedule["next_due"]
                try:
                    # Admission failure rolls back lifecycle/link mutations while
                    # the outer transaction preserves the due occurrence/reason.
                    with self.db.transaction():
                        self._start(conn, auth, workspace, due, scheduled=True)
                    following = next_due(json.loads(workspace["published_json"]), self.clock.now())
                    conn.execute("UPDATE agent_workspace_schedule SET next_due=?,last_outcome='Started',updated_at=? WHERE workspace_id=?",
                                 (following, to_iso(self.clock.now()), workspace["id"]))
                    admitted += 1
                except AiclError as error:
                    outcome = str(error.extra.get("reason", error.error)) + ": " + error.message
                    # Rotate checked workspaces so a full batch of unfunded
                    # occurrences cannot starve later, runnable schedules.
                    conn.execute("UPDATE agent_workspace_schedule SET last_outcome=?,updated_at=? WHERE workspace_id=?",
                                 (outcome, to_iso(self.clock.now()), workspace["id"]))
        return admitted


def admit_scheduled_runs(runtime, worker_id):
    return WorkspaceExecution(SimpleNamespace(db=runtime.db, clock=runtime.clock, agent_runtime=runtime)).admit_due(worker_id=worker_id)

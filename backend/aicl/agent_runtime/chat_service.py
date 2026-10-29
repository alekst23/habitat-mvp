"""Owner-authenticated chat admission and projections for durable runs.

The setup assistant never starts a run. Only explicit owner POSTs admit work or
change run controls. Model-generated events remain in the run's own journal.
"""
from __future__ import annotations

from pydantic import ValidationError

from aicl.agent_runtime.contracts import RunDefinition, RuntimeLimits
from aicl.commerce.service import MockCommerceService
from aicl.control.errors import AiclError
from aicl.db import to_iso
from aicl.workflow.service import MockWorkflowService


class RuntimeChatService:
    def __init__(self, ctx):
        self.ctx, self.db, self.clock = ctx, ctx.db, ctx.clock
        self.runtime = getattr(ctx, "agent_runtime", None)

    def _session(self, conn, auth, session_id):
        if auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "Sign in to continue.")
        row = conn.execute("SELECT * FROM assistant_session WHERE id=? AND tenant_id=? AND owner_id=?",
                           (session_id, auth.tenant_id, auth.owner_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Conversation not found.")
        return row

    def linked(self, conn, auth, session_id):
        self._session(conn, auth, session_id)
        row = conn.execute("SELECT run_id FROM agent_chat_run WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            return None
        # Read access remains possible when live dispatch has been disabled.
        from aicl.agent_runtime.storage import Repository
        return Repository(self.db, self.clock).owned_run(conn, auth, row[0])

    def _require_runtime(self):
        if self.runtime is None:
            raise AiclError("unavailable", "Durable sessions are not enabled on this server.")
        return self.runtime

    def readiness(self, conn, auth, instance_id, *, run=None):
        """Price the operation the worker would next dispatch, without advancing it."""
        funding_order = conn.execute(
            "SELECT id FROM mock_commerce_order WHERE instance_id=? AND tenant_id=? AND owner_id=? "
            "AND purpose='service_topup' AND state IN ('created','pending') "
            "ORDER BY created_at DESC,rowid DESC LIMIT 1", (instance_id, auth.tenant_id, auth.owner_id)).fetchone()
        funding_order_id = funding_order["id"] if funding_order else None
        if self.runtime is None:
            commerce = MockCommerceService(self.db, self.clock)
            commerce._owned_instance(conn, auth, instance_id)
            return {"ready": False, "balance_micro_usd": commerce._balance(conn, instance_id),
                    "required_micro_usd": None, "funding_order_id": funding_order_id,
                    "blockers": [{"reason": "runtime_unavailable",
                    "message": "Durable sessions are not enabled on this server."}]}
        runtime = self.runtime
        adapter, limits, spent, blockers = runtime.model, RuntimeLimits(), 0, []
        estimate, price_version = adapter.estimate, getattr(adapter, "price_version", None)
        if run:
            limits, spent = runtime._limits(run), runtime._run_spend(conn, run["id"])
            definition = runtime._definition(conn, auth, run)
            research_step = conn.execute("SELECT * FROM agent_step WHERE run_id=? AND tool_name='public.research' ORDER BY sequence LIMIT 1",
                                         (run["id"],)).fetchone()
            needs_research = bool(definition.public_research_release_id and not research_step)
            if set(definition.allowed_tools) & {"web.search", "web.read"} and not definition.public_research_release_id:
                blockers.append({"reason": "disclosure_approval_required",
                                 "message": "Approve the public research disclosure and restart with updated settings."})
            # New owner context supersedes prepared actions before dispatch.
            pending = (conn.execute("SELECT * FROM agent_step WHERE run_id=? AND state='prepared' ORDER BY sequence LIMIT 1",
                                    (run["id"],)).fetchone() if run["owner_cursor"] == run["applied_cursor"] else None)
            if needs_research or (pending and pending["tool_name"] == "public.research"):
                try:
                    if runtime.public_research is None:
                        raise AiclError("unavailable", "The public research boundary is unavailable.")
                    estimate = runtime.public_research.estimate_for_release(definition.public_research_release_id)
                    price_version = runtime.public_research.price_version
                except AiclError:
                    blockers.append({"reason": "public_research_unavailable",
                                     "message": "The approved public research release is unavailable. Review the settings."})
            elif pending:
                try:
                    adapter = runtime.tools.get(pending["tool_name"])
                    if adapter.version != pending["tool_version"]:
                        raise AiclError("denied", "Saved tool version is unavailable.")
                    estimate, price_version = adapter.estimate, getattr(adapter, "price_version", None)
                except AiclError:
                    blockers.append({"reason": "adapter_version", "message": "The saved tool is unavailable. Review this work before continuing."})
                if run["action_count"] >= limits.max_actions:
                    blockers.append({"reason": "action_limit", "message": "The session's action limit is reached."})
            elif run["decision_count"] >= limits.max_decisions:
                blockers.append({"reason": "decision_limit", "message": "The session's decision limit is reached."})
        result = runtime.accounting.readiness(
            conn, auth, instance_id, estimate, limits.max_run_cost_micro_usd, spent,
            price_version=price_version, allow_draft=run is None)
        result["blockers"].extend(blockers)
        result["ready"] = not result["blockers"]
        result["funding_order_id"] = funding_order_id
        return result

    @staticmethod
    def _require_ready(readiness):
        if not readiness["ready"]:
            blocker = readiness["blockers"][0]
            raise AiclError("denied", blocker["message"], reason=blocker["reason"], readiness=readiness)

    def candidates(self, conn, auth):
        rows = conn.execute("SELECT i.id,i.name,i.network_domains FROM agent_instance i "
                            "JOIN mock_workflow_config c ON c.instance_id=i.id "
                            "WHERE i.tenant_id=? AND i.owner_id=? AND json_extract(c.data_json,'$.scenario')='general' "
                            "ORDER BY i.updated_at DESC", (auth.tenant_id, auth.owner_id)).fetchall()
        output = []
        for row in rows:
            grant = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability='network.fetch'",
                                 (row["id"],)).fetchone()
            available = []
            if self.runtime and grant and grant[0] and row["network_domains"] != "[]":
                if any(spec["name"] == "web.read" for spec in self.runtime.tools.specs()):
                    available = [{"name": "web.read", "title": "Read public pages on this agent’s approved domains"}]
            output.append({"id": row["id"], "name": row["name"], "tools": available,
                           "readiness": self.readiness(conn, auth, row["id"]),
                           "setup_href": f"/instances/{row['id']}/workflow"})
        return output

    def view(self, auth, session_id):
        from aicl.agent_runtime.storage import Repository
        repo = Repository(self.db, self.clock)
        with self.db.reader() as conn:
            run = self.linked(conn, auth, session_id)
            candidates = self.candidates(conn, auth) if not run and self.runtime else []
            result = {"runtime_available": self.runtime is not None, "runtime_candidates": candidates, "runtime_run": None,
                      "runtime_messages": []}
            if run is None:
                return result
            checkpoint = repo.get_content(conn, auth, run["id"], run["checkpoint_ref"])
            definition = repo.get_content(conn, auth, run["id"], run["definition_ref"])
            artifacts = []
            for name, item in checkpoint["artifacts"].items():
                content = repo.get_content(conn, auth, run["id"], item["ref"])
                artifacts.append({"name": name, "version": item["version"], "content": content["content"],
                                  "completed": name in checkpoint["completed_artifacts"]})
            terminal = run["status"] in {"completed", "cancelled", "failed"}
            uncertain = conn.execute("SELECT 1 FROM agent_step WHERE run_id=? AND state IN ('dispatching','unknown')",
                                     (run["id"],)).fetchone() is not None
            readiness = self.readiness(conn, auth, run["instance_id"], run=run)
            result["runtime_run"] = {
                "id": run["id"], "instance_id": run["instance_id"], "readiness": readiness,
                "version": run["version"], "status": run["status"], "reason": run["reason"],
                "objective": definition["objective"], "plan": list(checkpoint["plan"].values()), "artifacts": artifacts,
                "question": checkpoint["question"],
                "can_pause": bool(self.runtime and not terminal and run["status"] != "paused"),
                "can_resume": bool(self.runtime and run["status"] in {"paused", "blocked"} and not uncertain and readiness["ready"]),
                "can_cancel": bool(self.runtime and not terminal),
                "can_advance": bool(self.runtime and run["status"] == "queued")}
            for event in repo.events(conn, auth, run["id"]):
                if event["kind"] in {"owner_message", "owner_answer", "assistant_message", "question"}:
                    result["runtime_messages"].append({"id": event["id"], "role": "user" if event["kind"].startswith("owner_") else "assistant",
                                                       "text": event["payload"]["text"]})
            return result

    def start(self, auth, session_id, instance_id, request_id, tools):
        runtime = self._require_runtime()
        if (not isinstance(tools, list) or any(type(name) is not str for name in tools)
                or len(tools) != len(set(tools)) or not set(tools) <= {"web.read"}):
            raise AiclError("validation_failed", "Review the available tools before starting work.")
        with self.db.transaction() as conn:
            self._session(conn, auth, session_id)
            existing = self.linked(conn, auth, session_id)
            key = f"chat:{session_id}:{request_id}"
            if existing:
                saved = runtime._definition(conn, auth, existing)
                if (existing["request_key"] != key or existing["instance_id"] != instance_id
                        or saved.allowed_tools != sorted(tools)):
                    raise AiclError("conflict", "This conversation already has a run. Open a new conversation for new work.")
                return existing
            workflow = MockWorkflowService(self.db, self.clock)
            config = workflow._config(conn, auth, instance_id)
            if not config["saved"] or config["scenario"] != "general":
                raise AiclError("validation_failed", "Choose a saved general agent.")
            workflow._require_demo_active(conn, auth)
            if config["enabled"]:
                raise AiclError("denied", "Pause this agent’s schedule before starting an interactive session.")
            if conn.execute("SELECT 1 FROM agent_run WHERE instance_id=? AND status NOT IN ('completed','cancelled','failed')",
                            (instance_id,)).fetchone():
                raise AiclError("conflict", "This agent already has an unfinished durable session.")
            if conn.execute("SELECT 1 FROM render_dispatch WHERE instance_id=? AND state IN "
                            "('queued','dispatching','submission_unknown','submitted','running','unknown')", (instance_id,)).fetchone():
                raise AiclError("conflict", "Resolve the existing hosted worker before starting a session.")
            if conn.execute("SELECT 1 FROM mock_workflow_run WHERE instance_id=? AND state IN "
                            "('generating','running','inference_unknown','waiting_owner','waiting_purchase','changes_requested')",
                            (instance_id,)).fetchone():
                raise AiclError("conflict", "Resolve the existing scheduled work before starting a session.")
            inst = workflow._instance(conn, auth, instance_id)
            candidate = next(item for item in self.candidates(conn, auth) if item["id"] == instance_id)
            if not set(tools) <= {item["name"] for item in candidate["tools"]}:
                raise AiclError("denied", "Enable network access and approved domains in the agent’s controls first.")
            requirements = [{"id": item["key"], "text": item["name"] + "\n" + item["description"]
                             + "\nCompletion criteria:\n" + "\n".join(item["criteria"])} for item in config["deliverables"]]
            try:
                definition = RunDefinition(objective=config["goal"] + ("\n\nSupplied context:\n" + config["inputs"] if config["inputs"] else ""),
                                           requirements=requirements, allowed_tools=sorted(tools))
            except ValidationError:
                raise AiclError("validation_failed", "The saved requirements exceed this session’s size limit. Shorten them before starting.") from None
            self._require_ready(candidate["readiness"])
            if inst["lifecycle"] == "draft":
                from aicl.creation.operations import SqliteInstanceOperations
                SqliteInstanceOperations(self.db, self.clock).set_lifecycle(auth, instance_id, inst["version"], "activate")
            runtime.accounting.commerce._controls(conn, auth, instance_id)
            run = runtime.create_run(auth, instance_id, key, definition)
            conn.execute("INSERT INTO agent_chat_run(session_id,run_id,created_at) VALUES (?,?,?)",
                         (session_id, run["id"], to_iso(self.clock.now())))
            return run

    def message(self, auth, session_id, request_id, text, *, run_id=None, question_id=None):
        runtime = self._require_runtime()
        with self.db.transaction() as conn:
            run = self.linked(conn, auth, session_id)
            if not run or run_id != run["id"]:
                raise AiclError("conflict", "Reload the conversation before addressing this run.")
            if question_id:
                runtime.answer(auth, run["id"], question_id, text, request_id)
            else:
                runtime.append_owner_message(auth, run["id"], text, request_id)
            conn.execute("UPDATE assistant_session SET updated_at=? WHERE id=?", (to_iso(self.clock.now()), session_id))
        return {"chat_session_id": session_id, "text": "Your message was saved to the session.", "replayed": False}

    def control(self, auth, session_id, run_id, action):
        runtime = self._require_runtime()
        with self.db.transaction() as conn:
            run = self.linked(conn, auth, session_id)
            if not run or run["id"] != run_id:
                raise AiclError("not_found", "Session not found.")
            if action in {"pause", "resume", "cancel"}:
                if action == "resume" and run["status"] in {"paused", "blocked"}:
                    self._require_ready(self.readiness(conn, auth, run["instance_id"], run=run))
                return getattr(runtime, action)(auth, run_id)
            if action == "advance":
                if run["status"] != "queued":
                    raise AiclError("conflict", "This session is not ready to continue.")
                runtime.repo._wakeup(conn, run_id, run["version"], to_iso(self.clock.now()))
                return run
            raise AiclError("not_found", "Unknown session control.")

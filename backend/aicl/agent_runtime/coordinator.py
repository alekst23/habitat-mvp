"""Serial, recoverable execution of structured decisions and accepted tool batches.

Live adapters require explicit nonproduction enablement. All semantic updates
are applied through one SQLite transaction, separately from external dispatch.
"""
from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
from time import monotonic

from pydantic import ValidationError

from aicl.agent_runtime.accounting import RuntimeAccounting
from aicl.agent_runtime.adapters import AdapterResult, ScopedArtifactReader
from aicl.agent_runtime.contracts import RunDefinition, RuntimeLimits, canonical_json, digest, parse_envelope
from aicl.agent_runtime.storage import Repository
from aicl.agent_runtime.research_context import public_evidence_preview, source_overview
from aicl.agent_runtime.read_coverage import merged_ranges, read_selector, read_span, request_covered
from aicl.agent_runtime.validation import contract_validation_error, sanitize_validation_error
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso
from aicl.workflow.openai_inference import InferenceNoChargeError, _contains_secret

_TERMINAL = {"completed", "cancelled", "failed"}
_PUBLIC_TOOLS = frozenset({"web.search", "web.read"})
_RESEARCH_STEP = "public.research"


class AgentRuntime:
    def __init__(self, db, clock, model, tools, *, environment="development", accounting=None, allow_live=False,
                 public_research=None):
        if environment not in {"development", "test"} or (getattr(model, "scripted", False) is not True and not allow_live):
            raise AiclError("denied", "Live runtime requires explicit nonproduction enablement.")
        self.db, self.clock, self.model = db, clock, model
        self.allow_live = allow_live
        self.public_research = public_research
        self.repo = Repository(db, clock)
        self.tools = tools.with_artifact_reader(self.repo)
        self.accounting = accounting or RuntimeAccounting(db, clock)

    def _auth(self, auth):
        if auth.expires_at <= self.clock.now():
            raise AiclError("unauthenticated", "Sign in again.")

    def create_run(self, auth, instance_id, request_key, definition, limits=None):
        self._auth(auth)
        definition = RunDefinition.model_validate(definition)
        limits = RuntimeLimits.model_validate(limits or {})
        for name in definition.allowed_tools:
            if name in _PUBLIC_TOOLS:
                # These are owner-selected research operations, not tools
                # callable by the private/mixed-context decision model.
                if definition.public_research_release_id and self.public_research is not None:
                    continue
                raise AiclError("denied", "Approve a public research release before starting web work.",
                                reason="disclosure_approval_required")
            if self.tools.get(name).scripted is not True and not self.allow_live:
                raise AiclError("denied", "live tools are not enabled")
        return self.repo.create_run(auth, instance_id, request_key,
                                    definition.model_dump(mode="json", exclude_none=True), limits.model_dump(mode="json"))

    def read(self, auth, run_id):
        self._auth(auth)
        with self.db.reader() as conn:
            run = self.repo.owned_run(conn, auth, run_id)
            return {**run, "checkpoint": self._checkpoint(conn, auth, run),
                    "events": self.repo.events(conn, auth, run_id),
                    "public_research": self.research_status(conn, auth, run)}

    def research_status(self, conn, auth, run):
        """Project completed research without authorizing or performing new work."""
        run = self.repo.owned_run(conn, auth, run["id"])
        step = conn.execute("SELECT * FROM agent_step WHERE run_id=? AND tool_name=? "
                            "AND state='applied' AND output_ref IS NOT NULL ORDER BY sequence DESC LIMIT 1",
                            (run["id"], _RESEARCH_STEP)).fetchone()
        if step is None:
            return None
        receipt = self.repo.get_content(conn, auth, run["id"], step["output_ref"])
        if (type(receipt) is not dict or "error" not in receipt or receipt["error"] is not None
                or "adapter_error" in receipt):
            return None
        return self._research_context(conn, auth, run, step, receipt=receipt)

    def _checkpoint(self, conn, auth, run):
        return self.repo.get_content(conn, auth, run["id"], run["checkpoint_ref"])

    def _definition(self, conn, auth, run):
        return RunDefinition.model_validate(self.repo.get_content(conn, auth, run["id"], run["definition_ref"]))

    def _limits(self, run):
        return RuntimeLimits.model_validate_json(run["limits_json"])

    def _save(self, conn, auth, run, checkpoint, **changes):
        return self.repo.save_checkpoint(conn, auth, run, checkpoint, changes)

    def _event(self, conn, auth, run, kind, payload, key):
        return self.repo.append_event(conn, auth, run["id"], kind, payload, key)

    def append_owner_message(self, auth, run_id, text, request_key):
        self._auth(auth)
        self._text(text)
        with self.db.transaction() as conn:
            run = self.repo.owned_run(conn, auth, run_id)
            if run["status"] in _TERMINAL:
                raise AiclError("invalid_state", "Create a revision run for completed work.")
            event = self._event(conn, auth, run, "owner_message", {"text": text}, request_key)
            if event["sequence"] <= run["owner_cursor"]:
                return run
            return self._save(conn, auth, run, self._checkpoint(conn, auth, run), owner_cursor=event["sequence"])

    def answer(self, auth, run_id, question_id, text, request_key):
        self._auth(auth)
        self._text(text)
        payload = {"question_id": question_id, "text": text}
        with self.db.transaction() as conn:
            run = self.repo.owned_run(conn, auth, run_id)
            prior = conn.execute("SELECT * FROM agent_event WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
            if prior:
                if prior["kind"] != "owner_answer" or self.repo.get_content(conn, auth, run_id, prior["payload_ref"]) != payload:
                    raise AiclError("conflict", "Answer identity was already used.")
                return run
            checkpoint = self._checkpoint(conn, auth, run)
            question = checkpoint["question"]
            if not question or question["id"] != question_id or run["status"] in _TERMINAL:
                raise AiclError("conflict", "This is not the current question.")
            event = self._event(conn, auth, run, "owner_answer", payload, request_key)
            checkpoint["question"] = None
            status = "queued" if run["status"] == "waiting_owner" else run["status"]
            return self._save(conn, auth, run, checkpoint, status=status, reason=None,
                              owner_cursor=event["sequence"])

    @staticmethod
    def _text(text):
        if type(text) is not str or not text.strip() or len(text) > 12000:
            raise AiclError("validation_failed", "Use a nonempty message of at most 12000 characters.")

    def pause(self, auth, run_id):
        return self._lifecycle(auth, run_id, "paused")

    def cancel(self, auth, run_id):
        return self._lifecycle(auth, run_id, "cancelled")

    def resume(self, auth, run_id):
        return self._lifecycle(auth, run_id, "queued")

    def _lifecycle(self, auth, run_id, status):
        self._auth(auth)
        with self.db.transaction() as conn:
            run = self.repo.owned_run(conn, auth, run_id)
            checkpoint = self._checkpoint(conn, auth, run)
            if run["status"] in _TERMINAL:
                if run["status"] == status:
                    return run
                raise AiclError("invalid_state", "Run is terminal.")
            if status == "queued":
                if run["status"] not in {"paused", "blocked"}:
                    raise AiclError("invalid_state", "Run is not paused or blocked.")
                if conn.execute("SELECT 1 FROM agent_step WHERE run_id=? AND state IN ('dispatching','unknown')", (run_id,)).fetchone():
                    raise AiclError("denied", "Reconcile the existing attempt first.")
                if checkpoint["question"]:
                    status = "waiting_owner"
            run = self._save(conn, auth, run, checkpoint, status=status, reason=None)
            self._event(conn, auth, run, "lifecycle", {"status": status}, f"lifecycle:{run['version']}")
            return run

    def advance_slice(self, auth, run_id, *, max_operations=16, worker_id=None, fault=None, max_seconds=120):
        """Advance bounded work. Fault hooks are only for deterministic crash tests.

        An unexpected caller/process failure leaves the lease intact; after expiry
        a new worker can apply receipts but cannot resend an uncertain dispatch.
        """
        self._auth(auth)
        if type(max_operations) is not int or not 1 <= max_operations <= 100:
            raise AiclError("validation_failed", "Invalid slice operation limit.")
        if type(max_seconds) is not int or not 1 <= max_seconds <= 300:
            raise AiclError("validation_failed", "Invalid slice time limit.")
        deadline = monotonic() + max_seconds
        initial = self.read(auth, run_id)
        if initial["status"] not in {"queued", "running"}:
            return initial
        worker_id = worker_id or str(uuid.uuid4())
        lease_seconds = max(30, int(getattr(self.model, "timeout_seconds", 0)) * 2 + 30)
        run = self.repo.claim(auth, run_id, worker_id, lease_seconds=lease_seconds)
        fence = run["fence"]
        for _ in range(max_operations):
            if monotonic() >= deadline:
                break
            with self.db.transaction() as conn:
                run = self.repo.owned_run(conn, auth, run_id)
                if run["status"] != "running":
                    break
                run = self.repo.check_fence(conn, auth, run_id, worker_id, fence)
                checkpoint = self._checkpoint(conn, auth, run)
                steps = self.repo.steps(conn, auth, run_id)
                uncertain = next((s for s in steps if s["state"] in {"dispatching", "unknown"}), None)
                if uncertain:
                    self.accounting.mark_unknown(conn, uncertain["hold_id"])
                    conn.execute("UPDATE agent_step SET state='unknown' WHERE id=?", (uncertain["id"],))
                    self._save(conn, auth, run, checkpoint, status="blocked", reason="unknown_outcome")
                    break
                received = next((s for s in steps if s["state"] == "received"), None)
                if received:
                    self._apply_received(conn, auth, run, checkpoint, received)
                    continue
                if run["applied_cursor"] != run["owner_cursor"]:
                    conn.execute("UPDATE agent_step SET state='superseded' WHERE run_id=? AND state='prepared'",
                                 (run_id,))
                    run = self._save(conn, auth, run, checkpoint, applied_cursor=run["owner_cursor"])
                    steps = self.repo.steps(conn, auth, run_id)
                pending = next((s for s in steps if s["state"] == "prepared"), None)
                definition = self._definition(conn, auth, run)
                research_pending = bool(definition.public_research_release_id
                                        and not any(s["tool_name"] == _RESEARCH_STEP for s in steps))
                adapter = (self.public_research if research_pending else
                           None if pending and pending["tool_name"] in _PUBLIC_TOOLS | {_RESEARCH_STEP} else
                           self.tools.get(pending["tool_name"]) if pending else self.model)
                timeout = int(getattr(adapter, "timeout_seconds", 0))
                if monotonic() + timeout + 5 > deadline:
                    break
                self.repo.renew(conn, auth, run_id, worker_id, fence, max(lease_seconds, timeout * 2 + 30))
                conn.execute("SAVEPOINT runtime_prepare")
                try:
                    research_needed = self._research_phase(conn, auth, run, steps)
                    if research_needed:
                        dispatch = self._prepare_research_dispatch(conn, auth, run, checkpoint)
                    elif pending and self._reuse_read(conn, auth, run, checkpoint, pending):
                        conn.execute("RELEASE runtime_prepare")
                        continue
                    else:
                        dispatch = self._prepare_dispatch(conn, auth, run, checkpoint, pending)
                except (AiclError, InferenceNoChargeError) as error:
                    # A denial must never leave a reservation without its step.
                    conn.execute("ROLLBACK TO runtime_prepare")
                    conn.execute("RELEASE runtime_prepare")
                    reason = (str(error.extra.get("reason", error.error)) if isinstance(error, AiclError)
                              else error.reason)
                    self._save(conn, auth, run, checkpoint, status="blocked", reason=reason)
                    break
                else:
                    conn.execute("RELEASE runtime_prepare")
            if fault:
                fault("after_dispatch_intent", dispatch)
            try:
                with self.db.reader() as conn:
                    self.accounting._require_demo_active(conn, auth)
            except AiclError as error:
                # Expiry after reservation is a proven no-dispatch outcome.
                # Keep this separate from provider failures and receipt settlement.
                self._record_no_charge(auth, run_id, dispatch, str(error.extra.get("reason", error.error)))
                break
            try:
                request = dispatch["request"]
                if dispatch["kind"] == "decision":
                    result = self.model.decide(request, dispatch["id"])
                elif dispatch["tool_name"] == _RESEARCH_STEP:
                    result = self.public_research.execute(auth, run_id, dispatch["hold_id"])
                else:
                    tool = self.tools.get(dispatch["tool_name"])
                    result = (tool.execute_scoped(request, dispatch["id"], auth, run_id)
                              if hasattr(tool, "execute_scoped") else tool.execute(request, dispatch["id"]))
            except InferenceNoChargeError as error:
                self._record_no_charge(auth, run_id, dispatch, error.reason)
                break
            except Exception:
                # Transport failure does not prove absence of a remote effect or charge.
                with self.db.transaction() as conn:
                    receipt_auth = replace(auth, expires_at=self.clock.now() + timedelta(minutes=1))
                    current = self.repo.owned_run(conn, receipt_auth, run_id)
                    self.accounting.mark_unknown(conn, dispatch["hold_id"])
                    conn.execute("UPDATE agent_step SET state='unknown' WHERE id=?", (dispatch["id"],))
                    if current["status"] == "running":
                        self._save(conn, receipt_auth, current, self._checkpoint(conn, receipt_auth, current),
                                   status="blocked", reason="unknown_outcome")
                break
            self.record_receipt(auth, run_id, dispatch["id"], result)
            if fault:
                fault("after_receipt", dispatch)
            with self.db.transaction() as conn:
                current = self.repo.owned_run(conn, auth, run_id)
                if current["status"] != "running":
                    break
                current = self.repo.check_fence(conn, auth, run_id, worker_id, fence)
                step = dict(conn.execute("SELECT * FROM agent_step WHERE id=?", (dispatch["id"],)).fetchone())
                self._apply_received(conn, auth, current, self._checkpoint(conn, auth, current), step)
            if fault:
                fault("after_apply", dispatch)
        self.repo.release(auth, run_id, worker_id, fence)
        return self.read(auth, run_id)

    def _record_no_charge(self, auth, run_id, dispatch, reason):
        auth = replace(auth, expires_at=self.clock.now() + timedelta(minutes=1))
        with self.db.transaction() as conn:
            run = self.repo.owned_run(conn, auth, run_id)
            row = conn.execute("SELECT * FROM agent_step WHERE id=? AND run_id=?", (dispatch["id"], run_id)).fetchone()
            payload, usage = {"adapter_error": reason}, canonical_json(asdict(MeasuredUsage(0, 0, 0)))
            if not row or row["hold_id"] != dispatch["hold_id"] or row["state"] not in {"dispatching", "unknown", "applied"}:
                raise AiclError("conflict", "No dispatched operation matches this rejection.")
            if row["output_ref"]:
                if (canonical_json(self.repo.get_content(conn, auth, run_id, row["output_ref"])) != canonical_json(payload)
                        or row["usage_json"] != usage):
                    raise AiclError("conflict", "Conflicting rejection replay.")
                return
            self.accounting.reconcile_no_charge(conn, dispatch["hold_id"])
            ref = self.repo.put_content(conn, auth, run_id, "receipt", payload,
                                        identity=f"receipt:{dispatch['id']}")
            conn.execute("UPDATE agent_step SET state='applied',output_ref=?,usage_json=?,updated_at=? WHERE id=?",
                         (ref, usage, to_iso(self.clock.now()), dispatch["id"]))
            self._event(conn, auth, run, "dispatch_rejected", {"step_id": dispatch["id"], "reason": reason},
                        f"rejected:{dispatch['id']}")
            if run["status"] == "running" or (run["status"] == "blocked" and run["reason"] == "unknown_outcome"):
                self._save(conn, auth, run, self._checkpoint(conn, auth, run), status="blocked", reason=reason)

    def _local_artifact_recovery_step(self, conn, auth, run):
        """Prove an uncertain operation was only a zero-cost built-in local read."""
        def deny():
            raise AiclError("denied", "This operation needs its original adapter's reconciliation.",
                            reason="reconciliation_pending")

        run = self.repo.owned_run(conn, auth, run["id"])
        if (run["status"] not in {"blocked", "paused"}
                or run["lease_until"] and from_iso(run["lease_until"]) > self.clock.now()):
            deny()
        uncertain = conn.execute("SELECT * FROM agent_step WHERE run_id=? AND state IN ('dispatching','unknown')",
                                 (run["id"],)).fetchall()
        if len(uncertain) != 1:
            deny()
        step = dict(uncertain[0])
        tool = self.tools.get("artifact.read")
        if (step["state"] != "unknown" or step["kind"] != "tool" or step["tool_name"] != "artifact.read"
                or type(tool) is not ScopedArtifactReader or step["tool_version"] != tool.version
                or tool.version != "artifact-v5" or tool.estimate != Estimate(0, 0, 0)
                or tool.capability != "inference" or tool.repository is not self.repo
                or step["output_ref"] is not None or step["usage_json"] is not None
                or step["receipt_metadata_json"] != "{}"):
            deny()
        hold = conn.execute("SELECT h.* FROM budget_hold h JOIN agent_runtime_hold r ON r.hold_id=h.id "
                            "WHERE h.id=? AND h.instance_id=? AND h.work_id=? AND r.operation_id=? "
                            "AND r.tenant_id=? AND r.owner_id=? AND r.instance_id=h.instance_id",
                            (step["hold_id"], run["instance_id"], "runtime:" + step["id"], step["id"],
                             auth.tenant_id, auth.owner_id)).fetchone()
        if (not hold or hold["state"] != "unknown" or any(hold[key] != 0 for key in
                ("est_input_tokens", "est_output_tokens", "est_compute_minutes", "est_web_search_calls",
                 "inference_micro_usd", "compute_micro_usd"))
                or conn.execute("SELECT 1 FROM budget_usage WHERE hold_id=?", (step["hold_id"],)).fetchone()):
            deny()
        source = conn.execute("SELECT kind FROM agent_content WHERE id=? AND run_id=?",
                              (step["input_ref"], run["id"])).fetchone()
        saved = self.repo.get_content(conn, auth, run["id"], step["input_ref"])
        if (not source or source["kind"] != "dispatch_input" or type(saved) is not dict
                or saved.get("estimate") != asdict(Estimate(0, 0, 0)) or type(saved.get("request")) is not dict):
            deny()
        self.accounting._controls(conn, auth, run["instance_id"])
        tool.validate(saved["request"])
        self.repo.get_content(conn, auth, run["id"], saved["request"]["ref"])
        return step, tool, saved["request"]

    def can_reconcile_local_artifact_read(self, conn, auth, run):
        """Read-only advisory; only an explicit owner Continue executes recovery."""
        try:
            self._local_artifact_recovery_step(conn, auth, run)
            return True
        except AiclError:
            return False

    def reconcile_local_artifact_read(self, auth, run_id, expected_run_version):
        """Recover only the original local read, preserving every remote unknown.

        The built-in reader has no provider or egress, and repeats the exact
        immutable scoped request. Current controls and all receipt/hold checks
        occur in the same transaction; exceptions leave the uncertainty intact.
        This records a receipt but never schedules inference or research.
        """
        self._auth(auth)
        with self.db.transaction() as conn:
            run = self.repo.owned_run(conn, auth, run_id)
            if type(expected_run_version) is not int or expected_run_version != run["version"]:
                raise AiclError("conflict", "Refresh this run before continuing.")
            step, tool, arguments = self._local_artifact_recovery_step(conn, auth, run)
            original_status = run["status"]
            # The owner explicitly requested Continue. Stage that transition
            # atomically so the ordinary public-evidence gate can validate its
            # current queued-state authority. Nothing is visible to a worker
            # before commit, and a denied gate rolls the transition back.
            run = self._save(conn, auth, run, self._checkpoint(conn, auth, run), status="queued")
            if self._research_phase(conn, auth, run, self.repo.steps(conn, auth, run_id)):
                raise AiclError("denied", "Existing public research is required for this recovery.",
                                reason="public_research_incomplete")
            result = ScopedArtifactReader.execute_scoped(tool, arguments, step["id"], auth, run_id)
            if (not isinstance(result, AdapterResult) or result.usage != MeasuredUsage(0, 0, 0)
                    or result.bounds_exceeded or result.response_id is not None or result.model is not None):
                raise AiclError("denied", "Local read recovery returned unexpected usage.", reason="reconciliation_pending")
            self.record_receipt(auth, run_id, step["id"], result)
            received = dict(conn.execute("SELECT * FROM agent_step WHERE id=?", (step["id"],)).fetchone())
            self._apply_received(conn, auth, run, self._checkpoint(conn, auth, run), received)
            run = self.repo.owned_run(conn, auth, run_id)
            self._event(conn, auth, run, "local_read_reconciled", {"step_id": step["id"], "hold_id": step["hold_id"]},
                        "local-read-reconciled:" + step["id"])
            return self._save(conn, auth, run, self._checkpoint(conn, auth, run), status=original_status, reason=None)

    def _run_spend(self, conn, run_id):
        return conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN h.state IN ('held','unknown') THEN h.inference_micro_usd+h.compute_micro_usd "
            "ELSE COALESCE(u.inference_micro_usd+u.compute_micro_usd,0) END),0) FROM agent_step s "
            "JOIN budget_hold h ON h.id=s.hold_id LEFT JOIN budget_usage u ON u.hold_id=h.id WHERE s.run_id=?", (run_id,)).fetchone()[0]

    def _research_phase(self, conn, auth, run, steps):
        """A fixed public prelude precedes all private decisions, once per run."""
        definition = self._definition(conn, auth, run)
        release_id = definition.public_research_release_id
        if set(definition.allowed_tools) & _PUBLIC_TOOLS and not release_id:
            raise AiclError("denied", "This saved run needs an approved disclosure release.",
                            reason="disclosure_approval_required")
        if not release_id:
            return False
        if self.public_research is None:
            raise AiclError("denied", "The public research boundary is unavailable.",
                            reason="public_research_unavailable")
        # This current-authority read also gates reuse of prior evidence after
        # resume/revocation; it never sends a new public request.
        self.public_research.authorize(auth, run["id"])
        prior = [step for step in steps if step["tool_name"] == _RESEARCH_STEP]
        if prior:
            if len(prior) != 1 or prior[0]["state"] != "applied" or not prior[0]["output_ref"]:
                raise AiclError("denied", "Reconcile the existing research batch before continuing.",
                                reason="public_research_incomplete")
            payload = self.repo.get_content(conn, auth, run["id"], prior[0]["output_ref"])
            if type(payload) is not dict or "error" not in payload or payload["error"] is not None or "adapter_error" in payload:
                raise AiclError("denied", "The research batch did not complete. Start a reviewed revision run.",
                                reason="public_research_failed")
            return False
        if run["decision_count"] or any(step["kind"] == "decision" for step in steps):
            raise AiclError("denied", "Research cannot start after private analysis.",
                            reason="public_research_phase_closed")
        return True

    def _prepare_research_dispatch(self, conn, auth, run, checkpoint):
        definition, limits = self._definition(conn, auth, run), self._limits(run)
        if not self.allow_live and not getattr(self.public_research, "scripted", False):
            raise AiclError("denied", "Live public research requires explicit runtime enablement.",
                            reason="public_research_unavailable")
        # The research service validates the immutable run/release binding and
        # prices the full maximum before either planning or network dispatch.
        estimate = self.public_research.estimate(auth, run["id"])
        action_bound = self.public_research.action_bound(auth, run["id"])
        if run["action_count"] + action_bound > limits.max_actions:
            raise AiclError("denied", "Action limit reached.", reason="action_limit")
        step_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run['id']}:public-research:{definition.public_research_release_id}"))
        hold = self.accounting.reserve(conn, auth, run["instance_id"], step_id, estimate,
                                       limits.max_run_cost_micro_usd, self._run_spend(conn, run["id"]),
                                       price_version=self.public_research.price_version)
        run = self._save(conn, auth, run, checkpoint, action_count=run["action_count"] + action_bound)
        request = {"release_id": definition.public_research_release_id}
        ref = self.repo.put_content(conn, auth, run["id"], "dispatch_input",
                                    {"request": request, "estimate": asdict(estimate)}, identity=f"dispatch:{step_id}")
        sequence = conn.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM agent_step WHERE run_id=?", (run["id"],)).fetchone()[0]
        stamp = to_iso(self.clock.now())
        conn.execute("INSERT INTO agent_step (id,run_id,sequence,kind,tool_name,tool_version,input_ref,state,base_version,owner_cursor,hold_id,created_at,updated_at) "
                     "VALUES (?,?,?,'tool',?,?,?,'dispatching',?,?,?,?,?)",
                     (step_id, run["id"], sequence, _RESEARCH_STEP, self.public_research.version, ref,
                      run["version"], run["owner_cursor"], hold.id, stamp, stamp))
        return {"id": step_id, "kind": "tool", "tool_name": _RESEARCH_STEP, "hold_id": hold.id, "request": request}

    def _reuse_read(self, conn, auth, run, checkpoint, pending):
        """A fresh successful same-run read can satisfy another exact request."""
        if pending["tool_name"] in _PUBLIC_TOOLS | {_RESEARCH_STEP}:
            raise AiclError("denied", "Public requests cannot be selected by private analysis.",
                            reason="private_context_disclosure")
        tool = self.tools.get(pending["tool_name"])
        arguments = self.repo.get_content(conn, auth, run["id"], pending["input_ref"])["request"]
        if (not tool.independent_read or tool.version != pending["tool_version"]
                or arguments.get("refresh") or getattr(tool, "cache_ttl_seconds", 0) <= 0):
            return False
        definition = self._definition(conn, auth, run)
        self.accounting._controls(conn, auth, run["instance_id"])
        if hasattr(tool, "validate_scoped"):
            tool.validate_scoped(conn, auth, run, arguments)
        grant = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability=?",
                             (run["instance_id"], tool.capability)).fetchone()
        if (pending["tool_name"] not in definition.allowed_tools and pending["tool_name"] != "artifact.read") or not grant or not grant[0]:
            raise AiclError("denied", "Tool capability is disabled.", reason="capability_disabled")
        for prior in reversed(self.repo.steps(conn, auth, run["id"])):
            if (prior["kind"] != "tool" or prior["state"] != "applied" or not prior["output_ref"]
                    or prior["tool_name"] != pending["tool_name"] or prior["tool_version"] != tool.version):
                continue
            if (self.clock.now() - from_iso(prior["updated_at"])).total_seconds() > tool.cache_ttl_seconds:
                continue
            request = self.repo.get_content(conn, auth, run["id"], prior["input_ref"])["request"]
            payload = self.repo.get_content(conn, auth, run["id"], prior["output_ref"])
            if (request != arguments or not isinstance(payload, dict) or "adapter_error" in payload
                    or "error" not in payload or payload["error"] is not None):
                continue
            # Retain original observation time; reuse never refreshes cache age.
            conn.execute("UPDATE agent_step SET output_ref=?,state='received',updated_at=? WHERE id=?",
                         (prior["output_ref"], prior["updated_at"], pending["id"]))
            reused = dict(conn.execute("SELECT * FROM agent_step WHERE id=?", (pending["id"],)).fetchone())
            self._event(conn, auth, run, "read_reused", {"step_id": pending["id"], "source_step_id": prior["id"]},
                        f"reuse:{pending['id']}")
            self._apply_received(conn, auth, run, checkpoint, reused)
            return True
        return False

    def _prepare_dispatch(self, conn, auth, run, checkpoint, pending):
        definition, limits = self._definition(conn, auth, run), self._limits(run)
        if pending:
            if pending["tool_name"] in _PUBLIC_TOOLS | {_RESEARCH_STEP}:
                raise AiclError("denied", "Public requests cannot be selected by private analysis.",
                                reason="private_context_disclosure")
            action = self.repo.get_content(conn, auth, run["id"], pending["input_ref"])["request"]
            tool = self.tools.get(pending["tool_name"])
            if tool.version != pending["tool_version"] or (tool.scripted is not True and not self.allow_live):
                raise AiclError("denied", "Saved tool version is unavailable.", reason="adapter_version")
            if pending["tool_name"] not in definition.allowed_tools and pending["tool_name"] != "artifact.read":
                raise AiclError("denied", "Tool grant is missing.")
            if run["action_count"] >= limits.max_actions:
                raise AiclError("denied", "Action limit reached.", reason="action_limit")
            grant = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability=?",
                                 (run["instance_id"], tool.capability)).fetchone()
            if not grant or not grant[0]:
                raise AiclError("denied", "Tool capability is disabled.", reason="capability_disabled")
            tool.validate(action)
            if hasattr(tool, "validate_scoped"):
                tool.validate_scoped(conn, auth, run, action)
            if isinstance(tool, ScopedArtifactReader):
                self.repo.get_content(conn, auth, run["id"], action["ref"])
            adapter, kind, step_id = tool, "tool", pending["id"]
            request, changes = action, {"action_count": run["action_count"] + 1}
        else:
            if run["decision_count"] >= limits.max_decisions:
                raise AiclError("denied", "Decision limit reached.", reason="decision_limit")
            adapter, kind, step_id = self.model, "decision", str(uuid.uuid4())
            request = self._context(conn, auth, run, checkpoint)
            if hasattr(adapter, "validate_context"):
                adapter.validate_context(request)
            changes = {"decision_count": run["decision_count"] + 1}
        hold = self.accounting.reserve(conn, auth, run["instance_id"], step_id, adapter.estimate,
                                       limits.max_run_cost_micro_usd, self._run_spend(conn, run["id"]),
                                       price_version=getattr(adapter, "price_version", None))
        run = self._save(conn, auth, run, checkpoint, **changes)
        stamp = to_iso(self.clock.now())
        input_ref = self.repo.put_content(conn, auth, run["id"], "dispatch_input",
                                         {"request": request, "estimate": asdict(adapter.estimate)}, identity=f"dispatch:{step_id}")
        if pending:
            conn.execute("UPDATE agent_step SET state='dispatching',hold_id=?,input_ref=?,base_version=?,updated_at=? WHERE id=?",
                         (hold.id, input_ref, run["version"], stamp, step_id))
        else:
            sequence = conn.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM agent_step WHERE run_id=?", (run["id"],)).fetchone()[0]
            conn.execute("INSERT INTO agent_step (id,run_id,sequence,kind,tool_name,tool_version,input_ref,state,base_version,owner_cursor,hold_id,created_at,updated_at) "
                         "VALUES (?,?,?,'decision',? ,?,?,'dispatching',?,?,?,?,?)",
                         (step_id, run["id"], sequence, "model", adapter.version, input_ref, run["version"], run["owner_cursor"], hold.id, stamp, stamp))
        return {"id": step_id, "kind": kind, "tool_name": pending["tool_name"] if pending else "model",
                "hold_id": hold.id, "request": request}

    def record_receipt(self, auth, run_id, step_id, result: AdapterResult):
        """Trusted adapter receipt path: settle even if owner paused/cancelled meanwhile."""
        # A session expiring during a dispatched request cannot erase its charge.
        # This identity is valid only inside this receipt path, never for dispatch.
        auth = replace(auth, expires_at=self.clock.now() + timedelta(minutes=1))
        if not isinstance(result, AdapterResult) or type(result.bounds_exceeded) is not bool:
            raise AiclError("validation_failed", "Invalid adapter receipt.")
        try:
            serialized = canonical_json(result.payload)
            payload = result.payload if len(serialized.encode()) <= 131072 else {"adapter_error": "result_too_large"}
        except (ValueError, TypeError, UnicodeError, RecursionError):
            payload = {"adapter_error": "unserializable_result"}
        metadata = {"response_id": result.response_id, "model": result.model}
        if result.bounds_exceeded:
            metadata["bounds_exceeded"] = True
        with self.db.transaction() as conn:
            run = self.repo.owned_run(conn, auth, run_id)
            row = conn.execute("SELECT * FROM agent_step WHERE id=? AND run_id=?", (step_id, run_id)).fetchone()
            if not row or not row["hold_id"] or row["state"] not in {"dispatching", "unknown", "received", "applied", "superseded"}:
                raise AiclError("conflict", "No dispatched operation matches this receipt.")
            if row["output_ref"]:
                old = self.repo.get_content(conn, auth, run_id, row["output_ref"])
                if (canonical_json(old) != canonical_json(payload)
                        or row["usage_json"] != canonical_json(asdict(result.usage))
                        or row["receipt_metadata_json"] not in ("{}", canonical_json(metadata))):
                    raise AiclError("conflict", "Conflicting receipt replay.")
                return
            ref = self.repo.put_content(conn, auth, run_id, "receipt", payload, identity=f"receipt:{step_id}")
            self.accounting.settle(conn, row["hold_id"], result.usage)
            conn.execute("UPDATE agent_step SET output_ref=?,usage_json=?,receipt_metadata_json=?,state='received',updated_at=? WHERE id=?",
                         (ref, canonical_json(asdict(result.usage)), canonical_json(metadata), to_iso(self.clock.now()), step_id))
            estimate = self.repo.get_content(conn, auth, run_id, row["input_ref"])["estimate"]
            if result.bounds_exceeded or any(value > estimate[key] for key, value in asdict(result.usage).items()):
                if run["status"] not in _TERMINAL | {"paused"}:
                    self._save(conn, auth, run, self._checkpoint(conn, auth, run), status="blocked", reason="usage_exceeded_bound")

    def _context(self, conn, auth, run, checkpoint):
        limits = self._limits(run)
        definition = self._definition(conn, auth, run)
        messages, questions = [], {}
        for event in self.repo.events(conn, auth, run["id"]):
            payload = event["payload"]
            if event["kind"] == "question":
                questions[payload["id"]] = payload
            elif event["kind"] in {"owner_message", "owner_answer"}:
                message = deepcopy(payload)
                if event["kind"] == "owner_answer" and payload.get("question_id") in questions:
                    question = questions[payload["question_id"]]
                    message["question_context"] = {"id": question["id"], "text": question["text"][:1200],
                        "truncated": len(question["text"]) > 1200, "source": "assistant", "status": "answered"}
                messages.append(message)
        context = {"definition": definition.model_dump(mode="json"), "plan": checkpoint["plan"],
                   "memory": checkpoint["memory"], "artifacts": deepcopy(checkpoint["artifacts"]),
                   "current_time": to_iso(self.clock.now()), "run_started_at": run["created_at"],
                   "runtime_limits": {"remaining_decisions": max(0, limits.max_decisions - run["decision_count"] - 1),
                                      "remaining_actions": max(0, limits.max_actions - run["action_count"]),
                                      "remaining_draft_continuations": max(0, limits.max_draft_continuations - run["draft_count"])},
                   "owner_messages": messages, "observations": [],
                   "retrieval": {"tool": "artifact.read", "arguments": {"ref": "content reference", "offset": 0, "max_chars": 4000}},
                   "validation_error": checkpoint.get("validation_error"),
                   "progress_feedback": checkpoint.get("progress_feedback")}
        feedback = context["progress_feedback"]
        if feedback and feedback.get("code") == "redundant_evidence_reads":
            # Full proposals remain in the checkpoint/audit. Avoid duplicating
            # their selectors here: read_coverage already identifies them.
            context["progress_feedback"] = {"code": feedback["code"], "message": feedback["message"],
                "skipped_read_count": len(feedback["skipped_reads"]),
                "evidence_refs": list(dict.fromkeys(ref for item in feedback["skipped_reads"]
                                                    for ref in item["evidence_refs"]))[:8]}
        context["definition"]["allowed_tools"] = [name for name in definition.allowed_tools if name not in _PUBLIC_TOOLS]
        context["definition"].pop("public_research_release_id", None)
        steps = self.repo.steps(conn, auth, run["id"])
        results = [step for step in steps
                   if step["kind"] == "tool" and step["state"] == "applied" and step["output_ref"]]
        for step in results:
            if step["tool_name"] == _RESEARCH_STEP:
                context["public_research"] = self._research_context(conn, auth, run, step)
        if len(canonical_json(context)) > limits.max_context_chars:
            raise AiclError("denied", "Required context exceeds the configured limit.", reason="context_limit")
        for key, artifact in context["artifacts"].items():
            stored = self.repo.get_content(conn, auth, run["id"], artifact["ref"])
            excerpt = stored["content"][-4000:]
            if len(canonical_json(context)) + len(canonical_json(excerpt)) + 80 <= limits.max_context_chars:
                artifact.update(tail=excerpt, truncated=len(stored["content"]) > 4000)
            else:
                artifact["omitted"] = True
        # Identical scoped reads have identical immutable content. Keep the
        # newest prompt observation and retain the equivalent receipt refs;
        # every original step and receipt stays in the audit history.
        read_values, read_spans, equivalent_refs, seen_reads, retained = {}, {}, {}, {}, []
        for step in reversed(results):
            if step["tool_name"] == "artifact.read":
                value = self.repo.get_content(conn, auth, run["id"], step["output_ref"])
                request = self.repo.get_content(conn, auth, run["id"], step["input_ref"])["request"]
                value, compatible = self._saved_read_view(conn, auth, run, step, request, value)
                span = read_span(request, value) if compatible else None
                if span is not None:
                    read_spans[step["output_ref"]] = {**span, "receipt_ref": step["output_ref"]}
                signature = canonical_json({"request": request, "result": value})
                if signature in seen_reads:
                    equivalent_refs.setdefault(seen_reads[signature], []).append(step["output_ref"])
                    continue
                seen_reads[signature] = step["output_ref"]
                read_values[step["output_ref"]] = value
            retained.append(step)
        results = list(reversed(retained))

        def read_observation(step):
            return {"ref": step["output_ref"], "tool": "artifact.read", "result": read_values[step["output_ref"]],
                    **({"equivalent_refs": equivalent_refs[step["output_ref"]]} if step["output_ref"] in equivalent_refs else {})}

        def remaining_read_reference(step):
            return {"ref": step["output_ref"], "tool": "artifact.read", "omitted": True,
                    **({"equivalent_refs": equivalent_refs[step["output_ref"]]} if step["output_ref"] in equivalent_refs else {})}

        # Keep bounded source observations; all omitted bodies remain retrievable by ref.
        included = set()
        # Source coverage takes priority over older retrieval chunks. Previously
        # a large receipt became just its first 4k characters (usually search
        # results), hiding every fetched article behind sequential JSON reads.
        ordered = [item for item in results if item["tool_name"] == _RESEARCH_STEP]
        ordered += [item for item in reversed(results) if item["tool_name"] != _RESEARCH_STEP]
        # Reserve the whole latest action batch before filling the source
        # overview. Keeping only its last read hides other requested results
        # before the model has ever seen them and encourages repeated reads.
        remaining_references = {item["output_ref"]: {"ref": item["output_ref"], "tool": item["tool_name"], "omitted": True,
                                **({"equivalent_refs": equivalent_refs[item["output_ref"]]} if item["output_ref"] in equivalent_refs else {})}
                                for item in results}
        # Required private task state must pass the unchanged final guard
        # before trying any alternative view of untrusted public evidence.
        if not self._context_fits({**context, "observations": list(remaining_references.values())}, limits.max_context_chars):
            raise AiclError("denied", "Required context exceeds the configured limit.", reason="context_limit")
        latest_read = next((item for item in reversed(results) if item["tool_name"] == "artifact.read"), None)
        latest_model_sequence = max((item["sequence"] for item in steps
                                     if item["kind"] == "decision" and item["state"] == "applied"), default=-1)
        latest_reads = {item["output_ref"]: read_observation(item) for item in results
                        if latest_read is not None and item["tool_name"] == "artifact.read"
                        and latest_read["sequence"] > latest_model_sequence
                        and (item["origin_decision_id"] == latest_read["origin_decision_id"]
                             if latest_read["origin_decision_id"] else item["id"] == latest_read["id"])}
        # Coverage survives context pressure, independently of which bodies fit.
        # It is derived only from scoped, successful immutable read receipts;
        # neither these offsets nor the excerpts grant any new read authority.
        source_reads = {}
        for step in results:
            span = read_spans.get(step["output_ref"])
            if span is not None:
                source_reads.setdefault(span["key"], []).append(span)
        coverage = []
        latest_spans = [read_spans[ref] for ref in latest_reads if ref in read_spans]
        for spans in source_reads.values():
            last = spans[-1]
            entry = {"selector": last["selector"], "returned_ranges": merged_ranges(spans),
                     "total_chars": last["total_chars"], "receipt_ref": last["receipt_ref"],
                     "instruction_authority": "untrusted_evidence", "retained_excerpts": []}
            # Keep an older source's opening finding visible even when recent
            # multi-source reads consume the rest of the prompt. These are
            # verbatim slices, never model-generated or purportedly complete.
            for span in (spans[0], spans[-1]):
                if not span["text"]:
                    continue
                request = {**span["selector"], "offset": span["start"],
                           "max_chars": min(512, len(span["text"]))}
                if (request_covered(request, latest_spans)
                        or any(item["offset"] == span["start"] for item in entry["retained_excerpts"])):
                    continue
                entry["retained_excerpts"].append({"offset": span["start"], "text": span["text"][:512],
                                                   "receipt_ref": span["receipt_ref"]})
            coverage.append(entry)
        if coverage:
            context["read_coverage"] = {"sources": coverage,
                "body_retention": "Only retained_excerpts and visible observations are in this context. Returned ranges record prior reads, not complete retained bodies or verified facts. Reuse sourced memory; do not request covered ranges again."}
        reserved = [latest_reads.get(ref, item) for ref, item in remaining_references.items()]
        if coverage:
            # Optional old excerpts must not evict a just-requested batch or
            # weaken either the character or provider-byte preflight. Shrink
            # all sources evenly; coverage and sourced memory stay explicit.
            for excerpt_limit in (256, 128, 64, 0):
                if self._context_fits({**context, "observations": reserved}, limits.max_context_chars):
                    break
                for source in context["read_coverage"]["sources"]:
                    source["retained_excerpts"] = [{**excerpt, "text": excerpt["text"][:excerpt_limit]}
                        for excerpt in source["retained_excerpts"]] if excerpt_limit else []
        if not self._context_fits({**context, "observations": reserved}, limits.max_context_chars):
            raise AiclError("denied", "The latest read batch exceeds the context allowance.", reason="context_limit")
        # Keep useful prior reads before expanding repeated overview bodies.
        # Source identities/retrieval remain discoverable in a compact view;
        # remaining space belongs to recent distinct read results first.
        compact_research = {}
        for step in results:
            if step["tool_name"] != _RESEARCH_STEP:
                continue
            receipt = self.repo.get_content(conn, auth, run["id"], step["output_ref"])
            other_observations = [compact_research.get(ref, latest_reads.get(ref, item))
                                  for ref, item in remaining_references.items() if ref != step["output_ref"]]
            compact = self._research_overview(conn, auth, run, step, receipt, context,
                                              reserved_observations=other_observations, minimal_only=True)
            if compact is not None:
                compact_research[step["output_ref"]] = compact
        retained_reads = dict(latest_reads)
        for step in reversed(results):
            ref = step["output_ref"]
            if step["tool_name"] != "artifact.read" or ref in retained_reads:
                continue
            span = read_spans.get(ref)
            if span and request_covered({**span["selector"], "offset": span["start"], "max_chars": len(span["text"])},
                                        [read_spans[key] for key in retained_reads if key in read_spans]):
                continue
            proposed = {**retained_reads, ref: read_observation(step)}
            observations = [compact_research.get(key, proposed.get(key, item))
                            for key, item in remaining_references.items()]
            proposed_context = {**context, "observations": observations}
            if coverage:
                # A full retained observation already carries these exact
                # characters. Spend its excerpt allowance on older evidence.
                proposed_spans = [read_spans[key] for key in proposed if key in read_spans]
                projected_coverage = deepcopy(context["read_coverage"])
                for source in projected_coverage["sources"]:
                    source["retained_excerpts"] = [excerpt for excerpt in source["retained_excerpts"]
                        if not request_covered({**source["selector"], "offset": excerpt["offset"],
                                                "max_chars": len(excerpt["text"])}, proposed_spans)]
                proposed_context["read_coverage"] = projected_coverage
            if self._context_fits(proposed_context, limits.max_context_chars):
                retained_reads = proposed
                if coverage:
                    context["read_coverage"] = projected_coverage
        for step in ordered:
            if step["output_ref"] in included:
                continue
            included.add(step["output_ref"])
            remaining_references.pop(step["output_ref"], None)
            reserved_observations = [retained_reads.get(ref, item) for ref, item in remaining_references.items()]
            value = self.repo.get_content(conn, auth, run["id"], step["output_ref"])
            body = canonical_json(value)
            if step["tool_name"] == "artifact.read":
                # Do not truncate a serialized pagination object: doing so can
                # discard text while retaining an offset beyond what was shown.
                entry = read_observation(step) if step["output_ref"] in retained_reads else remaining_read_reference(step)
            else:
                entry = {"ref": step["output_ref"], "tool": step["tool_name"], "text": body[:4000], "truncated": len(body) > 4000}
                if step["tool_name"] == _RESEARCH_STEP:
                    if isinstance(value, dict) and value.get("full_evidence_ref"):
                        # Keep the complete public-evidence manifest discoverable
                        # even when the serialized inline batch excerpt is clipped.
                        entry["full_evidence_ref"] = value["full_evidence_ref"]
                        entry["public_evidence_truncated"] = True
                    complete = {**entry, "text": body, "truncated": False}
                    candidate = {**context, "observations": [complete, *context["observations"], *reserved_observations]}
                    _, omitted_links = public_evidence_preview(value)
                    if not omitted_links and self._context_fits(candidate, limits.max_context_chars):
                        entry = complete
                    else:
                        overview = self._research_overview(conn, auth, run, step, value, context,
                                                           reserved_observations=reserved_observations)
                        if overview is not None:
                            entry = overview
                        else:
                            entry = {"ref": step["output_ref"], "tool": step["tool_name"], "omitted": True,
                                     **({"full_evidence_ref": value["full_evidence_ref"]} if value.get("full_evidence_ref") else {})}
            candidate = {**context, "observations": [entry, *context["observations"], *reserved_observations]}
            if not self._context_fits(candidate, limits.max_context_chars):
                if step["output_ref"] in retained_reads:
                    raise AiclError("denied", "The latest read batch exceeds the context allowance.", reason="context_limit")
                entry = {"ref": step["output_ref"], "tool": step["tool_name"], "omitted": True,
                         **({"equivalent_refs": equivalent_refs[step["output_ref"]]} if step["output_ref"] in equivalent_refs else {})}
            if not self._context_fits({**context, "observations": [entry, *context["observations"], *reserved_observations]}, limits.max_context_chars):
                raise AiclError("denied", "Evidence references exceed context allowance.", reason="context_limit")
            context["observations"].insert(0, entry)
        order = {item["output_ref"]: index for index, item in enumerate(results)}
        context["observations"].sort(key=lambda item: order[item["ref"]])
        return context

    def _saved_read_view(self, conn, auth, run, step, request, value):
        """Keep immutable receipts; never reinterpret raw offsets as a public view."""
        reader = self.tools.get("artifact.read")
        if step["tool_version"] == reader.version:
            return value, True
        if (step["tool_version"] != "artifact-v4" or type(reader) is not ScopedArtifactReader
                or type(value) is not dict or value.get("error") is not None):
            return value, False
        selection = reader.public_projection_selection(conn, request, auth, run["id"])
        if selection is None:
            return value, False  # Private content never receives a public projection.
        # Excluding old raw discovery metadata is not permission to hide body,
        # title or configured-provider credentials in the remaining evidence.
        if hasattr(self.model, "validate_disclosure"):
            self.model.validate_disclosure(selection)
        elif _contains_secret(selection, ""):
            raise InferenceNoChargeError("sensitive_or_invalid_input")
        elif getattr(self.model, "scripted", False) is not True:
            return value, False  # Other live adapters must supply their own guard.
        current = reader.public_read_projection(conn, request, auth, run["id"])
        if (request.get("public_preview") is True
                and {key: item for key, item in current.items() if key != "reader_version"} == value):
            return value, True  # Proven identical v4 public-view coordinates only.
        return {"error": "legacy_public_read_unavailable", "ref": request["ref"],
                **({"source_index": request["source_index"]} if "source_index" in request else {}),
                "message": "This older raw read is unavailable in model context. Use the source overview's retrieval request for the current public preview; old raw offsets do not apply.",
                "text": "", "next_offset": None, "total_chars": 0}, False

    def _context_fits(self, context, maximum):
        if len(canonical_json(context)) > maximum:
            return False
        if hasattr(self.model, "validate_context"):
            try:
                self.model.validate_context(context)
            except InferenceNoChargeError as error:
                if str(error) != "context_limit":
                    raise
                return False
        return True

    def _research_overview(self, conn, auth, run, step, receipt, context, *, reserved_observations=(), minimal_only=False):
        sources = []
        if receipt.get("full_evidence_ref"):
            manifest = self.repo.get_content(conn, auth, run["id"], receipt["full_evidence_ref"])
            for ref in manifest["evidence_refs"]:
                sources.append((self.repo.get_content(conn, auth, run["id"], ref), ref, None))
        else:
            for index, source in enumerate(receipt.get("evidence", [])):
                if type(source) is not dict:
                    continue
                if source.get("evidence_ref"):
                    ref = source["evidence_ref"]
                    sources.append((self.repo.get_content(conn, auth, run["id"], ref), ref, None))
                else:
                    sources.append((source, step["output_ref"], index))

        def entry_for(limit, *, minimal=False):
            overview = source_overview(sources, text_chars=limit)
            if minimal:
                # Newly returned reads take priority over duplicated discovery
                # details. Keep source identities and scoped retrieval visible.
                overview["evidence"] = [{**{key: source[key] for key in (
                    "source_kind", "url", "title", "date_candidates", "unavailable", "reason", "instruction_authority",
                    "evidence_ref", "retrieval") if key in source}, "details_omitted": True}
                    for source in overview["evidence"]]
            entry = {"ref": step["output_ref"], "tool": _RESEARCH_STEP,
                     "text": canonical_json(overview), "truncated": True}
            if receipt.get("full_evidence_ref"):
                entry.update(full_evidence_ref=receipt["full_evidence_ref"], public_evidence_truncated=True)
            candidate = {**context, "observations": [entry, *context["observations"], *reserved_observations]}
            # Include the entire latest read batch in both bounds when available;
            # otherwise leave space for a useful read on a later turn.
            maximum = self._limits(run).max_context_chars
            ceiling = maximum - 6000 if maximum >= 12000 and not reserved_observations else maximum
            return entry if self._context_fits(candidate, ceiling) else None

        if minimal_only:
            return entry_for(0, minimal=True)
        best = entry_for(0)
        if best is None:
            return entry_for(0, minimal=True)
        low, high = 0, 8000
        while low < high:
            trial = (low + high + 1) // 2
            candidate = entry_for(trial)
            if candidate is None:
                high = trial - 1
            else:
                low, best = trial, candidate
        return best

    def _research_context(self, conn, auth, run, step, *, receipt=None):
        """Coordinator status, separate from untrusted research prose.

        A completed prelude is still real search/page access even though its
        network phase is closed before private analysis. Counts describe saved
        operations, never completeness, factual verification or new authority.
        """
        if receipt is None:
            receipt = self.repo.get_content(conn, auth, run["id"], step["output_ref"])
        if (type(receipt) is not dict or receipt.get("error") is not None
                or "error" not in receipt or "adapter_error" in receipt):
            raise AiclError("denied", "The public research receipt is incomplete.", reason="public_research_failed")
        status = {"status": "completed", "evidence_ref": step["output_ref"],
                  "successful_searches": 0, "successful_page_reads": 0, "unavailable_page_reads": 0,
                  "additional_web_requests_available": False}
        evidence = receipt.get("evidence", [])
        if receipt.get("full_evidence_ref"):
            manifest = self.repo.get_content(conn, auth, run["id"], receipt["full_evidence_ref"])
            evidence = [self.repo.get_content(conn, auth, run["id"], ref) for ref in manifest["evidence_refs"]]
        for source in evidence:
            if type(source) is not dict:
                continue
            if source.get("omitted") and source.get("evidence_ref"):
                source = self.repo.get_content(conn, auth, run["id"], source["evidence_ref"])
            if source.get("source_kind") == "public_search":
                status["successful_searches"] += 1
            elif source.get("source_kind") == "public_page":
                status["unavailable_page_reads" if source.get("unavailable") is True else "successful_page_reads"] += 1
        return status

    def _apply_received(self, conn, auth, run, checkpoint, step):
        if step["state"] != "received":
            return
        if step["kind"] == "tool":
            self._event(conn, auth, run, "tool_result", {"step_id": step["id"], "ref": step["output_ref"]}, f"result:{step['id']}")
            changes = {}
            if step["tool_name"] == _RESEARCH_STEP:
                payload = self.repo.get_content(conn, auth, run["id"], step["output_ref"])
                if type(payload) is not dict or "error" not in payload or payload["error"] is not None or "adapter_error" in payload:
                    changes = {"status": "blocked", "reason": "public_research_failed"}
            self._save(conn, auth, run, checkpoint, **changes)
            conn.execute("UPDATE agent_step SET state='applied' WHERE id=?", (step["id"],))
            return
        if step["base_version"] != run["version"] or step["owner_cursor"] != run["owner_cursor"]:
            conn.execute("UPDATE agent_step SET state='superseded' WHERE id=?", (step["id"],))
            return
        payload = self.repo.get_content(conn, auth, run["id"], step["output_ref"])
        try:
            envelope = parse_envelope(payload)
            updated = self._validate_application(conn, auth, run, checkpoint, envelope)
        except (ValueError, AiclError) as error:
            # Validation has no writes. Never partly apply a malformed envelope.
            checkpoint["validation_error"] = self._decision_feedback(payload, error)
            invalid = run["invalid_count"] + 1
            changes = {"invalid_count": invalid}
            if invalid > self._limits(run).max_invalid_decisions:
                changes.update(status="blocked", reason="invalid_decision")
            self._save(conn, auth, run, checkpoint, **changes)
            conn.execute("UPDATE agent_step SET state='applied' WHERE id=?", (step["id"],))
            self._event(conn, auth, run, "invalid_decision", {"step_id": step["id"]}, f"invalid:{step['id']}")
            return
        updated.pop("validation_error", None)
        spans, evidence_signature, read_receipts = self._progress_evidence(conn, auth, run)
        artifacts = {key: self.repo.get_content(conn, auth, run["id"], item["ref"])["content"]
                     for key, item in checkpoint["artifacts"].items()}
        prior_contents = set(artifacts.values())
        artifacts.update({item.local_ref: item.content for item in envelope.output.artifacts})
        # New receipt IDs, action ordering, memory wording and plan edits do not
        # establish new information. Artifact names/references alone do not
        # either. Compare output exactly: Markdown/code whitespace can matter.
        signature = digest({"evidence": evidence_signature, "owner_cursor": run["owner_cursor"],
                            "artifacts": sorted(set(artifacts.values()))})
        repeated = checkpoint.get("repeated_decisions", 0) + 1 if checkpoint.get("work_signature") == signature else 0
        actions, skipped = [], []
        selections = {index: self._progress_selector(conn, auth, run, action.arguments)
                      for index, action in enumerate(envelope.actions) if action.name == "artifact.read"}
        for index, action in enumerate(envelope.actions):
            if action.name != "artifact.read":
                actions.append((index, action))
                continue
            request = action.arguments
            if request["ref"] in read_receipts:
                skipped.append({"request": request, "reason": "read_receipt_wrapper",
                                "evidence_refs": [request["ref"]], "source_request": read_receipts[request["ref"]]})
                continue
            selection = selections[index]
            normalized = {**request, **selection}
            normalized.pop("source_index", None)
            if request_covered(normalized, spans):
                matching = [span for span in spans if span["selector"] == read_selector(normalized)]
                skipped.append({"request": request, "reason": "range_already_read",
                                "evidence_refs": list(dict.fromkeys(span["receipt_ref"] for span in matching))[:8]})
                continue
            start, end = request.get("offset", 0), request.get("offset", 0) + request.get("max_chars", 4000)
            covering = next((other for ordinal, other in enumerate(envelope.actions)
                             if ordinal != index and selections.get(ordinal) == selection
                             and other.arguments.get("offset", 0) <= start
                             and other.arguments.get("offset", 0) + other.arguments.get("max_chars", 4000) >= end
                             and ((other.arguments.get("offset", 0), other.arguments.get("max_chars", 4000))
                                  != (start, request.get("max_chars", 4000)) or ordinal < index)), None)
            if covering is not None:
                skipped.append({"request": request, "reason": "covered_by_batch", "evidence_refs": []})
            else:
                actions.append((index, action))
        same_owner = checkpoint.get("progress_owner_cursor") == run["owner_cursor"]
        unchanged_output = not any(item.content not in prior_contents
                                   for item in envelope.output.artifacts)
        redundant_only = bool(skipped) and not actions and unchanged_output
        strikes = (checkpoint.get("redundant_read_decisions", 0) if same_owner else 0) + 1 if redundant_only else 0
        updated.update(work_signature=signature, repeated_decisions=repeated,
                       progress_owner_cursor=run["owner_cursor"], redundant_read_decisions=strikes)
        updated.pop("progress_feedback", None)
        if skipped:
            updated["progress_feedback"] = {
                "code": "redundant_evidence_reads", "skipped_reads": skipped,
                "message": "Redundant evidence reads were not dispatched. Use original source requests, not read-receipt wrappers. "
                           "Use retained evidence and findings to write the result, or request a genuinely unread range. "
                           "Repeating a read-only decision without new information or output stops this run."}
            self._event(conn, auth, run, "reads_suppressed", {"step_id": step["id"], "reads": skipped},
                        f"reads-suppressed:{step['id']}")
        elif repeated == 1:
            updated["progress_feedback"] = {
                "code": "no_new_information", "skipped_reads": [],
                "message": "The last actions added no new evidence or output. Use the saved findings to finish, "
                           "or request genuinely new information. Another unchanged decision stops this run."}
        stopped = (strikes >= 2 or repeated >= 2) and envelope.control.next in {"continue", "continue_draft"}
        for artifact in envelope.output.artifacts:
            prior = checkpoint["artifacts"].get(artifact.local_ref)
            ref = self.repo.put_content(conn, auth, run["id"], "artifact", artifact.model_dump(mode="json"),
                                        identity=f"artifact:{step['id']}:{artifact.local_ref}")
            updated["artifacts"][artifact.local_ref] = {"ref": ref, "version": (prior["version"] + 1) if prior else 1}
        if envelope.output.message:
            self._event(conn, auth, run, "assistant_message", {"text": envelope.output.message}, f"message:{step['id']}")
        # Valid findings, plan and output survive a bounded no-progress stop.
        # Suppression is a refusal, not cache reuse or a new authorized read.
        if stopped:
            self._save(conn, auth, run, updated, status="blocked", reason="no_progress")
            conn.execute("UPDATE agent_step SET state='applied' WHERE id=?", (step["id"],))
            return
        control, changes = envelope.control, {}
        if control.next == "continue":
            sequence = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM agent_step WHERE run_id=?", (run["id"],)).fetchone()[0]
            stamp = to_iso(self.clock.now())
            for sequence_offset, (ordinal, action) in enumerate(actions):
                child = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{step['id']}:action:{ordinal}"))
                tool = self.tools.get(action.name)
                ref = self.repo.put_content(conn, auth, run["id"], "action", {"request": action.arguments}, identity=f"action:{child}")
                conn.execute("INSERT INTO agent_step (id,run_id,sequence,kind,origin_decision_id,action_ordinal,tool_name,tool_version,input_ref,state,base_version,owner_cursor,created_at,updated_at) "
                             "VALUES (?,?,?,'tool',?,?,?,?,?,'prepared',?,?,?,?)",
                             (child, run["id"], sequence + sequence_offset + 1, step["id"], ordinal, action.name, tool.version,
                              ref, run["version"] + 1, run["owner_cursor"], stamp, stamp))
        elif control.next == "wait_owner":
            question = {"id": f"question:{step['id']}", "text": control.question, "options": control.options}
            updated["question"] = question
            self._event(conn, auth, run, "question", question, question["id"])
            changes.update(status="waiting_owner", reason=None)
        elif control.next == "complete":
            updated["completed_artifacts"] = control.artifact_refs
            updated["criterion_assessments"] = [item.model_dump(mode="json") for item in control.criterion_assessments]
            changes.update(status="completed", reason=None)
        elif control.next == "blocked":
            changes.update(status="blocked", reason=control.reason)
        elif control.next == "continue_draft":
            changes.update(draft_count=run["draft_count"] + 1)
        self._save(conn, auth, run, updated, **changes)
        conn.execute("UPDATE agent_step SET state='applied' WHERE id=?", (step["id"],))

    def _progress_selector(self, conn, auth, run, request):
        """Content identity collapses aliases without creating disclosure authority."""
        reader = self.tools.get("artifact.read")
        if type(reader) is ScopedArtifactReader:
            projected = reader.public_projection_selection(conn, request, auth, run["id"])
            if projected is not None:
                selector = read_selector({**request, "public_preview": True})
                selector.pop("source_index", None)
                selector["ref"] = "content:" + digest(projected)
                return selector
        payload = self.repo.get_content(conn, auth, run["id"], request["ref"])
        if "source_index" in request:
            index = request["source_index"]
            if (type(payload) is not dict or payload.get("error") is not None or "error" not in payload
                    or type(payload.get("evidence")) is not list or index >= len(payload["evidence"])):
                return {"ref": request["ref"], "selection_error": index}
            payload = payload["evidence"][index]
        # Keep unsupported public-preview requests distinct from supported ones.
        # Shape alone is not authority, even for progress/suppression decisions.
        if request.get("public_preview") is True:
            record = conn.execute("SELECT kind FROM agent_content WHERE id=? AND run_id=?",
                                  (request["ref"], run["id"])).fetchone()
            public_receipt = conn.execute("SELECT 1 FROM agent_step WHERE run_id=? AND tool_name='public.research' "
                                          "AND state='applied' AND output_ref=?", (run["id"], request["ref"])).fetchone()
            if record["kind"] != "public_research_source" and not public_receipt:
                return read_selector(request)
        selector = read_selector(request)
        selector.pop("source_index", None)
        selector["ref"] = "content:" + digest(payload)
        return selector

    def _progress_evidence(self, conn, auth, run):
        """Measure observed information, never receipt creation or claimed progress.

        The immutable content/representation and actual returned range identify
        artifact evidence. All reads here retain repository owner/run checks;
        the result can only suppress work, never grant access or dispatch it.
        """
        spans, other, read_receipts = [], set(), {}
        steps = [item for item in self.repo.steps(conn, auth, run["id"])
                 if item["kind"] == "tool" and item["state"] == "applied" and item["output_ref"]]
        for item in steps:
            if item["tool_name"] == "artifact.read":
                read_receipts[item["output_ref"]] = self.repo.get_content(conn, auth, run["id"], item["input_ref"])["request"]
        for item in steps:
            payload = self.repo.get_content(conn, auth, run["id"], item["output_ref"])
            if item["tool_name"] == "artifact.read":
                request = read_receipts[item["output_ref"]]
                if request["ref"] in read_receipts:
                    continue  # Wrappers and obsolete projections cannot manufacture current coverage.
                payload, compatible = self._saved_read_view(conn, auth, run, item, request, payload)
                span = read_span(request, payload) if compatible else None
                if span is not None:
                    selector = self._progress_selector(conn, auth, run, request)
                    spans.append({**span, "key": canonical_json(selector), "selector": selector,
                                  "receipt_ref": item["output_ref"]})
                # Failed selections do not become new evidence merely because
                # they have another receipt or slightly different arguments.
                continue
            other.add(digest({"tool": item["tool_name"], "payload": payload}))
        groups = {}
        for span in spans:
            groups.setdefault(span["key"], []).append(span)
        coverage = {key: {"ranges": merged_ranges(values),
                          "totals": sorted({value["total_chars"] for value in values})}
                    for key, values in groups.items()}
        return spans, {"coverage": coverage, "other": sorted(other)}, read_receipts

    def _validate_application(self, conn, auth, run, checkpoint, envelope):
        updated = deepcopy(checkpoint)
        definition, limits = self._definition(conn, auth, run), self._limits(run)
        requirements = {item.id for item in definition.requirements}
        if any(action.name in _PUBLIC_TOOLS | {_RESEARCH_STEP} for action in envelope.actions):
            raise AiclError("denied", "Public requests cannot be selected by private analysis.",
                            reason="private_context_disclosure")
        self.tools.validate_batch(envelope.actions, definition.allowed_tools, allow_live=self.allow_live)
        for action in envelope.actions:
            if action.name == "artifact.read":
                self.repo.get_content(conn, auth, run["id"], action.arguments["ref"])
                if action.arguments.get("public_preview") or "field" in action.arguments:
                    reader = self.tools.get("artifact.read")
                    if (type(reader) is ScopedArtifactReader and
                            reader.public_projection_selection(conn, action.arguments, auth, run["id"]) is None):
                        raise AiclError("validation_failed", "Public previews require saved public research evidence.")

        def evidence(refs):
            for ref in refs:
                # Scope check also rejects another run's opaque IDs.
                self.repo.get_content(conn, auth, run["id"], ref)

        for write in envelope.output.artifacts:
            evidence(write.evidence_refs)
        for update in envelope.memory_updates:
            evidence(update.evidence_refs)
            if update.op == "remove":
                updated["memory"].pop(update.key, None)
            else:
                updated["memory"][update.key] = {**update.model_dump(mode="json"), "authority": "derived"}
        if len(updated["memory"]) > 64:
            raise ValueError("memory limit")
        if envelope.plan_patch:
            for key in envelope.plan_patch.remove:
                updated["plan"].pop(key, None)
            for item in envelope.plan_patch.upsert:
                if not set(item.requirement_ids) <= requirements:
                    raise ValueError("unknown owner requirement")
                evidence(item.evidence_refs)
                updated["plan"][item.id] = item.model_dump(mode="json")
        plan = updated["plan"]
        if len(plan) > 64:
            raise ValueError("plan limit")
        visited, stack = set(), set()

        def visit(key):
            if key not in plan or key in stack:
                raise ValueError("missing/cyclic dependency")
            if key in visited:
                return
            stack.add(key)
            for dependency in plan[key]["dependency_ids"]:
                visit(dependency)
            stack.remove(key)
            visited.add(key)

        for key in plan:
            visit(key)
        for action in envelope.actions:
            if action.plan_item_id is not None and action.plan_item_id not in plan:
                raise ValueError("unknown plan item")
        artifacts = set(checkpoint["artifacts"]) | {item.local_ref for item in envelope.output.artifacts}
        if len(artifacts) > 64:
            raise ValueError("artifact limit")
        control = envelope.control
        if control.next == "complete":
            assessments = {item.requirement_id: item for item in control.criterion_assessments}
            if set(assessments) != requirements or any(item.status != "met" for item in assessments.values()):
                raise ValueError("owner requirements are unmet")
            if not set(control.artifact_refs) <= artifacts or checkpoint["question"]:
                raise ValueError("missing output or unanswered question")
            if any(item["state"] not in {"completed", "superseded"} for item in plan.values()):
                raise ValueError("unfinished plan work")
            if conn.execute("SELECT 1 FROM agent_step WHERE run_id=? AND state IN ('prepared','dispatching','unknown')", (run["id"],)).fetchone():
                raise ValueError("pending work")
            for assessment in assessments.values():
                evidence(assessment.evidence_refs)
        elif control.next == "blocked":
            if not set(control.partial_artifact_refs) <= artifacts:
                raise ValueError("missing partial output")
        elif control.next == "continue_draft":
            if run["draft_count"] >= limits.max_draft_continuations:
                raise ValueError("draft continuation limit")
            if not set(control.requirement_ids) <= requirements:
                raise ValueError("unknown owner requirement")
            changed = False
            for artifact in envelope.output.artifacts:
                prior = checkpoint["artifacts"].get(artifact.local_ref)
                if prior is None or self.repo.get_content(conn, auth, run["id"], prior["ref"])["content"] != artifact.content:
                    changed = True
            if not changed:
                raise ValueError("unchanged draft")
        return updated

    @staticmethod
    def _decision_feedback(payload, error):
        """Bounded repair feedback, never model text or exception contents.

        Provider diagnostics are persisted data too: revalidate their finite
        vocabulary before including them in a subsequent model context.
        """
        if type(payload) is dict and "adapter_error" in payload:
            diagnostic = sanitize_validation_error(payload.get("validation_error"))
            if diagnostic is not None:
                return diagnostic
            return ("invalid_decision: the previous provider reply could not be accepted. "
                    "Return one complete decision matching the supplied schema and control rules. "
                    "No changes from that reply were applied; reuse the saved evidence.")
        if isinstance(error, ValidationError):
            return contract_validation_error(error)
        # Only exact, application-owned messages select a hint. Never forward
        # exception messages, missing references or arbitrary rejected values.
        hints = {
            "memory limit": "Keep at most 64 memory entries.",
            "unknown owner requirement": "Use only the owner requirement IDs supplied in the saved definition.",
            "plan limit": "Keep at most 64 plan items.",
            "missing/cyclic dependency": "Plan dependencies must exist and must not form a cycle.",
            "unknown plan item": "Use an existing plan item ID, add it in this plan patch, or use null.",
            "artifact limit": "Keep at most 64 artifacts.",
            "owner requirements are unmet": "Assess every owner requirement as met before completing; otherwise continue or explain the blocker.",
            "missing output or unanswered question": "Complete only with saved or newly written artifact names and no pending owner question.",
            "unfinished plan work": "Complete or supersede unfinished plan items before completing the run.",
            "pending work": "Do not complete while accepted work remains pending.",
            "missing partial output": "Use saved or newly written artifact names for partial outputs.",
            "draft continuation limit": "remaining_draft_continuations is exhausted. Write final artifacts with complete if all owner requirements are met; otherwise report the precise blocker.",
            "unchanged draft": "A draft continuation must change artifact content.",
            "Agent content not found.": "Use only saved content references supplied in this run; URLs and invented IDs are not evidence references.",
            "Public requests cannot be selected by private analysis.": "Use saved research in this phase; do not request search or page tools.",
            "tool is outside this run's grants": "Request only tools listed in available_tools.",
            "tool is unavailable": "Request only tools listed in available_tools.",
        }
        message = error.message if isinstance(error, AiclError) else str(error)
        hint = hints.get(message, "Check the supplied schema, saved evidence references, owner requirement IDs and available tools.")
        return "invalid_decision: " + hint + " No changes from that reply were applied."

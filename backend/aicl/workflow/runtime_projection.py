"""Owner-scoped audit views over the durable runtime's existing evidence.

This is a read model, not a second execution or accounting path. It never
dispatches work, writes an audit event, settles a hold, or interprets a model's
completion claim as an owner review. Content reads retain repository integrity
and ownership checks, including when the worker is unavailable after a restart.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from urllib.parse import quote

from aicl.agent_runtime.storage import Repository
from aicl.control.errors import AiclError
from aicl.workflow.cost_projection import cost_line, cost_summary


PREFIX = "runtime:"


@contextmanager
def audit_reader(db):
    """Observe one committed snapshot, or the caller's existing transaction."""
    with db.reader() as conn:
        owns_snapshot = not conn.in_transaction
        if owns_snapshot:
            conn.execute("BEGIN")
        try:
            yield conn
        finally:
            if owns_snapshot:
                conn.execute("ROLLBACK")


class RuntimeAuditProjection:
    def __init__(self, db, clock):
        self.repo = Repository(db, clock)

    def _source_url(self, conn, auth, run):
        workspace = conn.execute(
            "SELECT w.id FROM agent_workspace_run x JOIN agent_workspace w ON w.id=x.workspace_id "
            "WHERE x.run_id=? AND w.instance_id=? AND w.tenant_id=? AND w.owner_id=?",
            (run["id"], run["instance_id"], auth.tenant_id, auth.owner_id)).fetchone()
        if workspace:
            return "/agent-workspaces/" + quote(workspace["id"], safe="")
        chat = conn.execute(
            "SELECT s.id FROM agent_chat_run x JOIN assistant_session s ON s.id=x.session_id "
            "WHERE x.run_id=? AND s.tenant_id=? AND s.owner_id=?",
            (run["id"], auth.tenant_id, auth.owner_id)).fetchone()
        return "/chat?session=" + quote(chat["id"], safe="") if chat else None

    @staticmethod
    def _details_url(run_id, step_id):
        return "/api/audit/runs/" + quote(run_id, safe="") + "/steps/" + quote(step_id, safe="")

    def _steps(self, conn, auth, run, *, step_id=None):
        result = []
        for row in self.repo.steps(conn, auth, run["id"]):
            if step_id is not None and row["id"] != step_id:
                continue
            receipt = self.repo.get_content(conn, auth, run["id"], row["output_ref"]) if row["output_ref"] else None
            metadata = json.loads(row["receipt_metadata_json"])
            usage = json.loads(row["usage_json"]) if row["usage_json"] else None
            measured = conn.execute(
                "SELECT u.* FROM budget_usage u JOIN agent_runtime_hold h ON h.hold_id=u.hold_id "
                "WHERE h.hold_id=? AND h.operation_id=? AND h.instance_id=? AND h.tenant_id=? AND h.owner_id=?",
                (row["hold_id"], row["id"], run["instance_id"], auth.tenant_id, auth.owner_id)).fetchone()
            if usage is not None:
                usage = {**usage, "input_tokens": usage["inference_input_tokens"],
                         "output_tokens": usage["inference_output_tokens"],
                         "cost_micro_usd": measured["inference_micro_usd"] + measured["compute_micro_usd"] if measured else None}
            # Execution state is separate from a returned tool/application error.
            error = next((receipt[key] for key in ("adapter_error", "error") if receipt.get(key)), None) if isinstance(receipt, dict) else None
            result.append({key: row[key] for key in ("id", "sequence", "kind", "tool_name", "tool_version", "state",
                                                    "created_at", "updated_at", "hold_id", "output_ref")} | {
                "details_url": self._details_url(run["id"], row["id"]),
                "usage": usage,
                "receipt_metadata": metadata, "error": str(error) if error is not None else None,
                "provenance": "fixture" if str(row["tool_version"]).startswith("scripted-") else
                              "provider_reported" if metadata.get("model") else "application_record"})
        return result

    def _detail_content(self, conn, auth, run_id, ref, kinds):
        """Read only explicitly linked, scoped immutable records of known kinds."""
        if not isinstance(ref, str) or not 1 <= len(ref) <= 240:
            raise AiclError("unavailable", "Stored action evidence has an invalid reference.")
        content = self.repo.get_content(conn, auth, run_id, ref)
        row = conn.execute("SELECT kind FROM agent_content WHERE id=? AND tenant_id=? AND owner_id=? AND run_id=?",
                           (ref, auth.tenant_id, auth.owner_id, run_id)).fetchone()
        if row is None or row["kind"] not in kinds:
            raise AiclError("unavailable", "Stored action evidence has an invalid content type.")
        return content

    @staticmethod
    def _retained(content, *, label, ref=None, note=None):
        return {"status": "retained", "label": label, "content_ref": ref, "content": content, "note": note}

    @staticmethod
    def _missing(label, note):
        return {"status": "not_retained", "label": label, "content_ref": None, "content": None, "note": note}

    def _research_records(self, conn, auth, run, row, receipt):
        records = []
        # Journals are immutable, owner/run scoped, and joined only within the
        # selected hold. Historical usage-only records stay explicitly partial.
        kinds = {"public_research_planner_request", "public_research_planner_receipt",
                 "public_research_request", "public_research_response"}
        planners, requests = {}, {}
        for saved in conn.execute(
                "SELECT id,kind,created_at,rowid AS ordering FROM agent_content WHERE tenant_id=? AND owner_id=? AND run_id=? "
                "AND kind IN ('public_research_planner_request','public_research_planner_receipt',"
                "'public_research_request','public_research_response') ORDER BY rowid",
                (auth.tenant_id, auth.owner_id, run["id"])):
            payload = self._detail_content(conn, auth, run["id"], saved["id"], kinds)
            if not isinstance(payload, dict):
                raise AiclError("unavailable", "Stored research evidence has an invalid shape.")
            if payload.get("hold_id") != row["hold_id"]:
                continue
            planner = saved["kind"].startswith("public_research_planner_")
            key = payload.get("round") if planner else payload.get("request_id")
            if ((planner and (type(key) is not int or key < 1))
                    or (not planner and (not isinstance(key, str) or not 1 <= len(key) <= 240))):
                raise AiclError("unavailable", "Stored research evidence has an invalid identity.")
            group = planners if planner else requests
            pair = group.setdefault(key, {"ordering": saved["ordering"], "created_at": saved["created_at"]})
            side = "request" if saved["kind"].endswith("_request") else "response"
            if side in pair:
                raise AiclError("unavailable", "Stored research evidence has duplicate records.")
            pair[side] = {"payload": payload, "ref": saved["id"]}
        for round_number, pair in planners.items():
            sent, returned = pair.get("request"), pair.get("response")
            sent_payload, returned_payload = sent["payload"] if sent else {}, returned["payload"] if returned else {}
            records.append({"kind": "research_planner", "label": "Research planning round " + str(round_number),
                "content_ref": returned["ref"] if returned else sent["ref"], "ordering": pair["ordering"],
                "request": self._retained(sent_payload["context"], label="Saved planner context", ref=sent["ref"],
                    note="Exact research planner adapter context; the provider HTTP envelope was not retained.")
                    if "context" in sent_payload else self._missing("Planner context", "This older record retained usage only, not the planner context."),
                "response": self._retained(returned_payload["result"], label="Saved planner result", ref=returned["ref"],
                    note="The parsed planner response, not the raw provider HTTP response.")
                    if "result" in returned_payload else self._missing("Planner response", "The planner response was not retained in this record."),
                "metadata": {"recorded_at": pair["created_at"], **{key: returned_payload[key] for key in
                    ("round", "model", "response_id", "usage", "status", "bounds_exceeded") if key in returned_payload}}})
        for request_id, pair in requests.items():
            sent, returned = pair.get("request"), pair.get("response")
            sent_payload, returned_payload = sent["payload"] if sent else {}, returned["payload"] if returned else {}
            kind = sent_payload.get("kind", returned_payload.get("kind"))
            if kind not in {"search", "page"} or (sent and returned and sent_payload.get("kind") != returned_payload.get("kind")):
                raise AiclError("unavailable", "Stored research evidence has mismatched request types.")
            if (sent and not isinstance(sent_payload.get("request"), dict)) or (returned and not isinstance(returned_payload.get("response"), dict)):
                raise AiclError("unavailable", "Stored research evidence has an invalid shape.")
            records.append({"kind": "research_network", "label": "Web search" if kind == "search" else "Page request",
                "content_ref": returned["ref"] if returned else sent["ref"], "ordering": pair["ordering"],
                "request": self._retained(sent_payload["request"], label="Authorized network request", ref=sent["ref"],
                    note="Exact approved URL, method and public headers before broker credentials were injected.")
                    if sent else self._missing("Network request", "The exact network request was not retained."),
                "response": self._retained(returned_payload["response"], label="Broker response and extracted evidence", ref=returned["ref"],
                    note="Saved broker status and extracted untrusted evidence; raw HTTP headers and bodies were not retained.")
                    if returned else self._missing("Network response", "No response was recorded; the outcome may be unknown."),
                "metadata": {"request_id": request_id, "recorded_at": pair["created_at"], "instruction_authority": "untrusted_evidence"}})
        records.sort(key=lambda item: item["ordering"])
        for record in records:
            record.pop("ordering")
        if not isinstance(receipt, dict):
            return records
        evidence = receipt.get("evidence", [])
        refs = None
        if receipt.get("full_evidence_ref"):
            manifest = self._detail_content(conn, auth, run["id"], receipt["full_evidence_ref"], {"public_research_evidence"})
            if not isinstance(manifest, dict) or not isinstance(manifest.get("evidence_refs"), list):
                raise AiclError("unavailable", "Stored research evidence has an invalid manifest.")
            refs = manifest["evidence_refs"]
            if len(refs) > 30 or any(not isinstance(ref, str) for ref in refs):
                raise AiclError("unavailable", "Stored research evidence has an invalid manifest.")
            evidence = [self._detail_content(conn, auth, run["id"], ref, {"public_research_source"}) for ref in refs]
        if not isinstance(evidence, list) or len(evidence) > 30:
            raise AiclError("unavailable", "Stored research evidence has an invalid shape.")
        for index, source in enumerate(evidence):
            ref = refs[index] if refs is not None else None
            if isinstance(source, dict) and source.get("evidence_ref") and refs is None:
                ref = source["evidence_ref"]
                source = self._detail_content(conn, auth, run["id"], ref, {"public_research_source"})
            if not isinstance(source, dict):
                raise AiclError("unavailable", "Stored research evidence has an invalid source.")
            label = "Search results" if source.get("source_kind") == "public_search" else "Page evidence"
            records.append({"kind": "research_evidence", "label": label + " " + str(index + 1), "content_ref": ref,
                "request": self._missing("Network request", "This is evidence supplied to the agent; captured network requests are listed separately."
                                         if requests else "The exact network request was not retained with this historical evidence."),
                "response": self._retained(source, label="Extracted public evidence", ref=ref,
                    note="Saved untrusted source content. This is the extracted result, not a raw HTTP response."),
                "metadata": {"instruction_authority": "untrusted_evidence"}})
        return records

    def step_details(self, conn, auth, run_id, step_id):
        """Owner-only request/response inspection; no execution or accounting writes."""
        run = self.repo.owned_run(conn, auth, run_id)
        row = conn.execute("SELECT * FROM agent_step WHERE id=? AND run_id=?", (step_id, run_id)).fetchone()
        if row is None:
            raise AiclError("not_found", "Action not found.")
        step, = self._steps(conn, auth, run, step_id=step_id)
        name = conn.execute("SELECT name FROM agent_instance WHERE id=?", (run["instance_id"],)).fetchone()["name"]
        step["cost_summary"] = cost_summary([cost for cost in self.costs(conn, auth, run["instance_id"], name, run_id=run_id)
                                             if cost["step_id"] == step_id])
        labels = {"public.research": "Public web research", "artifact.read": "Read saved evidence",
                  "web.search": "Web search", "web.read": "Read public page"}
        step["label"] = "Model decision" if step["kind"] == "decision" else labels.get(step["tool_name"], "Tool: " + step["tool_name"])
        model = row["kind"] == "decision"
        request = self._missing("Saved model context" if model else "Saved tool arguments", "No request was retained for this action.")
        if row["input_ref"]:
            stored = self._detail_content(conn, auth, run_id, row["input_ref"], {"dispatch_input", "action"})
            if not isinstance(stored, dict) or "request" not in stored:
                raise AiclError("unavailable", "Stored action request has an invalid shape.")
            request = self._retained(stored["request"], label=request["label"], ref=row["input_ref"],
                note=("Exact context saved at the model adapter boundary. The provider's full HTTP body, system prompt and headers were not retained."
                      if model else "Exact arguments saved at the application tool boundary. These are not a raw network request."))
            request["estimate"] = stored.get("estimate")
        response = self._missing("Saved adapter response", "This prepared action has not been dispatched."
                                 if row["state"] == "prepared" else "No response was recorded. The outcome may still be pending or unknown.")
        receipt = None
        if row["output_ref"]:
            receipt = self._detail_content(conn, auth, run_id, row["output_ref"], {"receipt"})
            response = self._retained(receipt, label="Saved adapter response", ref=row["output_ref"],
                note="The returned application payload, retained exactly as recorded; not a raw provider HTTP response.")
        limitations = ["Provider authentication headers are excluded from captured network requests; raw HTTP responses are not retained.",
                      "Recorded charges and unresolved reservations remain separate; inspecting details does not rerun an action."]
        records = self._research_records(conn, auth, run, row, receipt) if row["tool_name"] == "public.research" else []
        for event in self.repo.events(conn, auth, run_id):
            payload = event["payload"]
            if event["kind"] == "read_reused" and isinstance(payload, dict) and payload.get("step_id") == step_id:
                source_id = payload.get("source_step_id")
                if not any(previous["id"] == source_id for previous in self.repo.steps(conn, auth, run_id)):
                    raise AiclError("unavailable", "Stored reuse evidence refers to an invalid action.")
                limitations.append("This action reused a previously saved read result; it did not make another provider request.")
                step["reused_from_step_id"] = source_id
        return {"schema_version": 1, "run_id": run_id, "step": step, "request": request,
                "response": response, "records": records, "limitations": limitations}

    def _outputs(self, conn, auth, run, name, definition, checkpoint, steps, source_url):
        result, versions = [], {}
        by_evidence = {step["output_ref"]: step for step in steps if step["output_ref"]}
        requirements = definition.get("requirements", [])
        # Artifacts are saved only by a successfully applied decision, unlike
        # raw receipts which can be superseded, invalid, or never applied.
        for row in conn.execute(
                "SELECT id,created_at FROM agent_content WHERE tenant_id=? AND owner_id=? AND run_id=? "
                "AND kind='artifact' ORDER BY rowid", (auth.tenant_id, auth.owner_id, run["id"])):
            artifact = self.repo.get_content(conn, auth, run["id"], row["id"])
            local_ref = artifact["local_ref"]
            versions[local_ref] = versions.get(local_ref, 0) + 1
            latest = checkpoint.get("artifacts", {}).get(local_ref, {}).get("ref") == row["id"]
            complete = latest and local_ref in checkpoint.get("completed_artifacts", [])
            evidence = []
            for ref in artifact.get("evidence_refs", []):
                # Verify every saved evidence reference belongs to this owner/run.
                self.repo.get_content(conn, auth, run["id"], ref)
                step = by_evidence.get(ref)
                evidence.append({"ref": ref, "step_id": step["id"] if step else None,
                                 "tool_name": step["tool_name"] if step else "Saved run content",
                                 "state": step["state"] if step else "saved"})
            result.append({"id": PREFIX + run["id"] + ":" + row["id"], "runtime": True,
                "runtime_run_id": run["id"], "instance_id": run["instance_id"], "agent_name": name,
                "run_id": PREFIX + run["id"], "spec_key": local_ref, "name": local_ref,
                "content": artifact["content"], "state": "completed" if complete else "draft",
                "version": versions[local_ref], "latest": latest, "created_at": row["created_at"],
                "goal": definition["objective"], "criteria": [], "requirements": requirements,
                "criterion_assessments": checkpoint.get("criterion_assessments", []) if complete else [],
                "evidence_refs": artifact.get("evidence_refs", []), "evidence": evidence,
                "reviewed_at": None, "feedback": "", "config_version": None,
                "config_snapshot": {"scenario": "runtime", "goal": definition["objective"]},
                "inference": None, "legacy": False, "next_due": None, "source_url": source_url})
        return list(reversed(result))

    def costs(self, conn, auth, instance_id, name, *, run_id=None):
        result = []
        for row in conn.execute(
                "SELECT r.hold_id,h.state,h.created_at,h.inference_micro_usd AS reserved_inference,h.compute_micro_usd AS reserved_compute,"
                "u.inference_micro_usd,u.compute_micro_usd,u.recorded_at,u.inference_input_tokens,u.inference_output_tokens,"
                "u.web_search_calls,u.compute_minutes,h.price_table_version,s.run_id,s.id AS step_id,s.tool_version,s.receipt_metadata_json "
                "FROM agent_runtime_hold r JOIN budget_hold h ON h.id=r.hold_id AND h.instance_id=r.instance_id "
                "LEFT JOIN budget_usage u ON u.hold_id=r.hold_id AND u.instance_id=r.instance_id "
                "LEFT JOIN agent_step s ON s.hold_id=r.hold_id AND s.id=r.operation_id "
                "LEFT JOIN agent_run a ON a.id=s.run_id AND a.instance_id=r.instance_id "
                "AND a.tenant_id=r.tenant_id AND a.owner_id=r.owner_id "
                "WHERE r.tenant_id=? AND r.owner_id=? AND r.instance_id=? AND (s.id IS NULL OR a.id IS NOT NULL) "
                "AND (u.hold_id IS NOT NULL OR h.state IN ('held','unknown')) AND (? IS NULL OR s.run_id=?)",
                (auth.tenant_id, auth.owner_id, instance_id, run_id, run_id)):
            metadata = json.loads(row["receipt_metadata_json"] or "{}")
            held = row["state"] in ("held", "unknown")
            for column, category in (("inference_micro_usd", "Inference usage"), ("compute_micro_usd", "Compute usage")):
                amount = row["reserved_inference" if column == "inference_micro_usd" else "reserved_compute"] if held else row[column]
                if held:
                    category = category.replace("usage", "reservation")
                # Zero-cost steps still appear in Actions, not as invented spend.
                if not amount:
                    continue
                result.append(cost_line({"id": PREFIX + row["hold_id"] + ":" + column, "created_at": row["created_at"] if held else row["recorded_at"],
                    "agent_name": name, "instance_id": instance_id, "category": category,
                    "amount_usd": amount / 1_000_000, "amount_micro_usd": amount,
                    "status": row["state"] if held else "Settled", "run_id": PREFIX + row["run_id"] if row["run_id"] else None,
                    "step_id": row["step_id"], "hold_id": row["hold_id"], "model": metadata.get("model"),
                    "input_tokens": row["inference_input_tokens"], "output_tokens": row["inference_output_tokens"],
                    "web_search_calls": row["web_search_calls"], "compute_minutes": row["compute_minutes"],
                    "price_table_version": row["price_table_version"],
                    "evidence_url": "/audit/jobs/" + quote(PREFIX + row["run_id"], safe="") + "#step-" + quote(row["step_id"], safe="")
                                    if row["run_id"] else "/instances/" + quote(instance_id, safe=""),
                    "provenance": "fixture" if str(row["tool_version"]).startswith("scripted-") else
                                  "provider_reported" if metadata.get("model") else "application_record"}))
        return result

    def activity_log(self, conn, auth, run_id):
        """Compact work attachment over the same steps and ledger as the audit.

        Keep evidence references as owner-authenticated audit links, not copied
        requests or receipt bodies. Missing measured usage stays null; a pending
        reservation is never relabeled as a charge. This needs no live runtime.
        """
        run = self.repo.owned_run(conn, auth, run_id)
        name = conn.execute("SELECT name FROM agent_instance WHERE id=?", (run["instance_id"],)).fetchone()["name"]
        costs = self.costs(conn, auth, run["instance_id"], name, run_id=run_id)
        audit_url = "/audit/jobs/" + quote(PREFIX + run_id, safe="")
        labels = {"public.research": "Public web research", "artifact.read": "Read saved evidence",
                  "web.search": "Web search", "web.read": "Read public page"}
        totals = {"model_decisions": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0, "web_search_calls": 0}
        steps = []
        for step in self._steps(conn, auth, run):
            usage = step["usage"]
            if usage is not None:
                usage = {key: usage.get(key) for key in
                         ("input_tokens", "output_tokens", "web_search_calls", "compute_minutes", "cost_micro_usd")}
                for key in ("input_tokens", "output_tokens", "web_search_calls"):
                    totals[key] += usage[key] or 0
            totals["model_decisions" if step["kind"] == "decision" else "tool_calls"] += 1
            steps.append({key: step[key] for key in
                          ("id", "sequence", "kind", "tool_name", "state", "created_at", "updated_at")} | {
                "label": "Model decision" if step["kind"] == "decision" else labels.get(step["tool_name"], "Tool: " + step["tool_name"]),
                # Adapter errors can contain untrusted provider/tool text. The
                # detailed owner audit retains it; this attachment only marks it.
                "error": "This action returned an error. See audit details." if step["error"] else None,
                "model": step["receipt_metadata"].get("model"), "usage": usage,
                "cost_summary": cost_summary([row for row in costs if row["step_id"] == step["id"]]),
                "evidence_url": audit_url + "#step-" + quote(step["id"], safe=""),
                "details_url": step["details_url"]})
        return {"schema_version": 1, "run_id": run_id, "created_at": run["created_at"],
                "updated_at": run["updated_at"], "status": run["status"], "audit_url": audit_url,
                "summary": cost_summary(costs), "totals": totals, "steps": steps}

    def job(self, conn, auth, run_id):
        run = self.repo.owned_run(conn, auth, run_id)
        instance = conn.execute("SELECT name FROM agent_instance WHERE id=?", (run["instance_id"],)).fetchone()
        name = instance["name"]
        definition = self.repo.get_content(conn, auth, run_id, run["definition_ref"])
        checkpoint = self.repo.get_content(conn, auth, run_id, run["checkpoint_ref"])
        steps = self._steps(conn, auth, run)
        source_url = self._source_url(conn, auth, run)
        outputs = self._outputs(conn, auth, run, name, definition, checkpoint, steps, source_url)
        cost_rows = self.costs(conn, auth, run["instance_id"], name, run_id=run_id)
        for step in steps:
            step["cost_summary"] = cost_summary([row for row in cost_rows if row["step_id"] == step["id"]])
        base = {"instance_id": run["instance_id"], "agent_name": name, "run_id": PREFIX + run_id,
                "purchase_id": None, "runtime": True,
                "evidence_url": "/audit/jobs/" + quote(PREFIX + run_id, safe="")}
        events = [{**base, "id": PREFIX + run_id, "occurred_at": run["created_at"],
                   "event_type": "runtime.run_created", "action": "Run created", "reason": None, "outcome": "queued"}]
        events.append({**base, "id": PREFIX + run_id + ":status", "occurred_at": run["updated_at"],
                       "event_type": "runtime.run_status", "action": "Current recorded run status",
                       "reason": run["reason"], "outcome": run["status"], "observation": True})
        for step in steps:
            events.append({**base, "id": PREFIX + step["id"], "occurred_at": step["created_at"],
                           "event_type": "runtime." + step["kind"],
                           "action": "Model decision" if step["kind"] == "decision" else "Tool: " + step["tool_name"],
                           "reason": step["error"], "outcome": step["state"], "step_id": step["id"],
                           "evidence_url": base["evidence_url"] + "#step-" + quote(step["id"], safe="")})
        for event in self.repo.events(conn, auth, run_id):
            payload = event["payload"]
            status = payload.get("status") if event["kind"] == "lifecycle" and isinstance(payload, dict) else None
            step_id = payload.get("step_id") if isinstance(payload, dict) else None
            related_step = next((step for step in steps if step["id"] == step_id), None)
            events.append({**base, "id": PREFIX + event["id"], "occurred_at": event["created_at"],
                           "event_type": "runtime." + event["kind"],
                           "action": "Run " + status if status else event["kind"].replace("_", " "),
                           "reason": payload.get("reason") if isinstance(payload, dict) else None, "outcome": status or "recorded",
                           "evidence_url": base["evidence_url"] + "#step-" + quote(related_step["id"], safe="") if related_step else base["evidence_url"]})
        for output in outputs:
            events.append({**base, "id": output["id"], "occurred_at": output["created_at"],
                           "event_type": "runtime.artifact_saved", "action": "Saved output: " + output["name"],
                           "reason": None, "outcome": "saved", "deliverable_id": output["id"],
                           "evidence_url": "/audit/deliverables/" + quote(output["id"], safe="")})
        amounts = conn.execute(
            "SELECT COALESCE(SUM(u.inference_micro_usd),0),COALESCE(SUM(u.compute_micro_usd),0),"
            "COALESCE(SUM(CASE WHEN h.state IN ('held','unknown') THEN h.inference_micro_usd+h.compute_micro_usd ELSE 0 END),0),"
            "COALESCE(SUM(u.inference_input_tokens),0),COALESCE(SUM(u.inference_output_tokens),0) "
            "FROM agent_step s JOIN agent_runtime_hold r ON r.hold_id=s.hold_id AND r.operation_id=s.id JOIN budget_hold h ON h.id=r.hold_id "
            "LEFT JOIN budget_usage u ON u.hold_id=h.id WHERE s.run_id=? AND r.tenant_id=? AND r.owner_id=? AND r.instance_id=?",
            (run_id, auth.tenant_id, auth.owner_id, run["instance_id"])).fetchone()
        latest = next((item for item in outputs if item["latest"]), None)
        return {**base, "id": PREFIX + run_id, "runtime_run_id": run_id,
            "goal": definition["objective"], "deliverable_name": definition["objective"],
            "deliverable_description": definition["objective"], "state": run["status"], "reason": run["reason"],
            "blocked_reason": run["reason"], "created_at": run["created_at"], "updated_at": run["updated_at"],
            "scheduled_for": run["created_at"], "timezone": "America/New_York", "config_version": None,
            "config_snapshot": {"scenario": "runtime", "goal": definition["objective"]},
            "latest_deliverable": latest, "deliverables": outputs, "steps": steps, "events": events,
            "source_url": source_url, "plan": list(checkpoint.get("plan", {}).values()), "question": checkpoint.get("question"),
            "requirements": definition.get("requirements", []), "criterion_assessments": checkpoint.get("criterion_assessments", []),
            "inference_cost_micro_usd": amounts[0], "compute_cost_micro_usd": amounts[1], "held_micro_usd": amounts[2],
            "cost_rows": cost_rows, "cost_summary": cost_summary(cost_rows),
            "input_tokens": amounts[3], "output_tokens": amounts[4], "purchases": [], "supporting_work": [],
            "completion_criteria": [item["text"] for item in definition.get("requirements", [])]}

    def deliverable(self, conn, auth, identity):
        parts = identity.split(":")
        if len(parts) != 3 or parts[0] != "runtime":
            raise AiclError("not_found", "Saved output not found.")
        job = self.job(conn, auth, parts[1])
        item = next((output for output in job["deliverables"] if output["id"] == identity), None)
        if item is None:
            raise AiclError("not_found", "Saved output not found.")
        return {**item, "versions": [output for output in job["deliverables"] if output["spec_key"] == item["spec_key"]]}

"""Owner-scoped, read-only facts for Studio; no provider or payment calls.

Period flows use their recorded timestamps (payments use capture receipts), and
jobs use their scheduled timestamps (durable sessions use their creation time).
Date bounds are inclusive local dates in the requested timezone. Latest saved
outputs use their creation timestamps. Current balances, outstanding reservations, pending
owner requests and submitted output reviews ignore date bounds. Accepted counts describe the latest output
of jobs scheduled in the selected period, not reviews performed in that period.

Budget remaining sums each agent's tighter daily/monthly headroom for inference
and compute, using the control plane's UTC windows. It is policy headroom, not
cash or permission to execute. Service credit is available credit after charged
compute and its/inference's outstanding holds. Held USD includes all outstanding
resource and purchase reservations. Funding, reservations and consumption must
never be added together as a single expense total. Operator-funded assistant
usage is outside these agent accounts unless attributed to an agent workspace.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone as utc_timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aicl.agent_runtime.storage import Repository
from aicl.agent_workspace.setup_accounting import attempts as setup_attempts, usage as setup_usage
from aicl.commerce.service import MockCommerceService
from aicl.control.errors import AiclError
from aicl.db import to_iso
from aicl.workflow.cost_projection import cost_line, cost_summary, cost_jobs


def _usd(micro_usd):
    return micro_usd / 1_000_000


def _link(path, identity):
    return path + quote(str(identity), safe="")


def _payment_source(transport):
    return "paypal_sandbox" if transport == "paypal_sandbox" else "fixture"


def _filters(instance_id, date_from, date_to, timezone):
    if not isinstance(instance_id, str) or len(instance_id) > 200:
        raise AiclError("validation_failed", "Choose an agent.")
    try:
        if not isinstance(timezone, str) or len(timezone) > 100:
            raise ValueError()
        zone = ZoneInfo(timezone)
        bounds = []
        for value in (date_from, date_to):
            if not isinstance(value, str) or (value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)):
                raise ValueError()
            bounds.append(date.fromisoformat(value) if value else None)
        start, end = bounds
        if start and end and start > end:
            raise ValueError()
    except (ValueError, ZoneInfoNotFoundError):
        raise AiclError("validation_failed", "Choose a valid timezone and date range (YYYY-MM-DD).") from None

    def within(timestamp):
        day = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(zone).date()
        return (start is None or day >= start) and (end is None or day <= end)

    return within, {"instance_id": instance_id, "date_from": date_from, "date_to": date_to, "timezone": timezone}


class StudioData:
    def __init__(self, ctx):
        self.db, self.clock = ctx.db, ctx.clock
        self.runtime = Repository(ctx.db, ctx.clock)
        self.commerce = MockCommerceService(ctx.db, ctx.clock)

    def snapshot(self, auth, instance_id="", date_from="", date_to="", timezone="America/New_York"):
        now = self.clock.now()
        if auth is None or auth.expires_at <= now:
            raise AiclError("unauthenticated", "Sign in to continue.")
        within, filters = _filters(instance_id, date_from, date_to, timezone)
        result = {"as_of": to_iso(now), "filters": filters, "agents": [],
                  "current": {"service_credit_usd": 0, "held_usd": 0, "budget_remaining_usd": 0},
                  "totals": {"inference_usd": 0, "compute_estimate_usd": 0, "purchase_usd": 0,
                             "funding_usd": 0, "job_count": 0, "accepted_count": 0, "pending_count": 0},
                  "costs": [], "jobs": [], "outputs": [], "attention": [], "agent_summary": []}
        # A single committed SQLite snapshot prevents widgets from observing
        # different sides of a concurrent settlement. BEGIN does not write.
        with self.db.snapshot_reader() as conn:
            conn.execute("BEGIN")
            owned = conn.execute("SELECT * FROM agent_instance WHERE tenant_id=? AND owner_id=? ORDER BY name,id",
                                 (auth.tenant_id, auth.owner_id)).fetchall()
            if instance_id and not any(row["id"] == instance_id for row in owned):
                raise AiclError("not_found", "Agent not found.")
            result["agents"] = [{"id": row["id"], "name": row["name"]} for row in owned]
            selected = [row for row in owned if not instance_id or row["id"] == instance_id]
            current_micro = {"service_credit_usd": 0, "held_usd": 0, "budget_remaining_usd": 0}
            totals_micro = {key: 0 for key in ("inference_usd", "compute_estimate_usd", "purchase_usd", "funding_usd")}
            for agent in selected:
                facts, current, money = self._agent(conn, auth, agent, now, within)
                for key in ("costs", "jobs", "outputs", "attention"):
                    result[key].extend(facts[key])
                for key, amount in current.items():
                    current_micro[key] += amount
                for key, amount in money.items():
                    totals_micro[key] += amount
                summary = {"agent_id": agent["id"], "agent_name": agent["name"],
                           **{key: _usd(money[key]) for key in ("inference_usd", "compute_estimate_usd", "purchase_usd")},
                           "job_count": len(facts["jobs"]),
                           "accepted_count": sum(job["review_status"] == "accepted" for job in facts["jobs"]),
                           "pending_count": len(facts["attention"]),
                           "evidence_url": _link("/instances/", agent["id"])}
                result["agent_summary"].append(summary)
            result["current"] = {key: _usd(value) for key, value in current_micro.items()}
            result["totals"].update({key: _usd(value) for key, value in totals_micro.items()})
        for key in ("job_count", "accepted_count", "pending_count"):
            result["totals"][key] = sum(row[key] for row in result["agent_summary"])
        result["costs"].sort(key=lambda row: (row["occurred_at"], row["id"]), reverse=True)
        result["jobs"].sort(key=lambda row: (row["scheduled_at"], row["id"]), reverse=True)
        result["outputs"].sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        result["attention"].sort(key=lambda row: (row["created_at"], row["id"]))
        result["costs"] = [cost_line(row) for row in result["costs"]]
        result["cost_summary"] = cost_summary(result["costs"])
        result["cost_jobs"] = cost_jobs(result["costs"], result["jobs"])
        for job in result["jobs"]:
            lines = [row for row in result["costs"] if row["job_id"] == job["id"]]
            summary = cost_summary(lines)
            job.update(cost_summary=summary, settled_usd=_usd(summary["settled_micro_usd"]),
                       estimated_usd=_usd(summary["estimated_micro_usd"]), total_cost_usd=_usd(summary["total_micro_usd"]),
                       components=", ".join(dict.fromkeys(row["component_label"] for row in lines if row["charge_kind"] in ("usage", "estimate"))) or "No recorded charges",
                       coverage=summary["coverage_note"])
        for agent in result["agent_summary"]:
            summary = cost_summary([row for row in result["costs"] if row["agent_id"] == agent["agent_id"]])
            agent.update(cost_summary=summary, settled_usd=_usd(summary["settled_micro_usd"]),
                         estimated_usd=_usd(summary["estimated_micro_usd"]), total_cost_usd=_usd(summary["total_micro_usd"]))
        return result

    def _agent(self, conn, auth, agent, now, within):
        iid, name = agent["id"], agent["name"]
        scope = (iid, auth.tenant_id, auth.owner_id)
        jobs = [dict(row) for row in conn.execute(
            "SELECT w.id,w.commerce_run_id,w.occurrence_id,w.state,w.blocked_reason,w.spec_json,o.scheduled_for "
            "FROM mock_workflow_run w JOIN mock_workflow_occurrence o ON o.id=w.occurrence_id WHERE w.instance_id=?", (iid,))]
        by_job = {row["id"]: row for row in jobs}
        commerce_to_job = {row["commerce_run_id"]: row["id"] for row in jobs}
        purchases = [dict(row) for row in conn.execute(
            "SELECT p.id,p.run_id,p.quota_state,p.amount_minor,p.state,p.created_at,p.expires_at,w.workflow_run_id "
            "FROM mock_commerce_purchase p LEFT JOIN mock_workflow_purchase w ON w.purchase_id=p.id "
            "WHERE p.instance_id=? AND p.tenant_id=? AND p.owner_id=?", scope)]
        purchase_to_job = {}
        for row in purchases:
            if row["workflow_run_id"] in by_job:
                purchase_to_job[row["id"]] = row["workflow_run_id"]
                commerce_to_job[row["run_id"]] = row["workflow_run_id"]
        attempts = {row["hold_id"]: dict(row) for row in conn.execute(
            "SELECT a.hold_id,a.workflow_run_id,a.model,a.state FROM workflow_inference_attempt a "
            "JOIN mock_workflow_run w ON w.id=a.workflow_run_id WHERE w.instance_id=?", (iid,)) if row["hold_id"]}
        attempt_jobs = {row["workflow_run_id"] for row in attempts.values()}
        settled_jobs = {row["workflow_run_id"] for row in attempts.values() if row["state"] == "settled"}
        holds = [dict(row) for row in conn.execute("SELECT * FROM budget_hold WHERE instance_id=?", (iid,))]
        usage = {row["hold_id"]: dict(row) for row in conn.execute("SELECT * FROM budget_usage WHERE instance_id=?", (iid,))}
        runtime_runs = [dict(row) for row in conn.execute(
            "SELECT * FROM agent_run WHERE instance_id=? AND tenant_id=? AND owner_id=?", scope)]
        runtime_ids = {row["id"] for row in runtime_runs}
        runtime_holds = [dict(row) for row in conn.execute(
            "SELECT r.hold_id,s.run_id,s.id AS step_id,s.kind,s.tool_version,s.receipt_metadata_json "
            "FROM agent_runtime_hold r LEFT JOIN agent_step s ON s.hold_id=r.hold_id AND s.id=r.operation_id "
            "LEFT JOIN agent_run a ON a.id=s.run_id AND a.instance_id=r.instance_id "
            "AND a.tenant_id=r.tenant_id AND a.owner_id=r.owner_id "
            "WHERE r.instance_id=? AND r.tenant_id=? AND r.owner_id=? AND (s.id IS NULL OR a.id IS NOT NULL)", scope)]
        ledger = [dict(row) for row in conn.execute("SELECT * FROM mock_commerce_ledger WHERE instance_id=?", (iid,))]
        receipts = {row["id"]: dict(row) for row in conn.execute(
            "SELECT r.id,r.order_id,r.purpose,r.amount_minor,r.created_at,o.payment_transport,o.purchase_id "
            "FROM mock_commerce_receipt r JOIN mock_commerce_order o ON o.id=r.order_id "
            "WHERE r.instance_id=? AND o.tenant_id=? AND o.owner_id=?", scope)}
        dispatches = [dict(row) for row in conn.execute(
            "SELECT d.id,d.hold_id,d.occurrence_id,d.continuation_run_id,u.cost_micro_usd,u.created_at "
            "FROM render_dispatch d LEFT JOIN render_compute_usage u ON u.dispatch_id=d.id WHERE d.instance_id=?", (iid,))]
        outputs, latest_outputs = {}, {}
        for row in conn.execute(
            "SELECT d.id,d.workflow_run_id,d.state,d.created_at FROM mock_workflow_deliverable d "
            "JOIN mock_workflow_run w ON w.id=d.workflow_run_id WHERE w.instance_id=? ORDER BY d.version", (iid,)):
            outputs[row["workflow_run_id"]] = row["state"]
            latest_outputs[row["workflow_run_id"]] = dict(row)

        facts = {"costs": [], "jobs": [], "outputs": [], "attention": []}
        money = {key: 0 for key in ("inference_usd", "compute_estimate_usd", "purchase_usd", "funding_usd")}
        job_inference, job_compute, job_sources = {}, {}, {}

        def cost(identity, timestamp, category, amount, status, provenance, *, job_id=None, evidence_url=None, measured=None, model=None, step_id=None, hold_id=None):
            if not within(timestamp):
                return
            row = {"id": identity, "occurred_at": timestamp, "agent_id": iid, "agent_name": name,
                   "job_id": job_id, "category": category, "amount_usd": _usd(amount), "amount_micro_usd": amount, "status": status,
                   "step_id": step_id, "hold_id": hold_id,
                   "provenance": provenance, "evidence_url": evidence_url or (
                       _link("/audit/jobs/", job_id) if job_id else _link("/instances/", iid))}
            if step_id and job_id and not evidence_url:
                row["evidence_url"] += "#step-" + quote(step_id, safe="")
            if measured:
                row.update(input_tokens=measured["inference_input_tokens"], output_tokens=measured["inference_output_tokens"],
                           web_search_calls=measured["web_search_calls"], compute_minutes=measured["compute_minutes"],
                           price_table_version=measured["price_table_version"])
            if model:
                row["model"] = model
            facts["costs"].append(row)
            target = {"inference": "inference_usd", "setup_inference": "inference_usd", "compute_estimate": "compute_estimate_usd",
                      "merchant_purchase": "purchase_usd", "service_funding": "funding_usd"}.get(category)
            if target:
                money[target] += amount
            if job_id and category in ("inference", "compute_estimate"):
                target_jobs = job_inference if category == "inference" else job_compute
                target_jobs[job_id] = target_jobs.get(job_id, 0) + amount
                job_sources.setdefault(job_id, set()).add(provenance)

        for row in ledger:
            if row["kind"] == "service_topup":
                receipt = receipts.get(row["receipt_id"])
                cost(row["id"], row["created_at"], "service_funding", row["delta_micro_usd"], "recorded",
                     _payment_source(receipt["payment_transport"]) if receipt else "application_record",
                     evidence_url=_link("/commerce/orders/", receipt["order_id"]) if receipt else None)
                continue
            attempt = attempts.get(row["hold_id"])
            # Live inference links by a durable FK. Fixture and historical work
            # use their commerce reference, normalized through both job maps.
            pieces = row["reference"].split(":")
            referenced = pieces[1] if len(pieces) > 1 else ""
            job_id = attempt["workflow_run_id"] if attempt else commerce_to_job.get(referenced)
            cost(row["id"], row["created_at"], "inference", -row["delta_micro_usd"], "settled",
                 "provider_reported" if attempt else "fixture", job_id=job_id,
                 measured=usage.get(row["hold_id"]), model=attempt["model"] if attempt else None, hold_id=row["hold_id"])
        for row in receipts.values():
            if row["purpose"] == "agent_purchase":
                cost(row["id"], row["created_at"], "merchant_purchase", row["amount_minor"] * 10_000,
                     "captured", _payment_source(row["payment_transport"]), job_id=purchase_to_job.get(row["purchase_id"]),
                     evidence_url=_link("/commerce/orders/", row["order_id"]))
        for row in purchases:
            if row["quota_state"] == "held":
                cost("reservation:" + row["id"], row["created_at"], "purchase_reservation", row["amount_minor"] * 10_000,
                     row["state"], "application_record", job_id=purchase_to_job.get(row["id"]),
                     evidence_url=_link("/requests?selected=", "purchase:" + row["id"]))
        for row in dispatches:
            if row["cost_micro_usd"] is None:
                continue
            candidates = [job["id"] for job in jobs if job["occurrence_id"] == row["occurrence_id"]]
            job_id = row["continuation_run_id"] if row["continuation_run_id"] in by_job else (
                candidates[0] if len(candidates) == 1 else None)
            # A dispatch can produce several jobs. Keep its cost at agent level
            # rather than multiplying it or inventing a per-job allocation.
            cost(row["id"], row["created_at"], "compute_estimate", row["cost_micro_usd"], "estimated",
                 "runtime_estimate", job_id=job_id, hold_id=row["hold_id"], measured=usage.get(row["hold_id"]))

        # Durable sessions settle the shared budget ledger directly. They do
        # not create a commerce debit or Render usage projection. Ownership of
        # the canonical hold identifies those costs without parsing references
        # or counting any of the legacy ledger projections a second time.
        by_hold = {row["id"]: row for row in holds}
        for row in runtime_holds:
            job_id = "runtime:" + row["run_id"] if row["run_id"] in runtime_ids else None
            measured = usage.get(row["hold_id"])
            metadata = json.loads(row["receipt_metadata_json"] or "{}")
            model = metadata.get("model")
            provenance = ("fixture" if (row["tool_version"] or "").startswith("scripted-") else
                          "provider_reported" if model else "application_record")
            if measured is not None:
                if row["kind"] == "decision" or measured["inference_input_tokens"] or measured["inference_output_tokens"] or measured["web_search_calls"]:
                    if job_id:
                        # Source provenance is historical evidence, independent
                        # of whether its settlement falls inside this period.
                        job_sources.setdefault(job_id, set()).add(provenance)
                    if measured["inference_micro_usd"]:
                        cost("runtime-inference:" + row["hold_id"], measured["recorded_at"], "inference",
                             measured["inference_micro_usd"], "settled", provenance,
                             job_id=job_id, measured=measured, model=model, step_id=row["step_id"], hold_id=row["hold_id"])
                if measured["compute_micro_usd"]:
                    cost("runtime-compute:" + row["hold_id"], measured["recorded_at"], "compute_estimate",
                         measured["compute_micro_usd"], "estimated", "runtime_estimate", job_id=job_id, measured=measured,
                         step_id=row["step_id"], hold_id=row["hold_id"])
            hold = by_hold[row["hold_id"]]
            if hold["state"] in {"held", "unknown"}:
                for category in ("inference", "compute"):
                    if hold[category + "_micro_usd"]:
                        cost("runtime-" + category + "-reservation:" + hold["id"], hold["created_at"],
                             category + "_reservation", hold[category + "_micro_usd"], hold["state"],
                             "application_record", job_id=job_id, step_id=row["step_id"], hold_id=row["hold_id"])

        workspace = conn.execute("SELECT id FROM agent_workspace WHERE instance_id=? AND tenant_id=? AND owner_id=?", scope).fetchone()
        if workspace:
            for row in setup_attempts(conn, workspace["id"]):
                if row["state"] == "settled":
                    category = "setup_waived" if row["waived_attempt_id"] else "setup_inference"
                    status = "waived" if row["waived_attempt_id"] else "charged" if row["charged_attempt_id"] else "pending_attribution"
                    cost("setup:" + row["id"], row["updated_at"], category, row["cost_micro_usd"], status,
                         "provider_reported" if row["model"] else "application_record",
                         evidence_url=_link("/agent-workspaces/", workspace["id"]), model=row["model"],
                         measured={"inference_input_tokens": row["input_tokens"], "inference_output_tokens": row["output_tokens"],
                                   "web_search_calls": 0, "compute_minutes": 0, "price_table_version": row["price_version"]})
                elif row["state"] in {"held", "unknown"}:
                    cost("setup-reservation:" + row["id"], row["created_at"], "setup_reservation",
                         row["reserved_micro_usd"], row["state"], "application_record",
                         evidence_url=_link("/agent-workspaces/", workspace["id"]))

        def saved_output(identity, job_id, title, status, timestamp, provenance):
            evidence_url = _link("/audit/deliverables/", identity)
            if within(timestamp):
                facts["outputs"].append({"id": identity, "agent_id": iid, "agent_name": name,
                    "job_id": job_id, "output_name": title, "status": status, "created_at": timestamp,
                    "content_available": True, "provenance": provenance, "evidence_url": evidence_url})
            return evidence_url

        def attention(identity, kind, title, status, timestamp, evidence_url=None):
            facts["attention"].append({"id": identity, "agent_id": iid, "agent_name": name,
                                       "kind": kind, "title": title, "status": status, "created_at": timestamp,
                                       "evidence_url": evidence_url or _link("/requests?selected=", identity)})

        for row in conn.execute("SELECT id,kind,title,status,created_at FROM owner_request "
                                "WHERE instance_id=? AND tenant_id=? AND owner_id=? AND status='pending'", scope):
            attention(row["id"], row["kind"], row["title"], row["status"], row["created_at"])
        for row in conn.execute("SELECT id,description,created_at FROM browser_purchase_proposal "
                                "WHERE instance_id=? AND tenant_id=? AND owner_id=? AND state='pending'", scope):
            attention("browser-purchase:" + row["id"], "purchase_proposal", row["description"], "pending", row["created_at"])
        for row in purchases:
            if row["state"] in ("awaiting_approval", "awaiting_checkout", "payment_pending") and not (
                row["state"] in ("awaiting_approval", "awaiting_checkout") and row["expires_at"] <= to_iso(now)):
                attention("purchase:" + row["id"], "purchase", "Review purchase or payment", row["state"], row["created_at"])
        for job_id, row in latest_outputs.items():
            if row["state"] == "submitted":
                title = json.loads(by_job[job_id]["spec_json"]).get("name", "Job output")
                attention("deliverable:" + row["id"], "deliverable_review", title, "submitted", row["created_at"],
                          _link("/audit/deliverables/", row["id"]))
        for row in jobs:
            sources = job_sources.get(row["id"], set()) - {"runtime_estimate"}
            provenance = "mixed" if len(sources) > 1 else next(iter(sources),
                "provider_reported" if row["id"] in settled_jobs else
                "application_record" if row["id"] in attempt_jobs else "fixture")
            latest = latest_outputs.get(row["id"])
            title = json.loads(row["spec_json"]).get("name", "Job output")
            output_url = saved_output(latest["id"], row["id"], title, latest["state"], latest["created_at"], provenance) if latest else None
            if within(row["scheduled_for"]):
                facts["jobs"].append({"id": row["id"], "agent_id": iid, "agent_name": name,
                    "scheduled_at": row["scheduled_for"], "status": row["state"], "blocked_reason": row["blocked_reason"],
                    "output_name": title, "output_count": int(latest is not None), "output_url": output_url,
                    "review_status": outputs.get(row["id"], "not_submitted"),
                    "inference_usd": _usd(job_inference.get(row["id"], 0)),
                    "compute_estimate_usd": _usd(job_compute.get(row["id"], 0)),
                    "provenance": provenance, "evidence_url": _link("/audit/jobs/", row["id"])})

        for row in runtime_runs:
            checkpoint = self.runtime.get_content(conn, auth, row["id"], row["checkpoint_ref"])
            job_id = "runtime:" + row["id"]
            evidence_url = _link("/audit/jobs/", job_id)
            sources = job_sources.get(job_id, set()) - {"runtime_estimate"}
            provenance = "mixed" if len(sources) > 1 else next(iter(sources), "application_record")
            output_urls = []
            for local_ref, artifact in checkpoint.get("artifacts", {}).items():
                # Verify the scoped immutable record before exposing its link;
                # the compact operations feed never includes artifact contents.
                self.runtime.get_content(conn, auth, row["id"], artifact["ref"])
                stored = conn.execute("SELECT kind,created_at FROM agent_content WHERE id=? AND run_id=?",
                                      (artifact["ref"], row["id"])).fetchone()
                if stored["kind"] != "artifact":
                    raise AiclError("unavailable", "Saved output evidence is unavailable.")
                output_urls.append(saved_output(job_id + ":" + artifact["ref"], job_id, local_ref,
                    "completed" if local_ref in checkpoint.get("completed_artifacts", []) else "draft",
                    stored["created_at"], provenance))
            if row["status"] == "waiting_owner":
                attention(job_id, "owner_input", "Answer the agent's question", "waiting_owner", row["updated_at"], evidence_url)
            elif row["status"] == "blocked":
                attention(job_id, "blocked_work", "Review blocked agent work", "blocked", row["updated_at"], evidence_url)
            if within(row["created_at"]):
                definition = self.runtime.get_content(conn, auth, row["id"], row["definition_ref"])
                facts["jobs"].append({"id": job_id, "agent_id": iid, "agent_name": name,
                    "scheduled_at": row["created_at"], "status": row["status"], "blocked_reason": row["reason"],
                    "output_name": definition.get("objective", "Agent work"), "output_count": len(output_urls),
                    "output_url": output_urls[0] if output_urls else None,
                    # A model's completion and self-assessment cannot create
                    # owner acceptance. Preserve partial output visibility too.
                    "review_status": "completed" if checkpoint.get("completed_artifacts") else
                                     "draft" if checkpoint.get("artifacts") else "not_submitted",
                    "inference_usd": _usd(job_inference.get(job_id, 0)),
                    "compute_estimate_usd": _usd(job_compute.get(job_id, 0)),
                    "provenance": provenance, "evidence_url": evidence_url})

        active_holds = [row for row in holds if row["state"] in ("held", "unknown")]
        setup_held = setup_usage(conn, workspace["id"])["held_micro_usd"] if workspace else 0
        current = {"service_credit_usd": self.commerce._balance(conn, iid),
                   "held_usd": sum(row["inference_micro_usd"] + row["compute_micro_usd"] for row in active_holds)
                       + sum(row["amount_minor"] * 10_000 for row in purchases if row["quota_state"] == "held") + setup_held,
                   "budget_remaining_usd": 0}
        utc_now = now.astimezone(utc_timezone.utc)
        for category in ("inference", "compute"):
            available = []
            for field, limit, key in (("window_day", "daily", utc_now.strftime("%Y-%m-%d")),
                                     ("window_month", "monthly", utc_now.strftime("%Y-%m"))):
                column = category + "_micro_usd"
                consumed = sum(row[column] for row in usage.values() if row[field] == key)
                reserved = sum(row[column] for row in active_holds if row[field] == key)
                available.append(max(0, agent[f"{category}_{limit}_micro_usd"] - consumed - reserved))
            current["budget_remaining_usd"] += min(available)
        return facts, current, money

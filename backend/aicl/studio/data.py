"""Owner-scoped, read-only facts for Studio; no provider or payment calls.

Period flows use their recorded timestamps (payments use capture receipts), and
jobs use their scheduled timestamps. Date bounds are inclusive local dates in
the requested timezone. Current balances, outstanding reservations, pending
owner requests and submitted output reviews ignore date bounds. Accepted counts describe the latest output
of jobs scheduled in the selected period, not reviews performed in that period.

Budget remaining sums each agent's tighter daily/monthly headroom for inference
and compute, using the control plane's UTC windows. It is policy headroom, not
cash or permission to execute. Service credit is available credit after charged
compute and its/inference's outstanding holds. Held USD includes all outstanding
resource and purchase reservations. Funding, reservations and consumption must
never be added together as a single expense total. Operator-funded assistant
usage is outside these agent accounts.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone as utc_timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aicl.control.errors import AiclError
from aicl.db import to_iso


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

    def snapshot(self, auth, instance_id="", date_from="", date_to="", timezone="America/New_York"):
        now = self.clock.now()
        if auth is None or auth.expires_at <= now:
            raise AiclError("unauthenticated", "Sign in to continue.")
        within, filters = _filters(instance_id, date_from, date_to, timezone)
        result = {"as_of": to_iso(now), "filters": filters, "agents": [],
                  "current": {"service_credit_usd": 0, "held_usd": 0, "budget_remaining_usd": 0},
                  "totals": {"inference_usd": 0, "compute_estimate_usd": 0, "purchase_usd": 0,
                             "funding_usd": 0, "job_count": 0, "accepted_count": 0, "pending_count": 0},
                  "costs": [], "jobs": [], "attention": [], "agent_summary": []}
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
                for key in ("costs", "jobs", "attention"):
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
        result["attention"].sort(key=lambda row: (row["created_at"], row["id"]))
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

        facts = {"costs": [], "jobs": [], "attention": []}
        money = {key: 0 for key in ("inference_usd", "compute_estimate_usd", "purchase_usd", "funding_usd")}
        job_inference, job_compute, job_sources = {}, {}, {}

        def cost(identity, timestamp, category, amount, status, provenance, *, job_id=None, evidence_url=None, measured=None, model=None):
            if not within(timestamp):
                return
            row = {"id": identity, "occurred_at": timestamp, "agent_id": iid, "agent_name": name,
                   "job_id": job_id, "category": category, "amount_usd": _usd(amount), "status": status,
                   "provenance": provenance, "evidence_url": evidence_url or (
                       _link("/audit/jobs/", job_id) if job_id else _link("/instances/", iid))}
            if measured:
                row.update(input_tokens=measured["inference_input_tokens"], output_tokens=measured["inference_output_tokens"])
            if model:
                row["model"] = model
            facts["costs"].append(row)
            target = {"inference": "inference_usd", "compute_estimate": "compute_estimate_usd",
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
                 measured=usage.get(row["hold_id"]), model=attempt["model"] if attempt else None)
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
                 "runtime_estimate", job_id=job_id)

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
            if within(row["scheduled_for"]):
                sources = job_sources.get(row["id"], set()) - {"runtime_estimate"}
                provenance = "mixed" if len(sources) > 1 else next(iter(sources),
                    "provider_reported" if row["id"] in settled_jobs else
                    "application_record" if row["id"] in attempt_jobs else "fixture")
                facts["jobs"].append({"id": row["id"], "agent_id": iid, "agent_name": name,
                    "scheduled_at": row["scheduled_for"], "status": row["state"], "blocked_reason": row["blocked_reason"],
                    "output_name": json.loads(row["spec_json"]).get("name", "Job output"),
                    "review_status": outputs.get(row["id"], "not_submitted"),
                    "inference_usd": _usd(job_inference.get(row["id"], 0)),
                    "compute_estimate_usd": _usd(job_compute.get(row["id"], 0)),
                    "provenance": provenance, "evidence_url": _link("/audit/jobs/", row["id"])})

        active_holds = [row for row in holds if row["state"] in ("held", "unknown")]
        compute_holds = {row["hold_id"] for row in dispatches}
        credit_held = sum(row["inference_micro_usd"] + row["compute_micro_usd"] for row in active_holds if row["id"] in attempts)
        credit_held += sum(row["compute_micro_usd"] for row in active_holds if row["id"] in compute_holds and row["id"] not in attempts)
        current = {"service_credit_usd": sum(row["delta_micro_usd"] for row in ledger) - credit_held
                       - sum(row["cost_micro_usd"] or 0 for row in dispatches),
                   "held_usd": sum(row["inference_micro_usd"] + row["compute_micro_usd"] for row in active_holds)
                       + sum(row["amount_minor"] * 10_000 for row in purchases if row["quota_state"] == "held"),
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

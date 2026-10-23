"""Fixed PocketPlan fixtures; no advertising or model provider is contacted."""
from __future__ import annotations

from copy import deepcopy
import json
import uuid
from zoneinfo import ZoneInfo

from aicl.commerce.service import _canonical
from aicl.commerce.adapters import ADS_CATALOG
from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso

SCENARIO = "pocketplan_ads"
PRIMARY = "pocketplan-campaign-v1"
EXPANSION = "pocketplan-expansion-v1"


def _spec(key, name, description, criteria):
    return {"key": key, "name": name, "description": description, "criteria": criteria,
            "purchase_required": False, "validation_scenario": "pass"}


def pocketplan_preset():
    """Return a fresh, editable saved-configuration example."""
    return {"scenario": SCENARIO,
        "goal": "Market PocketPlan to freelancers. Prepare a campaign, recommend where to advertise, and report what we learn. Ask before spending money on ads.",
        "inputs": "PocketPlan is a fictional daily planner for independent freelancers. Supplied audience fixture: 18 of 30 beta interviews mention juggling client deadlines. Destination: https://pocketplan.example/app. LaunchPad Ads is a fictional ad platform; all performance figures are demo fixtures.",
        "cadence": "daily", "timezone": "America/New_York", "deliverables": [
            _spec("campaign_plan", "Campaign plan", "Audience evidence, a bounded three-day test, an organic alternative, and a measurement plan.",
                  ["Cite the supplied audience evidence", "State the $30 total and $10 daily caps", "Define clicks, attributed installs and cost per install; do not promise results"]),
            _spec("ad_creative", "Ad creative", "Two PocketPlan ad variants with audience, call to action and destination.",
                  ["Include two ad variants for freelancers", "Use the supplied PocketPlan destination", "Use truthful feature claims and one clear call to action"]),
            _spec("performance_report", "Daily performance report", "Timestamped campaign results and next steps; keep prepaid funds distinct from consumed spend.",
                  ["Include the reporting date and campaign state", "Reconcile spend, impressions, clicks and attributed installs", "Show CPC and CPI with their denominators and flag fixture data"])
        ]}


def ad_content(snapshot, spec, feedback="", failed=False):
    """Scenario fixtures with saved source context, never inferred market research."""
    kind = spec.get("ad_kind", spec["key"])
    header = [spec["name"], "Goal: " + snapshot["goal"], "Saved inputs\n" + snapshot["inputs"]]
    if kind == "campaign_plan":
        sections = ["Audience evidence\nThe supplied demo interviews report 18 of 30 freelancers struggling to coordinate client deadlines. This supports a small test of deadline-focused messaging; it does not establish market demand.",
            "Recommendation\nTest PocketPlan on LaunchPad Ads for three reporting days: $30 total, at most $10 per day. Target: " + ADS_CATALOG[PRIMARY]["campaign"]["targeting"] + ". Ask the owner to approve the exact campaign before funding it.",
            "Measurement plan\nRecord impressions, clicks and attributed installs. CPC = consumed advertising spend / clicks. CPI = consumed advertising spend / attributed installs. Attribution is a fixture and does not prove causation or revenue.",
            "Alternative and next action\nPublish the prepared creative through the developer's existing channels at no ad cost. If paid distribution is declined, retain this plan and report an organic outreach checklist. Review creative and targeting before approving a purchase.",
            "Separate expansion hypothesis\nIndependent professionals interested in productivity may form a broader audience. Treat any $15 expansion as a separate owner decision; the recommended alternative is to wait for the initial three-day test before expanding."]
    elif kind == "ad_creative":
        sections = [f"Variant {chr(65 + index)}\nHeadline: {creative['headline']}\nBody: {creative['body']}\nCall to action: {creative['call_to_action']}"
                    for index, creative in enumerate(ADS_CATALOG[PRIMARY]["campaign"]["creative"])] + [
            "Audience and destination\n" + ADS_CATALOG[PRIMARY]["campaign"]["targeting"] + ". Destination: https://pocketplan.example/app (fictional demo destination).",
            "Next action\nReview both variants, destination and audience before approving the separate paid campaign. This creative exists and can be revised without a purchase."]
    elif kind == "ad_authorization":
        expansion = spec["offer_id"] == EXPANSION
        sections = ["Evidence and recommendation\n" + (
            "The first daily campaign report is available. Propose a separate $15, three-day audience test for independent professionals, capped at $5 per day. One fixture day is insufficient to justify expansion confidently; the owner can decline and wait for the original test to finish."
            if expansion else "The saved campaign plan identifies deadline management as a plausible message for the supplied freelancer audience. A $30, three-day test, capped at $10 per day, buys measurable distribution for the prepared creative."),
            "What approval covers\nLaunchPad Ads, the displayed creative and destination, the specified audience, and the fixed total and daily caps. Payment funds the campaign; scheduled reporting starts and records delivery separately.",
            "Alternative and decline outcome\n" + ("Keep the original campaign running within its existing cap. No expansion funds are charged." if expansion else "Keep the campaign plan and creative. Use existing organic channels; no paid campaign starts."),
            "Supporting work\n" + "\n".join(spec.get("source_titles", []))]
    else:
        report = spec.get("ad_report", {})
        if report.get("organic"):
            sections = [f"Report date\n{report['reported_at']}",
                "Paid distribution\nThe owner declined the campaign. Paid ad funding and consumption remain $0; no paid delivery or installs are claimed.",
                "Organic outreach checklist\nReview the two prepared ad variants, choose one for an existing developer channel, verify the demo destination, and decide whether to publish. No publishing action was performed by this mock.",
                "Next action\nUse owner feedback to refine the creative. Revisit paid distribution only through a new explicit campaign scope."]
        else:
            clicks, installs = report.get("clicks", 0), report.get("attributed_installs", 0)
            spend = report.get("spend_minor", 0)
            cpc = f"${spend / clicks / 100:.2f}" if clicks else "Not available (zero clicks)"
            cpi = f"${spend / installs / 100:.2f}" if installs else "Not available (zero attributed installs)"
            sections = [f"Report date\n{report.get('reported_at', '')} · campaign day {report.get('day', 0)} · {report.get('campaign_name', 'PocketPlan')}",
                f"Daily results\nConsumed spend: ${spend / 100:.2f}\nImpressions: {report.get('impressions', 0):,}\nClicks: {clicks}\nAttributed installs: {installs}\nCPC = spend / clicks: {cpc}\nCPI = spend / attributed installs: {cpi}",
                f"Funding reconciliation\nPrepaid campaign funds: ${report.get('funding_minor', 0) / 100:.2f}. Cumulative consumption: ${report.get('consumed_minor', 0) / 100:.2f}. Remaining prepaid funds: ${report.get('remaining_minor', 0) / 100:.2f}. Consumption is not another PayPal charge. Campaign state: {report.get('state', 'active')}.",
                "Interpretation and next action\n" + report.get("recommendation", "Keep the approved cap and collect the full test before deciding whether to increase spend.")]
    if feedback:
        sections += ["Owner change request\n" + feedback,
                     "Revision\nKeep the campaign recommendation concise: confirm the audience, creative and fixed cap, then review the reported evidence before approving any additional spend."]
    if failed:
        sections.append("Unfinished draft\nA configured fixture check is incomplete; revise on the next scheduled occurrence.")
    sections.append("Local scenario fixture. No ads are published and no real performance is measured.")
    return "\n\n".join(header + sections)


class AdWorkflowMixin:
    def _ad_job(self, conn, auth, config, occurrence_id, spec, *, offer_id=None):
        iid, now = config["instance_id"], to_iso(self.clock.now())
        brief = {"product_name": spec["name"], "audience": "Independent freelancers", "goal": config["goal"][:600]}
        commerce = self.commerce._start_workflow_run(conn, auth, iid, f"wf:{occurrence_id}:{spec['key']}", brief,
                                                   purchase_required=bool(offer_id), offer_id=offer_id, charge=self.inference is None)
        snapshot = {k: deepcopy(config[k]) for k in ("goal", "inputs", "deliverables", "cadence", "timezone", "version", "scenario")}
        run_id = str(uuid.uuid4())
        conn.execute("INSERT INTO mock_workflow_run (id,instance_id,occurrence_id,commerce_run_id,spec_key,config_version,config_json,spec_json,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, iid, occurrence_id, commerce["id"], spec["key"], config["version"], _canonical(snapshot), _canonical(spec), "running", now, now))
        job = self._job(conn, auth, run_id)
        if offer_id:
            conn.execute("INSERT INTO mock_workflow_purchase (purchase_id,workflow_run_id) VALUES (?,?)", (commerce["purchase_id"], run_id))
        self._produce(conn, auth, job, already_charged=True)
        return self._job(conn, auth, run_id)

    def _ad_request(self, conn, auth, config, occurrence_id, offer_id):
        existing = conn.execute("SELECT * FROM mock_ad_campaign WHERE instance_id=? AND offer_id=?", (config["instance_id"], offer_id)).fetchone()
        if existing:
            return existing
        original = conn.execute("SELECT config_json FROM mock_workflow_run WHERE instance_id=? AND spec_key='campaign_plan' AND json_extract(config_json,'$.scenario')=? ORDER BY rowid LIMIT 1", (config["instance_id"], SCENARIO)).fetchone()
        if original:
            config = {**json.loads(original[0]), "instance_id": config["instance_id"]}
        expansion = offer_id == EXPANSION
        spec = _spec("audience_expansion" if expansion else "campaign_authorization", "Audience expansion recommendation" if expansion else "Campaign purchase recommendation",
                     "Evidence, exact campaign scope, organic alternative and owner decision.", ["Link the supporting saved work", "State fixed campaign caps and the decline outcome"])
        sources = conn.execute("SELECT w.id,d.id AS deliverable_id,w.spec_json FROM mock_workflow_run w JOIN mock_workflow_deliverable d ON d.workflow_run_id=w.id WHERE w.instance_id=? AND json_extract(w.config_json,'$.scenario')=? AND d.state IN ('submitted','accepted') AND d.version=(SELECT MAX(x.version) FROM mock_workflow_deliverable x WHERE x.workflow_run_id=w.id) AND (w.spec_key IN ('campaign_plan','ad_creative') OR json_extract(w.spec_json,'$.ad_kind')='performance_report') ORDER BY d.rowid DESC", (config["instance_id"], SCENARIO)).fetchall()
        spec.update(ad_kind="ad_authorization", offer_id=offer_id, source_titles=[json.loads(r["spec_json"])["name"] for r in sources[:4]],
                    source_work=[{"job_id": r["id"], "deliverable_id": r["deliverable_id"], "name": json.loads(r["spec_json"])["name"]} for r in sources[:4]])
        job = self._ad_job(conn, auth, config, occurrence_id, spec, offer_id=offer_id)
        cid = str(uuid.uuid4())
        conn.execute("INSERT INTO mock_ad_campaign (id,instance_id,offer_id,workflow_run_id,total_cap_minor,daily_cap_minor,created_at) VALUES (?,?,?,?,?,?,?)",
                     (cid, config["instance_id"], offer_id, job["id"], 1500 if expansion else 3000, 500 if expansion else 1000, to_iso(self.clock.now())))
        return conn.execute("SELECT * FROM mock_ad_campaign WHERE id=?", (cid,)).fetchone()

    def _ad_activate(self, conn, auth, job):
        campaign = conn.execute("SELECT * FROM mock_ad_campaign WHERE workflow_run_id=?", (job["id"],)).fetchone()
        if not campaign:
            return False
        config = self._config(conn, auth, job["instance_id"])
        if not config["enabled"]:
            raise AiclError("denied", "Enable the schedule before starting campaign delivery.", reason="schedule_paused")
        self.commerce._controls(conn, auth, job["instance_id"])
        purchase = self._current_purchase(conn, job)
        if not purchase or purchase["state"] != "paid" or not purchase["fulfillment_json"]:
            raise AiclError("denied", "Complete the approved campaign checkout before delivery.", reason="payment_incomplete")
        if not campaign["started_at"]:
            anchor = config["demo_time"] or to_iso(self.clock.now())
            conn.execute("UPDATE mock_ad_campaign SET started_at=? WHERE id=?", (anchor, campaign["id"]))
            self.commerce._event(conn, auth, job["instance_id"], "commerce.run_completed", action="campaign_started", run_id=job["id"], campaign_id=campaign["id"])
        return True

    def _ad_campaign_projection(self, conn, auth, campaign):
        job = self._job(conn, auth, campaign["workflow_run_id"])
        purchase = self._current_purchase(conn, job)
        paid = bool(purchase and purchase["state"] == "paid" and purchase["fulfillment_json"])
        funding = campaign["total_cap_minor"] if paid else 0
        metrics = []
        for row in conn.execute("SELECT * FROM mock_ad_day WHERE campaign_id=? ORDER BY day_number", (campaign["id"],)):
            metrics.append({"day": row["day_number"], "reported_at": row["reported_at"], "spend_minor": row["spend_minor"],
                "impressions": row["impressions"], "clicks": row["clicks"], "attributed_installs": row["installs"],
                "cpc_minor": round(row["spend_minor"] / row["clicks"], 2) if row["clicks"] else None,
                "cpi_minor": round(row["spend_minor"] / row["installs"], 2) if row["installs"] else None,
                "run_id": row["workflow_run_id"]})
        consumed = sum(m["spend_minor"] for m in metrics)
        state = "completed" if campaign["completed_at"] else "active" if campaign["started_at"] else "funded" if paid else purchase["state"] if purchase else "awaiting_approval"
        if not paid and purchase and purchase["expires_at"] <= to_iso(self.clock.now()) and state in ("awaiting_approval", "awaiting_checkout"):
            state = "expired"
        return {"id": campaign["id"], "instance_id": campaign["instance_id"], "agent_name": self._instance(conn, auth, campaign["instance_id"])["name"],
            "name": "PocketPlan audience expansion" if campaign["offer_id"] == EXPANSION else "PocketPlan freelancer campaign",
            "offer_id": campaign["offer_id"], "state": state, "purchase_id": purchase["id"] if purchase else None,
            "source_job_id": job["id"], "funding_minor": funding, "consumed_minor": consumed, "remaining_minor": funding - consumed,
            "total_cap_minor": campaign["total_cap_minor"], "daily_cap_minor": campaign["daily_cap_minor"], "duration_days": campaign["duration_days"],
            "days_reported": len(metrics), "created_at": campaign["created_at"], "started_at": campaign["started_at"], "completed_at": campaign["completed_at"],
            "metrics": metrics, "latest_metrics": metrics[-1] if metrics else None, "scenario": SCENARIO, "platform": "LaunchPad Ads", "mock": True,
            "delivery_gated": not self._config(conn, auth, campaign["instance_id"])["enabled"]}

    def _ad_report(self, conn, auth, config, occurrence_id, expected_due, campaign):
        job = self._job(conn, auth, campaign["workflow_run_id"])
        snapshot = json.loads(job["config_json"])
        source_config = {**snapshot, "instance_id": config["instance_id"]}
        view = self._ad_campaign_projection(conn, auth, campaign)
        if not view["funding_minor"] or campaign["completed_at"]:
            return False
        day_key = from_iso(expected_due).astimezone(ZoneInfo(snapshot["timezone"])).date().isoformat()
        if conn.execute("SELECT 1 FROM mock_ad_day WHERE campaign_id=? AND day_key=?", (campaign["id"], day_key)).fetchone():
            return False
        self._ad_activate(conn, auth, job)
        day = len(view["metrics"]) + 1
        if day > campaign["duration_days"]:
            return False
        # Per-day finite fixtures. No elapsed-hour multiplication or catch-up spend.
        spend = min(campaign["daily_cap_minor"], view["remaining_minor"])
        main = campaign["offer_id"] == PRIMARY
        impressions, clicks, installs = ((1200, 30, 6), (1350, 36, 8), (1420, 40, 9))[day - 1] if main else ((550, 12, 2), (620, 15, 3), (680, 17, 4))[day - 1]
        consumed = view["consumed_minor"] + spend
        finished = day == campaign["duration_days"] or consumed >= view["funding_minor"]
        total_installs = sum(m["attributed_installs"] for m in view["metrics"]) + installs
        total_clicks = sum(m["clicks"] for m in view["metrics"]) + clicks
        if day == 1:
            recommendation = (f"The first day delivered {clicks} clicks and {installs} attributed installs for ${spend / 100:.2f}. "
                              "Keep the approved targeting and daily cap, and collect the full three-day result before deciding whether to expand. One day is not enough to establish a reliable acquisition cost.")
        elif not finished:
            previous = view["metrics"][-1]
            prior_cpi = previous["spend_minor"] / previous["attributed_installs"] / 100 if previous["attributed_installs"] else None
            today_cpi = spend / installs / 100 if installs else None
            comparison = (f"Today's CPI is ${today_cpi:.2f}, compared with ${prior_cpi:.2f} in the previous report. "
                          if prior_cpi is not None and today_cpi is not None else "There are too few attributed installs to compare daily CPI. ")
            recommendation = (comparison + "Keep the original targeting and finish the approved test before changing the audience. "
                              f"So far, ${consumed / 100:.2f} has produced {total_clicks} clicks and {total_installs} attributed installs; the sample remains small.")
        else:
            aggregate_cpi = f"${consumed / total_installs / 100:.2f}" if total_installs else "unavailable (no attributed installs)"
            recommendation = (f"The completed test consumed ${consumed / 100:.2f} and recorded {total_clicks} clicks and {total_installs} attributed installs "
                              f"at an aggregate CPI of {aggregate_cpi}. The approved campaign is complete and will spend no more. "
                              "Review install quality and retention before committing more funds. If the owner wants another test, prepare a fresh campaign proposal and obtain separate approval; do not renew automatically.")
        expansion_state = None
        if main:
            expansion = conn.execute("SELECT * FROM mock_ad_campaign WHERE instance_id=? AND offer_id=?", (config["instance_id"], EXPANSION)).fetchone()
            if expansion:
                expansion_state = self._ad_campaign_projection(conn, auth, expansion)["state"]
                if expansion_state in ("declined", "cancelled"):
                    recommendation += " The owner declined the optional audience expansion, so this report retains the original freelancer targeting and records no expansion spend."
        spec = deepcopy(next(s for s in snapshot["deliverables"] if s["key"] == "performance_report"))
        spec["key"] = f"report-{campaign['id'][:8]}-{day}"
        spec["name"] = f"{view['name']} · day {day} report"
        spec.update(ad_kind="performance_report", ad_report={"day": day, "reported_at": expected_due, "campaign_name": view["name"], "spend_minor": spend,
            "impressions": impressions, "clicks": clicks, "attributed_installs": installs, "funding_minor": view["funding_minor"], "consumed_minor": consumed,
            "remaining_minor": view["funding_minor"] - consumed, "state": "completed" if finished else "active",
            "total_clicks": total_clicks, "total_attributed_installs": total_installs,
            "expansion_state": expansion_state, "recommendation": recommendation}, ad_campaign_id=campaign["id"])
        report_job = self._ad_job(conn, auth, source_config, occurrence_id, spec)
        conn.execute("INSERT INTO mock_ad_day (id,campaign_id,day_key,day_number,reported_at,spend_minor,impressions,clicks,installs,workflow_run_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), campaign["id"], day_key, day, expected_due, spend, impressions, clicks, installs, report_job["id"]))
        if finished:
            conn.execute("UPDATE mock_ad_campaign SET completed_at=? WHERE id=?", (expected_due, campaign["id"]))
        self.commerce._event(conn, auth, config["instance_id"], "commerce.run_completed", action="campaign_day_reported", campaign_id=campaign["id"], run_id=report_job["id"], spend_minor=spend, day=day)
        return True

    def _advance_ads(self, conn, auth, config, occurrence_id, expected_due):
        outcomes = []
        # Existing campaign snapshots survive later config edits. New explicit
        # configuration cannot rebuy a completed/declined campaign in this fixture.
        for key in ("campaign_plan", "ad_creative"):
            if conn.execute("SELECT 1 FROM mock_workflow_run WHERE instance_id=? AND spec_key=? AND json_extract(config_json,'$.scenario')=?", (config["instance_id"], key, SCENARIO)).fetchone():
                continue
            try:
                with self.db.transaction():
                    self._ad_job(conn, auth, config, occurrence_id, next(s for s in config["deliverables"] if s["key"] == key))
                outcomes.append("Prepared " + key.replace("_", " "))
            except AiclError as error:
                outcomes.append(error.message)
        for offer_id in (PRIMARY, EXPANSION):
            campaign = conn.execute("SELECT * FROM mock_ad_campaign WHERE instance_id=? AND offer_id=?", (config["instance_id"], offer_id)).fetchone()
            if not campaign:
                if offer_id == PRIMARY:
                    required = conn.execute("SELECT COUNT(*) FROM mock_workflow_run WHERE instance_id=? AND spec_key IN ('campaign_plan','ad_creative') AND state IN ('submitted','accepted') AND json_extract(config_json,'$.scenario')=?", (config["instance_id"], SCENARIO)).fetchone()[0]
                    if required < 2:
                        continue
                else:
                    if not conn.execute("SELECT 1 FROM mock_ad_day d JOIN mock_ad_campaign c ON c.id=d.campaign_id JOIN mock_workflow_run w ON w.id=d.workflow_run_id WHERE c.instance_id=? AND c.offer_id=? AND d.day_number=1 AND w.state IN ('submitted','accepted')", (config["instance_id"], PRIMARY)).fetchone():
                        continue
                try:
                    with self.db.transaction():
                        campaign = self._ad_request(conn, auth, config, occurrence_id, offer_id)
                    outcomes.append("Campaign approval requested" if offer_id == PRIMARY else "Optional audience expansion requested")
                except AiclError as error:
                    outcomes.append(error.message)
                    continue
            try:
                with self.db.transaction():
                    if self._ad_report(conn, auth, config, occurrence_id, expected_due, campaign):
                        outcomes.append("Campaign daily report submitted")
                    elif offer_id == PRIMARY and self._ad_campaign_projection(conn, auth, campaign)["state"] in ("declined", "cancelled"):
                        original = json.loads(self._job(conn, auth, campaign["workflow_run_id"])["config_json"])
                        day_key = from_iso(expected_due).astimezone(ZoneInfo(original["timezone"])).date().isoformat()
                        key = "organic-" + day_key
                        if not conn.execute("SELECT 1 FROM mock_workflow_run WHERE instance_id=? AND spec_key=?", (config["instance_id"], key)).fetchone():
                            spec = deepcopy(next(s for s in original["deliverables"] if s["key"] == "performance_report"))
                            spec.update(key=key, name="Organic outreach report", ad_kind="performance_report", ad_report={"organic": True, "reported_at": expected_due})
                            self._ad_job(conn, auth, {**original, "instance_id": config["instance_id"]}, occurrence_id, spec)
                            outcomes.append("Organic outreach report submitted")
            except AiclError as error:
                self._record_block(conn, auth, self._job(conn, auth, campaign["workflow_run_id"]), error)
                outcomes.append(error.message)
        return outcomes

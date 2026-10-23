"""Persistent PocketPlan workflow fixtures: purchases fund finite ad delivery."""
from datetime import timedelta

import pytest

from aicl.control.errors import AiclError
from aicl.db import from_iso
from aicl.workflow.ad_scenario import PRIMARY, EXPANSION, pocketplan_preset
from aicl.workflow.service import MockWorkflowService
from test_mock_commerce import ready


def prepared(build_env, cadence="daily", allowance=4500):
    env, commerce, auth, inst, ops = ready(build_env, limit_minor=allowance)
    workflow = MockWorkflowService(env.db, env.clock, commerce=commerce)
    config = pocketplan_preset()
    config.update(cadence=cadence, timezone="UTC")
    workflow.save_config(auth, inst.id, config, 1)
    workflow.schedule(auth, inst.id, True)
    return env, workflow, commerce, auth, inst, ops


def tick(wf, auth, iid):
    return wf.advance(auth, iid, wf.config(auth, iid)["next_due"])


def campaign(view, offer=PRIMARY):
    return next(c for c in view["campaigns"] if c["offer_id"] == offer)


def pay(wf, commerce, auth, cid, continuation="schedule"):
    wf.set_continuation(auth, cid, continuation)
    purchase = commerce.purchase(auth, cid)
    order_id = commerce.decide_purchase(auth, cid, "approve", purchase["quote_digest"])["order_id"]
    commerce.checkout(auth, order_id, "complete")
    wf.payment_completed(auth, order_id)
    return order_id


def test_plan_and_exact_creative_exist_before_purchase_and_decline_preserves_them(build_env):
    _, wf, commerce, auth, inst, _ = prepared(build_env)
    view = tick(wf, auth, inst.id)
    by_key = {d["spec_key"]: d for d in view["deliverables"]}
    assert {"campaign_plan", "ad_creative", "campaign_authorization"} <= by_key.keys()
    creative = by_key["ad_creative"]["content"]
    quote = view["purchases"][0]["quote"]["campaign"]
    for item in quote["creative"]:
        assert all(item[key] in creative for key in ("headline", "body", "call_to_action"))
    assert quote["targeting"] in creative and quote["destination_url"] in creative
    purchase = view["purchases"][0]
    assert {item["name"] for item in purchase["source_job"]["supporting_work"]} == {"Campaign plan", "Ad creative"}
    assert "required" not in purchase["purchase_reason"]
    assert campaign(view)["state"] == "awaiting_approval"
    assert view["totals"]["ad_funding_minor"] == view["totals"]["ad_consumed_minor"] == 0
    commerce.decide_purchase(auth, purchase["id"], "decline", purchase["quote_digest"])
    later = tick(wf, auth, inst.id)
    assert campaign(later)["state"] == "declined"
    organic = next(d for d in later["deliverables"] if d["name"] == "Organic outreach report")
    assert "no paid delivery or installs are claimed" in organic["content"]
    assert later["totals"]["ad_funding_minor"] == later["totals"]["ad_consumed_minor"] == 0
    assert len(later["purchases"]) == 1
    assert {d["id"] for d in view["deliverables"]} <= {d["id"] for d in later["deliverables"]}


def test_plan_still_exists_when_purchase_allowance_is_insufficient(build_env):
    _, wf, _, auth, inst, _ = prepared(build_env, allowance=2000)
    view = tick(wf, auth, inst.id)
    assert {d["spec_key"] for d in view["deliverables"]} == {"campaign_plan", "ad_creative"}
    assert not view["purchases"] and not view["campaigns"]


def test_three_days_are_finite_and_paid_funding_is_not_double_counted(build_env):
    env, wf, commerce, auth, inst, _ = prepared(build_env)
    first = tick(wf, auth, inst.id)
    request = campaign(first)["purchase_id"]
    pay(wf, commerce, auth, request)
    funded = wf.overview(auth, inst.id)
    assert campaign(funded)["state"] == "funded"
    assert campaign(funded)["days_reported"] == 0
    assert funded["totals"]["ad_funding_minor"] == 3000
    assert funded["totals"]["ad_consumed_minor"] == 0
    first_day = tick(wf, auth, inst.id)
    assert campaign(first_day)["state"] == "active"
    assert campaign(first_day)["consumed_minor"] == 1000
    assert len(first_day["purchases"]) == 2
    day_one_report = next(d for d in first_day["deliverables"] if "day 1 report" in d["name"])
    assert "collect the full three-day result" in day_one_report["content"]
    expansion = next(p for p in first_day["purchases"] if p["quote"]["offer_id"] == EXPANSION)
    assert any("day 1 report" in s["name"] for s in expansion["source_work"])
    commerce.decide_purchase(auth, expansion["id"], "decline", expansion["quote_digest"])
    wf = MockWorkflowService(env.db, env.clock, commerce=commerce)  # Survives service recreation.
    second_day = tick(wf, auth, inst.id)
    assert campaign(second_day)["consumed_minor"] == 2000
    day_two_report = next(d for d in second_day["deliverables"] if "day 2 report" in d["name"])
    assert "Today's CPI is $1.25, compared with $1.67" in day_two_report["content"]
    assert "owner declined the optional audience expansion" in day_two_report["content"]
    complete = tick(wf, auth, inst.id)
    main = campaign(complete)
    assert (main["state"], main["consumed_minor"], main["remaining_minor"], main["days_reported"]) == ("completed", 3000, 0, 3)
    assert campaign(complete, EXPANSION)["state"] == "declined"
    day_three_report = next(d for d in complete["deliverables"] if "day 3 report" in d["name"])
    assert "$30.00 and recorded 106 clicks and 23 attributed installs" in day_three_report["content"]
    assert "aggregate CPI of $1.30" in day_three_report["content"]
    assert "fresh campaign proposal and obtain separate approval" in day_three_report["content"]
    assert sum(x["spend_minor"] for x in main["metrics"]) == 3000
    assert all(x["spend_minor"] <= 1000 for x in main["metrics"])
    assert main["metrics"][0]["cpc_minor"] == round(1000 / 30, 2)
    assert main["metrics"][0]["cpi_minor"] == round(1000 / 6, 2)
    assert complete["totals"]["purchase_spent_minor"] == complete["totals"]["ad_funding_minor"] == 3000
    assert sum(row["amount_usd"] for row in complete["cost_rows"] if row["category"] == "Ad funding") == 30
    before = commerce.dashboard(auth, inst.id)["balance_micro_usd"]
    for _ in range(3):
        repeated = tick(wf, auth, inst.id)
    assert len(repeated["purchases"]) == 2
    assert campaign(repeated)["metrics"] == main["metrics"]
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == before


def test_hourly_ticks_replay_and_callbacks_never_duplicate_daily_delivery(build_env):
    _, wf, commerce, auth, inst, _ = prepared(build_env, cadence="hourly")
    first = tick(wf, auth, inst.id)
    pid = campaign(first)["purchase_id"]
    order = pay(wf, commerce, auth, pid, continuation="now")
    assert campaign(wf.overview(auth, inst.id))["state"] == "active"
    assert campaign(wf.overview(auth, inst.id))["metrics"] == []
    day = tick(wf, auth, inst.id)
    due = day["occurrence"]["scheduled_for"]
    for _ in range(3):
        wf.payment_completed(auth, order)
        assert wf.advance(auth, inst.id, due)["occurrence"]["replayed"]
    same_day = tick(wf, auth, inst.id)
    assert campaign(same_day)["days_reported"] == 1
    assert campaign(same_day)["consumed_minor"] == 1000


def test_campaign_and_report_keep_original_config_after_edits_and_versions(build_env):
    _, wf, commerce, auth, inst, _ = prepared(build_env)
    first = tick(wf, auth, inst.id)
    source = first["purchases"][0]["source_job"]["id"]
    original = wf.job(auth, source)
    updated = pocketplan_preset()
    updated.update(goal="A changed goal for future work", inputs="Different future inputs")
    wf.save_config(auth, inst.id, updated, wf.config(auth, inst.id)["version"])
    pay(wf, commerce, auth, first["purchases"][0]["id"])
    view = tick(wf, auth, inst.id)
    report = next(d for d in view["deliverables"] if "day 1 report" in d["name"])
    assert report["goal"] == original["goal"]
    assert report["config_version"] == original["config_version"]
    wf.review(auth, report["id"], "request_changes", "Make the next step shorter", report["version"])
    revised = tick(wf, auth, inst.id)
    versions = wf.deliverable(auth, report["id"])["versions"]
    assert [v["version"] for v in versions] == [2, 1]
    assert "Make the next step shorter" in versions[0]["content"]
    assert campaign(revised)["days_reported"] == 2


def test_paused_or_disabled_agent_cannot_deliver_but_funds_are_retained(build_env):
    env, wf, commerce, auth, inst, ops = prepared(build_env)
    first = tick(wf, auth, inst.id)
    order = pay(wf, commerce, auth, first["purchases"][0]["id"])
    wf.schedule(auth, inst.id, False)
    wf.set_continuation(auth, first["purchases"][0]["id"], "now")
    wf.payment_completed(auth, order)
    assert campaign(wf.overview(auth, inst.id))["state"] == "funded"
    assert campaign(wf.overview(auth, inst.id))["funding_minor"] == 3000
    wf.schedule(auth, inst.id, True)
    ops.set_capability(auth, inst.id, env.instances.get(auth, inst.id).version, "inference", False)
    blocked = tick(wf, auth, inst.id)
    assert campaign(blocked)["state"] == "funded" and campaign(blocked)["days_reported"] == 0
    assert blocked["totals"]["ad_consumed_minor"] == 0


def test_expired_quote_refresh_keeps_offer_and_does_not_rebuy_campaign(build_env):
    env, wf, commerce, auth, inst, _ = prepared(build_env)
    first = tick(wf, auth, inst.id)
    original = first["purchases"][0]
    env.clock.set(from_iso(original["expires_at"]) + timedelta(seconds=1))
    refreshed = wf.refresh_purchase(auth, original["id"])
    assert refreshed["quote"]["offer_id"] == PRIMARY
    assert refreshed["quote"]["amount_minor"] == 3000
    pay(wf, commerce, auth, refreshed["id"])
    day = tick(wf, auth, inst.id)
    assert len([c for c in day["campaigns"] if c["offer_id"] == PRIMARY]) == 1
    assert campaign(day)["purchase_id"] == refreshed["id"]
    assert campaign(day)["consumed_minor"] == 1000


def test_owner_isolation_and_read_only_projections(build_env):
    env, wf, _, auth, inst, _ = prepared(build_env)
    tick(wf, auth, inst.id)
    stranger, _ = env.new_instance()
    assert wf.overview(stranger)["campaigns"] == []
    with pytest.raises(AiclError):
        wf.overview(stranger, inst.id)
    with env.db.reader() as conn:
        before = list(conn.iterdump())
    wf.overview(auth, inst.id)
    with env.db.reader() as conn:
        assert list(conn.iterdump()) == before


def test_old_paid_template_does_not_satisfy_ad_funding(build_env):
    _, wf, commerce, auth, inst, _ = prepared(build_env, allowance=4600)
    old = commerce.start_run(auth, inst.id, "legacy-template")
    p = old["purchase"]
    order = commerce.decide_purchase(auth, p["id"], "approve", p["quote_digest"])["order_id"]
    commerce.checkout(auth, order, "complete")
    first = tick(wf, auth, inst.id)
    assert campaign(first)["state"] == "awaiting_approval"
    assert campaign(first)["funding_minor"] == 0
    assert len(first["purchases"]) == 2


def test_both_campaigns_can_be_funded_and_finish_without_extra_charges(build_env):
    _, wf, commerce, auth, inst, _ = prepared(build_env)
    first = tick(wf, auth, inst.id)
    pay(wf, commerce, auth, campaign(first)["purchase_id"])
    first_day = tick(wf, auth, inst.id)
    pay(wf, commerce, auth, campaign(first_day, EXPANSION)["purchase_id"])
    for _ in range(3):
        view = tick(wf, auth, inst.id)
    assert {c["state"] for c in view["campaigns"]} == {"completed"}
    assert view["totals"]["ad_funding_minor"] == view["totals"]["ad_consumed_minor"] == 4500
    assert view["totals"]["ad_remaining_minor"] == 0
    assert commerce.dashboard(auth, inst.id)["policy"]["spent_minor"] == 4500
    assert len([row for row in view["cost_rows"] if row["category"] == "Ad funding"]) == 2


def test_incomplete_plan_is_revised_before_purchase_is_requested(build_env):
    _, wf, _, auth, inst, _ = prepared(build_env)
    config = pocketplan_preset()
    config["deliverables"][0]["validation_scenario"] = "needs_work_once"
    wf.save_config(auth, inst.id, config, wf.config(auth, inst.id)["version"])
    first = tick(wf, auth, inst.id)
    assert not first["purchases"]
    assert next(d for d in first["deliverables"] if d["spec_key"] == "campaign_plan")["state"] == "needs_work"
    second = tick(wf, auth, inst.id)
    assert len(second["purchases"]) == 1
    for source in second["purchases"][0]["source_work"]:
        assert wf.deliverable(auth, source["deliverable_id"])["state"] == "submitted"


def test_expansion_waits_until_first_daily_report_passes_its_checks(build_env):
    _, wf, commerce, auth, inst, _ = prepared(build_env)
    config = pocketplan_preset()
    config["deliverables"][2]["validation_scenario"] = "needs_work_once"
    wf.save_config(auth, inst.id, config, wf.config(auth, inst.id)["version"])
    first = tick(wf, auth, inst.id)
    pay(wf, commerce, auth, campaign(first)["purchase_id"])
    first_day = tick(wf, auth, inst.id)
    assert len(first_day["campaigns"]) == len(first_day["purchases"]) == 1
    report = next(d for d in first_day["deliverables"] if "day 1 report" in d["name"])
    assert report["state"] == "needs_work"
    second_day = tick(wf, auth, inst.id)
    assert len(second_day["campaigns"]) == len(second_day["purchases"]) == 2
    expansion = next(p for p in second_day["purchases"] if p["quote"]["offer_id"] == EXPANSION)
    supporting = [s for s in expansion["source_work"] if "day 1 report" in s["name"]]
    assert len(supporting) == 1
    corrected = wf.deliverable(auth, supporting[0]["deliverable_id"])
    assert corrected["version"] == 2 and corrected["state"] == "submitted"

"""Studio reads real SQLite facts without executing work or exposing private data."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.db import to_iso
from aicl.studio.data import StudioData
from test_scheduled_owner_workflow import prepared, spec, tick


def studio(env):
    return StudioData(SimpleNamespace(db=env.db, clock=env.clock))


def test_owner_scope_filters_unknown_agent_and_read_only_payload(build_env):
    env, wf, _, auth, inst, _ = prepared(build_env)
    view, _ = tick(wf, auth, inst.id)
    other_auth, other = env.new_instance()
    with env.db.reader() as conn:
        before = conn.execute("SELECT count(*) FROM audit_event").fetchone()[0]
    data = studio(env).snapshot(auth)
    assert data["agents"] == [{"id": inst.id, "name": inst.name}]
    assert data["totals"]["job_count"] == 1
    assert data["jobs"][0]["id"] == view["runs"][0]["id"]
    serialized = json.dumps(data)
    assert other.id not in serialized
    assert "private instructions" not in serialized
    assert view["deliverables"][0]["content"] not in serialized
    with env.db.reader() as conn:
        assert conn.execute("SELECT count(*) FROM audit_event").fetchone()[0] == before
    for identity in (other.id, "does-not-exist"):
        with pytest.raises(AiclError) as caught:
            studio(env).snapshot(auth, instance_id=identity)
        assert caught.value.error == "not_found"
    # Tenant equality alone is insufficient: owner must also match.
    assert studio(env).snapshot(replace(auth, owner_id=other_auth.owner_id))["agents"] == []
    for invalid_auth in (None, replace(auth, expires_at=env.clock.now())):
        with pytest.raises(AiclError) as caught:
            studio(env).snapshot(invalid_auth)
        assert caught.value.error == "unauthenticated"


@pytest.mark.parametrize("filters", [
    {"date_from": "2026-10-31", "date_to": "2026-10-01"},
    {"date_from": "2026-02-30"}, {"date_to": "2026-1-1"}, {"timezone": "Not/A_Zone"},
])
def test_invalid_filters_are_rejected(build_env, filters):
    env = build_env()
    auth, _ = env.new_instance()
    with pytest.raises(AiclError) as caught:
        studio(env).snapshot(auth, **filters)
    assert caught.value.error == "validation_failed"


def test_agent_filter_applies_to_every_fact_but_preserves_owner_dropdown(build_env):
    env, wf, commerce, auth, inst, _ = prepared(build_env)
    tick(wf, auth, inst.id)
    _, second = env.new_instance()
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET tenant_id=?,owner_id=?,name='Other agent' WHERE id=?",
                     (auth.tenant_id, auth.owner_id, second.id))
    order = commerce.create_topup(auth, second.id, 1000, "other-agent-funding")
    commerce.select_payment_buyer(auth, order["id"], "demo-buyer")
    commerce.checkout(auth, order["id"], "complete")
    data = studio(env).snapshot(auth, instance_id=second.id)
    assert {row["id"] for row in data["agents"]} == {inst.id, second.id}
    assert data["jobs"] == data["attention"] == []
    assert {row["agent_id"] for row in data["costs"] + data["agent_summary"]} == {second.id}
    assert data["totals"]["funding_usd"] == data["current"]["service_credit_usd"] == 10
    assert data["totals"]["inference_usd"] == data["totals"]["job_count"] == 0


def test_fixture_cost_links_canonical_job_and_current_attention_ignores_period(build_env):
    env, wf, _, auth, inst, _ = prepared(build_env, spec(purchase=True))
    view, _ = tick(wf, auth, inst.id)
    job = view["runs"][0]
    data = studio(env).snapshot(auth)
    inference = next(row for row in data["costs"] if row["category"] == "inference")
    assert inference["job_id"] == job["id"]
    assert inference["evidence_url"] == "/audit/jobs/" + job["id"]
    assert inference["provenance"] == "fixture" and inference["input_tokens"] > 0
    assert data["totals"]["purchase_usd"] == 0  # A reservation is not a purchase.
    assert data["totals"]["funding_usd"] == 5
    assert data["current"]["held_usd"] == 1
    assert data["totals"]["pending_count"] == 1
    assert data["attention"][0]["evidence_url"].startswith("/requests?selected=purchase%3A")
    old = studio(env).snapshot(auth, date_from="2025-01-01", date_to="2025-01-01")
    assert old["costs"] == old["jobs"] == []
    assert old["current"] == data["current"]
    assert old["attention"] == data["attention"]
    assert old["totals"]["pending_count"] == 1
    assert old["totals"]["inference_usd"] == old["totals"]["funding_usd"] == 0


def test_local_date_boundary_and_payment_capture_date_drive_period_accounting(build_env):
    env, wf, commerce, auth, inst, _ = prepared(build_env, spec(purchase=True))
    # 03:59 UTC is still Oct 14 in New York. 04:00 starts Oct 15.
    env.clock.advance(datetime(2026, 10, 15, 3, 59, tzinfo=timezone.utc) - env.clock.now())
    view, _ = tick(wf, auth, inst.id)
    purchase = view["purchases"][0]
    approved = commerce.decide_purchase(auth, purchase["id"], "approve", purchase["quote_digest"])
    first = commerce.create_topup(auth, inst.id, 500, "before-midnight")
    commerce.select_payment_buyer(auth, first["id"], "demo-buyer")
    commerce.checkout(auth, first["id"], "complete")
    env.clock.advance(timedelta(minutes=1))
    second = commerce.create_topup(auth, inst.id, 1000, "at-midnight")
    commerce.select_payment_buyer(auth, second["id"], "demo-buyer")
    commerce.checkout(auth, second["id"], "complete")
    commerce.checkout(auth, approved["order_id"], "complete")
    yesterday = studio(env).snapshot(auth, date_from="2026-10-14", date_to="2026-10-14")
    today = studio(env).snapshot(auth, date_from="2026-10-15", date_to="2026-10-15")
    assert yesterday["totals"]["funding_usd"] == 10
    assert today["totals"]["funding_usd"] == 10
    assert yesterday["totals"]["purchase_usd"] == 0
    assert today["totals"]["purchase_usd"] == 1  # Captured now, requested yesterday.
    assert yesterday["totals"]["job_count"] == 1 and today["totals"]["job_count"] == 0
    assert today["current"] == yesterday["current"]
    captured = next(row for row in today["costs"] if row["category"] == "merchant_purchase")
    assert captured["job_id"] == view["runs"][0]["id"]
    assert captured["evidence_url"] == "/commerce/orders/" + approved["order_id"]


def test_provider_metering_uses_attempt_fk_and_never_infers_payment_mode_from_settings(build_env):
    from test_workflow_inference import live
    env, wf, commerce, auth, inst, _, _ = live(build_env)
    view = wf.advance(auth, inst.id, wf.config(auth, inst.id)["next_due"])
    data = studio(env).snapshot(auth)
    inference, = [row for row in data["costs"] if row["category"] == "inference"]
    expected = next(row for row in view["runs"] if row["spec_key"] == "campaign_plan")
    assert inference["job_id"] == expected["id"]
    assert inference["provenance"] == "provider_reported"
    assert inference["model"] == "gpt-6-sol"
    assert (inference["input_tokens"], inference["output_tokens"], inference["amount_usd"]) == (100, 50, .0007)
    assert next(row for row in data["costs"] if row["category"] == "service_funding")["provenance"] == "fixture"
    # Stored transport, not current process configuration, identifies payments.
    with env.db.transaction() as conn:
        conn.execute("UPDATE mock_commerce_order SET payment_transport='paypal_sandbox' WHERE purpose='service_topup'")
    updated = studio(env).snapshot(auth)
    assert next(row for row in updated["costs"] if row["category"] == "service_funding")["provenance"] == "paypal_sandbox"
    assert updated["current"]["service_credit_usd"] == commerce.dashboard(auth, inst.id)["balance_micro_usd"] / 1_000_000


def test_unknown_inference_keeps_credit_hold_without_claiming_measured_cost(build_env):
    from aicl.workflow.openai_inference import InferenceUnknownOutcomeError
    from test_workflow_inference import live
    env, wf, commerce, auth, inst, _, _ = live(build_env, error=InferenceUnknownOutcomeError("timeout"))
    wf.advance(auth, inst.id, wf.config(auth, inst.id)["next_due"])
    data = studio(env).snapshot(auth)
    assert data["totals"]["inference_usd"] == 0
    assert data["current"]["held_usd"] == .052
    assert data["current"]["service_credit_usd"] == 4.948
    job = next(row for row in data["jobs"] if row["output_name"] == "Campaign plan")
    assert job["provenance"] == "application_record"
    assert data["current"]["service_credit_usd"] == commerce.dashboard(auth, inst.id)["balance_micro_usd"] / 1_000_000


def test_shared_dispatch_compute_is_counted_once_without_fabricated_job_allocation(build_env):
    env, wf, commerce, auth, inst, _ = prepared(build_env, spec("one"), spec("two"))
    view, _ = tick(wf, auth, inst.id)
    env.clock.advance(timedelta(days=8))
    with env.db.transaction() as conn:
        occurrence = conn.execute("SELECT occurrence_id FROM mock_workflow_run WHERE id=?", (view["runs"][0]["id"],)).fetchone()[0]
        hold = env.budget.reserve(conn, inst.id, "studio-compute", Estimate(0, 0, 1), price_table_version="render-flex-bound-2026-10-22")
        usage = env.budget.settle(conn, hold.id, MeasuredUsage(0, 0, 1))
        timestamp = to_iso(env.clock.now())
        conn.execute("INSERT INTO render_dispatch(id,instance_id,scheduled_for,kind,config_json,state,hold_id,occurrence_id,created_at) "
                     "VALUES ('dispatch',?,?,'schedule','{}','completed',?,?,?)", (inst.id, timestamp, hold.id, occurrence, timestamp))
        conn.execute("INSERT INTO render_compute_usage(dispatch_id,instance_id,hold_id,elapsed_seconds,charged_minutes,cost_micro_usd,created_at) "
                     "VALUES ('dispatch',?,?,10,1,?,?)", (inst.id, hold.id, usage.compute_micro_usd, timestamp))
    data = studio(env).snapshot(auth)
    compute, = [row for row in data["costs"] if row["category"] == "compute_estimate"]
    assert compute["job_id"] is None and compute["provenance"] == "runtime_estimate"
    assert data["totals"]["compute_estimate_usd"] == .006667
    assert data["agent_summary"][0]["compute_estimate_usd"] == .006667
    assert sum(row["compute_estimate_usd"] for row in data["jobs"]) == 0
    assert data["current"]["service_credit_usd"] == commerce.dashboard(auth, inst.id)["balance_micro_usd"] / 1_000_000
    budget = env.budget.read_budget(inst.id)
    assert data["current"]["budget_remaining_usd"] == sum(
        min(windows["day"].available, windows["month"].available) for windows in budget.windows.values()) / 1_000_000


def test_accepted_count_uses_latest_output_only_for_period_jobs(build_env):
    env, wf, _, auth, inst, _ = prepared(build_env)
    view, _ = tick(wf, auth, inst.id)
    output = view["deliverables"][0]
    wf.review(auth, output["id"], "accept", "", output["version"])
    data = studio(env).snapshot(auth)
    assert data["totals"]["accepted_count"] == 1
    assert data["jobs"][0]["review_status"] == "accepted"
    assert studio(env).snapshot(auth, date_from="2027-01-01")["totals"]["accepted_count"] == 0


def test_submitted_output_requires_attention_across_period_filters_and_clears_after_review(build_env):
    env, wf, _, auth, inst, _ = prepared(build_env)
    view, _ = tick(wf, auth, inst.id)
    output = view["deliverables"][0]
    data = studio(env).snapshot(auth)
    review, = data["attention"]
    assert review["kind"] == "deliverable_review"
    assert review["title"] == output["name"] and review["status"] == "submitted"
    assert review["evidence_url"] == "/audit/deliverables/" + output["id"]
    assert data["totals"]["pending_count"] == data["agent_summary"][0]["pending_count"] == 1
    past = studio(env).snapshot(auth, date_from="2025-01-01", date_to="2025-01-01")
    assert past["jobs"] == [] and past["attention"] == [review]
    wf.review(auth, output["id"], "request_changes", "Add a specific next action.", output["version"])
    assert studio(env).snapshot(auth)["attention"] == []
    revised, _ = tick(wf, auth, inst.id)
    latest = next(item for item in revised["deliverables"] if item["latest"])
    latest_review, = studio(env).snapshot(auth)["attention"]
    assert latest_review["evidence_url"] == "/audit/deliverables/" + latest["id"]
    assert latest["id"] != output["id"]
    wf.review(auth, latest["id"], "accept", "", latest["version"])
    accepted = studio(env).snapshot(auth)
    assert accepted["attention"] == [] and accepted["totals"]["pending_count"] == 0
    assert accepted["agent_summary"][0]["pending_count"] == 0

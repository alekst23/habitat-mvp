"""Mock scheduled owner journey: persisted state and real local control/accounting guards."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import pytest

from aicl.commerce.service import MockCommerceService
from aicl.control.errors import AiclError
from aicl.control.instances import Limits
from aicl.db import from_iso
from aicl.workflow.service import MockWorkflowService
from test_mock_commerce import ready
from test_payment_workflow import PaymentPort


def spec(key="report", *, purchase=False, validation="pass"):
    return {
        "key": key,
        "name": f"{key.title()} deliverable",
        "description": "A useful report with a headline, recommendation and clear next action.",
        "criteria": ["Include a headline", "Include a clear next action"],
        "purchase_required": purchase,
        "validation_scenario": validation,
    }


def configuration(*deliverables, goal="Help the owner plan a community garden"):
    return {
        "goal": goal,
        "inputs": "Audience: local residents. Keep the language concise.",
        "deliverables": list(deliverables or (spec(),)),
        "cadence": "hourly",
        "timezone": "UTC",
    }


def prepared(build_env, *deliverables, funded=True):
    env, payments, auth, inst, ops = ready(build_env, funded=funded, limit_minor=2000)
    workflow = MockWorkflowService(env.db, env.clock, commerce=payments)
    workflow.save_config(auth, inst.id, configuration(*deliverables), 1)
    workflow.schedule(auth, inst.id, True)
    return env, workflow, payments, auth, inst, ops


def tick(workflow, auth, instance_id):
    due = workflow.config(auth, instance_id)["next_due"]
    return workflow.advance(auth, instance_id, due), due


def current_outputs(view):
    return [item for item in view["deliverables"] if item["latest"]]


def expect_error(code, operation):
    with pytest.raises(AiclError) as rejected:
        operation()
    assert rejected.value.error == code
    return rejected.value


def approved(workflow, payments, auth, purchase_id, continuation):
    workflow.set_continuation(auth, purchase_id, continuation)
    request = payments.purchase(auth, purchase_id)
    return payments.decide_purchase(auth, purchase_id, "approve", request["quote_digest"])


def test_schedule_produces_purchase_free_output_once_and_keeps_configuration_snapshot(build_env):
    env, workflow, payments, auth, inst, _ = prepared(build_env)
    config = workflow.config(auth, inst.id)
    assert config["goal"] == configuration()["goal"]
    assert config["deliverables"][0]["criteria"] == spec()["criteria"]
    # A saved/enabled schedule is not itself permission to start a manual task.
    assert workflow.overview(auth, inst.id)["runs"] == []
    original_clock = env.clock.now()
    view, due = tick(workflow, auth, inst.id)
    assert env.clock.now() == original_clock  # Demo time must not expire the owner session.
    output, = current_outputs(view)
    assert output["state"] == "submitted" and output["version"] == 1
    assert output["goal"] in output["content"]
    assert all(result["passed"] for result in output["criteria"])
    assert [result["criterion"] for result in output["criteria"]] == spec()["criteria"]
    assert view["purchases"] == []
    run, = view["runs"]
    assert run["purchase_id"] is None and run["inference_cost_micro_usd"] > 0
    balance = payments.dashboard(auth, inst.id)["balance_micro_usd"]
    replay = workflow.advance(auth, inst.id, due)
    assert replay["occurrence"]["replayed"]
    assert len(replay["runs"]) == len(replay["deliverables"]) == 1
    assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == balance

    edited = configuration(spec(), goal="Plan a neighborhood library instead")
    edited["deliverables"][0]["criteria"] = ["Include a library opening plan"]
    workflow.save_config(auth, inst.id, edited, config["version"])
    expect_error("conflict", lambda: workflow.save_config(auth, inst.id, edited, config["version"]))
    restarted = MockWorkflowService(env.db, env.clock)
    assert restarted.config(auth, inst.id)["goal"] == edited["goal"]
    old = restarted.deliverable(auth, output["id"])
    assert old["goal"] == config["goal"]
    assert old["config_snapshot"]["deliverables"][0]["criteria"] == spec()["criteria"]
    assert old["config_version"] != restarted.config(auth, inst.id)["version"]
    restarted.review(auth, output["id"], "accept", "", output["version"])
    later, _ = tick(restarted, auth, inst.id)
    newest = next(item for item in later["deliverables"] if item["goal"] == edited["goal"])
    assert newest["goal"] == edited["goal"]
    assert [item["criterion"] for item in newest["criteria"]] == edited["deliverables"][0]["criteria"]


def test_needs_work_cannot_be_submitted_or_accepted_and_is_corrected_on_next_tick(build_env):
    _, workflow, _, auth, inst, _ = prepared(build_env, spec(validation="needs_work_once"))
    first, _ = tick(workflow, auth, inst.id)
    failed, = current_outputs(first)
    assert failed["state"] == "needs_work"
    assert any(not item["passed"] and item["reason"] for item in failed["criteria"])
    assert not any(item["state"] == "submitted" for item in first["deliverables"])
    with pytest.raises(AiclError):
        workflow.review(auth, failed["id"], "accept", "", failed["version"])
    corrected, _ = tick(workflow, auth, inst.id)
    output, = current_outputs(corrected)
    assert output["state"] == "submitted" and output["version"] == 2
    assert all(item["passed"] for item in output["criteria"])
    history = workflow.deliverable(auth, output["id"])["versions"]
    assert {item["version"] for item in history} == {1, 2}
    assert next(item for item in history if item["version"] == 1)["state"] == "needs_work"


def test_owner_feedback_targets_version_and_revision_keeps_original_criteria(build_env):
    _, workflow, _, auth, inst, _ = prepared(build_env)
    initial, _ = tick(workflow, auth, inst.id)
    first, = current_outputs(initial)
    # Waiting for review must not create another copy on each scheduled occurrence.
    unchanged, _ = tick(workflow, auth, inst.id)
    assert len(unchanged["deliverables"]) == 1
    expect_error("conflict", lambda: workflow.review(auth, first["id"], "accept", "", 99))
    expect_error("validation_failed", lambda: workflow.review(auth, first["id"], "request_changes", "", 1))
    feedback = "Add a specific volunteer sign-up deadline."
    reviewed = workflow.review(auth, first["id"], "request_changes", feedback, 1)
    assert reviewed["state"] == "changes_requested" and reviewed["feedback"] == feedback
    assert len(workflow.overview(auth, inst.id)["deliverables"]) == 1
    config = workflow.config(auth, inst.id)
    edited = configuration(goal="Future unrelated work")
    edited["deliverables"][0]["criteria"] = ["Unrelated new criterion"]
    workflow.save_config(auth, inst.id, edited, config["version"])
    revised, _ = tick(workflow, auth, inst.id)
    latest, = current_outputs(revised)
    assert latest["version"] == 2 and latest["state"] == "submitted"
    assert feedback in latest["content"]
    assert latest["config_version"] == first["config_version"]
    assert [item["criterion"] for item in latest["criteria"]] == spec()["criteria"]
    # A stale browser tab reviewing v1 must never accept the newly submitted v2.
    expect_error("conflict", lambda: workflow.review(auth, first["id"], "accept", "", 1))
    assert workflow.deliverable(auth, latest["id"])["state"] == "submitted"
    accepted = workflow.review(auth, latest["id"], "accept", "", 2)
    assert accepted["state"] == "accepted"
    history = workflow.deliverable(auth, latest["id"])["versions"]
    prior = next(item for item in history if item["version"] == 1)
    assert prior["state"] == "changes_requested" and prior["feedback"] == feedback


def test_purchase_inbox_spans_independent_runs_without_duplicate_waiting_requests(build_env):
    _, workflow, payments, auth, inst, _ = prepared(
        build_env, spec("poster", purchase=True), spec("newsletter", purchase=True), spec("summary"))
    first, _ = tick(workflow, auth, inst.id)
    assert len(first["purchases"]) == 2
    assert len({item["run_id"] for item in first["purchases"]}) == 2
    assert {item["state"] for item in first["purchases"]} == {"awaiting_approval"}
    assert len(current_outputs(first)) == 1
    assert current_outputs(first)[0]["state"] == "submitted"
    balance = payments.dashboard(auth, inst.id)["balance_micro_usd"]
    again, _ = tick(workflow, auth, inst.id)
    assert {item["id"] for item in again["purchases"]} == {item["id"] for item in first["purchases"]}
    assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == balance
    request = payments.purchase(auth, first["purchases"][0]["id"])
    payments.decide_purchase(auth, request["id"], "decline", request["quote_digest"])
    inbox = workflow.overview(auth)["purchases"]
    assert len(inbox) == 2 and {item["state"] for item in inbox} == {"declined", "awaiting_approval"}
    assert payments.dashboard(auth, inst.id)["policy"]["held_minor"] == 100
    assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == balance


def test_purchase_review_links_original_job_snapshot_and_retains_refreshed_quotes(build_env):
    env, workflow, payments, auth, inst, _ = prepared(
        build_env, spec("poster", purchase=True), spec("newsletter", purchase=True))
    first, due = tick(workflow, auth, inst.id)
    by_name = {item["deliverable_name"]: item for item in first["purchases"]}
    poster, newsletter = by_name["Poster deliverable"], by_name["Newsletter deliverable"]
    assert poster["quote"]["item_name"] == newsletter["quote"]["item_name"]  # Same resource, distinct work.
    assert poster["source_job"]["id"] != newsletter["source_job"]["id"]
    original = workflow.job(auth, poster["source_job"]["id"])
    assert original["scheduled_for"] == due and original["timezone"] == "UTC"
    assert original["deliverable_description"] == spec()["description"]
    assert original["completion_criteria"] == spec()["criteria"]
    assert original["latest_deliverable"] is None and original["deliverables"] == []
    assert [item["id"] for item in original["purchases"]] == [poster["id"]]
    assert original["purchase"]["id"] == poster["id"]
    assert "saved requirements call for a purchased resource" in poster["purchase_reason"]

    edited = configuration(spec("poster", purchase=True), goal="An entirely different future goal")
    edited["deliverables"][0].update(description="New future description", criteria=["New future criterion"])
    edited["timezone"] = "America/New_York"
    workflow.save_config(auth, inst.id, edited, workflow.config(auth, inst.id)["version"])
    env.clock.set(from_iso(poster["expires_at"]) + timedelta(seconds=1))
    fresh = workflow.refresh_purchase(auth, poster["id"])
    refreshed = workflow.job(auth, original["id"])
    assert refreshed["goal"] == original["goal"]
    assert refreshed["config_version"] == original["config_version"]
    assert refreshed["timezone"] == "UTC"
    assert refreshed["completion_criteria"] == original["completion_criteria"]
    assert refreshed["deliverable_description"] == original["deliverable_description"]
    assert {item["id"] for item in refreshed["purchases"]} == {poster["id"], fresh["id"]}
    assert refreshed["purchase"]["id"] == fresh["id"]
    assert {item["source_job"]["id"] for item in refreshed["purchases"]} == {original["id"]}
    assert next(item for item in refreshed["purchases"] if item["id"] == poster["id"])["current_proposal"] is False
    assert newsletter["id"] not in {item["id"] for item in refreshed["purchases"]}

    order = approved(workflow, payments, auth, fresh["id"], "now")["order_id"]
    payments.checkout(auth, order, "complete")
    workflow.payment_completed(auth, order)
    produced = workflow.job(auth, original["id"])
    output, = produced["deliverables"]
    assert produced["latest_deliverable"] == {
        "id": output["id"], "name": output["name"], "state": "submitted", "version": 1}
    workflow.review(auth, output["id"], "request_changes", "Shorten this version", 1)
    tick(workflow, auth, inst.id)
    revised = workflow.job(auth, original["id"])
    assert [item["version"] for item in revised["deliverables"]] == [2, 1]
    assert revised["latest_deliverable"]["version"] == 2

    stranger, _ = env.new_instance()
    with env.db.reader() as conn:
        before = list(conn.iterdump())
    expect_error("not_found", lambda: workflow.job(stranger, original["id"]))
    expect_error("not_found", lambda: workflow.job(auth, "missing-job"))
    assert workflow.job(auth, original["id"])["id"] == original["id"]
    assert workflow.job_for_purchase(auth, poster["id"])["id"] == original["id"]
    workflow.overview(auth, inst.id)
    with env.db.reader() as conn:
        assert list(conn.iterdump()) == before


def test_legacy_purchase_keeps_manual_brief_without_scheduled_job_link(build_env):
    env, payments, auth, inst, _ = ready(build_env, limit_minor=2000)
    run = payments.start_run(auth, inst.id, "legacy-purchase-context")
    workflow = MockWorkflowService(env.db, env.clock, commerce=payments)
    purchase, = workflow.overview(auth, inst.id)["purchases"]
    assert purchase["source_job"] is None and purchase["workflow_run_id"] is None
    assert purchase["legacy_source"]["id"] == run["id"]
    assert purchase["legacy_source"]["brief"] == run["brief"]
    assert purchase["goal"] == run["brief"]["goal"]
    assert purchase["legacy_source"]["deliverable_id"] is None
    expect_error("not_found", lambda: workflow.job(auth, run["id"]))


@pytest.mark.parametrize("continuation", ["now", "schedule"])
def test_approval_never_resumes_without_payment_and_delivery_then_resumes_once(build_env, continuation):
    _, workflow, payments, auth, inst, _ = prepared(build_env, spec(purchase=True))
    first, _ = tick(workflow, auth, inst.id)
    request, = first["purchases"]
    approved_request = approved(workflow, payments, auth, request["id"], continuation)
    order_id = approved_request["order_id"]
    scheduled_due = workflow.config(auth, inst.id)["next_due"]
    workflow.payment_completed(auth, order_id)
    workflow.payment_completed(auth, {**payments.order(auth, order_id), "state": "completed"})
    assert workflow.overview(auth, inst.id)["deliverables"] == []
    payments.checkout(auth, order_id, "pending")
    workflow.payment_completed(auth, order_id)
    pending, _ = tick(workflow, auth, inst.id)
    assert pending["deliverables"] == [] and len(pending["runs"]) == 1
    assert not payments.purchase(auth, request["id"])["fulfillment"]

    payments.checkout(auth, order_id, "complete")
    before = payments.dashboard(auth, inst.id)["balance_micro_usd"]
    due_after_wait = workflow.config(auth, inst.id)["next_due"]
    workflow.payment_completed(auth, order_id)
    after = workflow.overview(auth, inst.id)
    if continuation == "now":
        assert current_outputs(after)[0]["state"] == "submitted"
        assert workflow.config(auth, inst.id)["next_due"] == due_after_wait
    else:
        assert after["deliverables"] == []
        assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == before
        after, due = tick(workflow, auth, inst.id)
        assert due != scheduled_due
        assert current_outputs(after)[0]["state"] == "submitted"
        workflow.advance(auth, inst.id, due)
    assert len(after["runs"]) == 1  # Resume the dependent job, do not plan or purchase again.
    cost = after["runs"][0]["inference_cost_micro_usd"]
    balance = payments.dashboard(auth, inst.id)["balance_micro_usd"]
    payments.checkout(auth, order_id, "complete")
    workflow.payment_completed(auth, order_id)
    repeated = workflow.overview(auth, inst.id)
    assert len(repeated["deliverables"]) == len(repeated["runs"]) == len(repeated["purchases"]) == 1
    assert repeated["runs"][0]["inference_cost_micro_usd"] == cost
    assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == balance
    policy = payments.dashboard(auth, inst.id)["policy"]
    assert policy["spent_minor"] == 100 and policy["held_minor"] == 0


def test_cancelled_or_unknown_payment_cannot_resume_and_recovery_reuses_identity(build_env):
    env, workflow, _, auth, inst, _ = prepared(build_env, spec("cancel", purchase=True), spec("recover", purchase=True))
    port = PaymentPort(env.db)
    payments = MockCommerceService(env.db, env.clock, payments=port)
    workflow = MockWorkflowService(env.db, env.clock, commerce=payments)
    first, _ = tick(workflow, auth, inst.id)
    cancelled, unknown = first["purchases"]
    cancel_order = approved(workflow, payments, auth, cancelled["id"], "now")["order_id"]
    payments.checkout(auth, cancel_order, "cancel")
    workflow.payment_completed(auth, cancel_order)
    assert workflow.overview(auth, inst.id)["deliverables"] == []
    unknown_order = approved(workflow, payments, auth, unknown["id"], "now")["order_id"]
    port.lose_response = True
    with pytest.raises(AiclError):
        payments.checkout(auth, unknown_order, "complete")
    assert payments.order(auth, unknown_order)["payment_phase"] == "unknown"
    workflow.payment_completed(auth, unknown_order)
    assert workflow.overview(auth, inst.id)["deliverables"] == []
    recovered = payments.reconcile_payment(auth, unknown_order)
    workflow.payment_completed(auth, recovered)
    output, = current_outputs(workflow.overview(auth, inst.id))
    assert output["state"] == "submitted"
    balance = payments.dashboard(auth, inst.id)["balance_micro_usd"]
    workflow.payment_completed(auth, payments.reconcile_payment(auth, unknown_order))
    assert len(workflow.overview(auth, inst.id)["deliverables"]) == 1
    assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == balance
    assert [call for call in port.calls if call == (unknown_order, "complete")] == [(unknown_order, "complete")]


def test_expired_proposal_refresh_preserves_cost_and_racing_continuations_claim_once(build_env):
    env, workflow, payments, auth, inst, _ = prepared(build_env, spec(purchase=True))
    first, _ = tick(workflow, auth, inst.id)
    original, = first["purchases"]
    planning_cost = first["runs"][0]["inference_cost_micro_usd"]
    balance = payments.dashboard(auth, inst.id)["balance_micro_usd"]
    env.clock.set(from_iso(original["expires_at"]) + timedelta(seconds=1))
    fresh = workflow.refresh_purchase(auth, original["id"])
    assert fresh["id"] != original["id"] and fresh["quote_digest"] != original["quote_digest"]
    assert workflow.refresh_purchase(auth, original["id"])["id"] == fresh["id"]
    refreshed = workflow.overview(auth, inst.id)
    assert len(refreshed["runs"]) == 1 and len(refreshed["purchases"]) == 2
    assert payments.purchase(auth, original["id"])["state"] == "expired"
    assert refreshed["runs"][0]["inference_cost_micro_usd"] == planning_cost
    assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == balance
    assert payments.dashboard(auth, inst.id)["policy"]["held_minor"] == 100
    error = expect_error("denied", lambda: payments.decide_purchase(
        auth, fresh["id"], "approve", original["quote_digest"]))
    assert error.extra["reason"] == "confirmation_mismatch"
    order_id = approved(workflow, payments, auth, fresh["id"], "now")["order_id"]
    payments.checkout(auth, order_id, "complete")
    due = workflow.config(auth, inst.id)["next_due"]
    barrier = Barrier(2)

    def resume():
        barrier.wait(timeout=5)
        return workflow.payment_completed(auth, order_id)

    def scheduled():
        barrier.wait(timeout=5)
        return workflow.advance(auth, inst.id, due)

    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [workers.submit(resume), workers.submit(scheduled)]
        for call in calls:
            call.result(timeout=10)
    completed = workflow.overview(auth, inst.id)
    assert len(completed["runs"]) == len(completed["deliverables"]) == 1
    assert completed["deliverables"][0]["state"] == "submitted"
    assert completed["runs"][0]["inference_cost_micro_usd"] == planning_cost * 2
    assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == balance - planning_cost
    assert payments.dashboard(auth, inst.id)["policy"]["spent_minor"] == 100


def test_schedule_pause_and_run_now_do_not_bypass_disabled_controls(build_env):
    env, workflow, payments, auth, inst, ops = prepared(build_env, spec(purchase=True))
    due = workflow.config(auth, inst.id)["next_due"]
    workflow.schedule(auth, inst.id, False)
    paused = expect_error("denied", lambda: workflow.advance(auth, inst.id, due))
    assert paused.extra["reason"] == "schedule_paused"
    assert workflow.overview(auth, inst.id)["runs"] == []
    workflow.schedule(auth, inst.id, True)
    first, _ = tick(workflow, auth, inst.id)
    purchase, = first["purchases"]
    order = approved(workflow, payments, auth, purchase["id"], "now")["order_id"]
    payments.checkout(auth, order, "complete")
    ops.set_capability(auth, inst.id, env.instances.get(auth, inst.id).version, "inference", False)
    balance = payments.dashboard(auth, inst.id)["balance_micro_usd"]
    workflow.payment_completed(auth, order)
    blocked = workflow.overview(auth, inst.id)
    assert blocked["deliverables"] == []
    assert "inference" in blocked["runs"][0]["blocked_reason"].lower()
    assert any(event["reason"] == "capability_disabled" for event in blocked["events"])
    assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == balance
    ops.set_capability(auth, inst.id, env.instances.get(auth, inst.id).version, "inference", True)
    workflow.schedule(auth, inst.id, False)
    workflow.payment_completed(auth, order)
    assert workflow.overview(auth, inst.id)["deliverables"] == []
    assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == balance


def test_stale_enable_cannot_undo_schedule_pause_or_separate_owner_control_pause(build_env):
    env, workflow, _, auth, inst, ops = prepared(build_env)
    stale = workflow.config(auth, inst.id)
    workflow.schedule(auth, inst.id, False, expected_version=stale["version"],
                      expected_instance_version=stale["instance_version"])
    paused = workflow.config(auth, inst.id)
    assert not paused["enabled"] and paused["version"] > stale["version"]
    expect_error("conflict", lambda: workflow.schedule(
        auth, inst.id, True, expected_version=stale["version"],
        expected_instance_version=stale["instance_version"]))
    assert not workflow.config(auth, inst.id)["enabled"]

    workflow.schedule(auth, inst.id, True, expected_version=paused["version"],
                      expected_instance_version=paused["instance_version"])
    enabled = workflow.config(auth, inst.id)
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    expect_error("conflict", lambda: workflow.schedule(
        auth, inst.id, True, expected_version=enabled["version"],
        expected_instance_version=enabled["instance_version"]))
    assert env.instances.get(auth, inst.id).lifecycle == "paused"
    # An idempotent repeat with a fresh view also must not change separate controls.
    fresh = workflow.config(auth, inst.id)
    workflow.schedule(auth, inst.id, True, expected_version=fresh["version"],
                      expected_instance_version=fresh["instance_version"])
    assert env.instances.get(auth, inst.id).lifecycle == "paused"
    assert workflow.overview(auth, inst.id)["runs"] == []


@pytest.mark.parametrize("blocked_by", ["credit", "budget"])
def test_scheduled_work_records_credit_or_budget_failure_without_outputs_or_charges(build_env, blocked_by):
    env, workflow, payments, auth, inst, ops = prepared(build_env, funded=blocked_by != "credit")
    if blocked_by == "budget":
        ops.set_limits(auth, inst.id, env.instances.get(auth, inst.id).version,
                       Limits(1, 10_000_000, 1_000_000, 10_000_000))
    before = payments.dashboard(auth, inst.id)["balance_micro_usd"]
    view, due = tick(workflow, auth, inst.id)
    assert view["deliverables"] == [] and view["purchases"] == []
    assert view["occurrence"]["reason"]
    expected_reason = {"credit": "credit_insufficient", "budget": "budget_exhausted"}[blocked_by]
    assert any(event["reason"] == expected_reason for event in view["events"])
    assert payments.dashboard(auth, inst.id)["balance_micro_usd"] == before
    assert workflow.advance(auth, inst.id, due)["occurrence"]["replayed"]
    budget = env.budget.read_budget(inst.id)
    assert budget.windows["inference"]["day"].settled == 0
    assert budget.windows["inference"]["day"].held == 0


def test_owner_isolation_covers_config_schedule_outputs_reviews_and_purchase_preferences(build_env):
    env, workflow, payments, auth, inst, _ = prepared(build_env, spec(), spec("paid", purchase=True))
    view, _ = tick(workflow, auth, inst.id)
    output, = current_outputs(view)
    purchase, = view["purchases"]
    stranger, _ = env.new_instance()
    assert workflow.overview(stranger)["runs"] == []
    assert workflow.overview(stranger)["purchases"] == []
    assert workflow.overview(stranger)["deliverables"] == []
    due = workflow.config(auth, inst.id)["next_due"]
    original = deepcopy(workflow.overview(auth, inst.id))
    for operation in (
        lambda: workflow.config(stranger, inst.id),
        lambda: workflow.save_config(stranger, inst.id, configuration(), 2),
        lambda: workflow.schedule(stranger, inst.id, True),
        lambda: workflow.advance(stranger, inst.id, due),
        lambda: workflow.overview(stranger, inst.id),
        lambda: workflow.deliverable(stranger, output["id"]),
        lambda: workflow.review(stranger, output["id"], "accept", "", 1),
        lambda: workflow.set_continuation(stranger, purchase["id"], "now"),
    ):
        expect_error("not_found", operation)
    assert workflow.overview(auth, inst.id) == original
    assert payments.purchase(auth, purchase["id"])["state"] == "awaiting_approval"

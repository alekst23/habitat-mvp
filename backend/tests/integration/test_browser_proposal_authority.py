"""Owner changes during inference cannot turn stale observations into approval requests."""
from dataclasses import replace
from datetime import timedelta

import pytest

from aicl.db import to_iso
from aicl.browser.proposals import BrowserPurchaseProposalService
from aicl.control.errors import AiclError
from aicl.render.service import MAX_COMPUTE_MINUTES
from test_browser_flow_recovery import claimed_after_login
from test_browser_scheduled_flow import run_due
from test_workflow_inference import rows


@pytest.mark.parametrize("change", ["revoked", "expired", "schedule_paused", "agent_paused", "hold_released", "compute_expired"])
def test_proposal_checks_current_authority_after_billed_inference(build_env, base_env, change):
    flow, login, opened, dispatch, attempt = claimed_after_login(build_env, base_env)
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = flow
    assert execution.browser_prepare(dispatch["id"], "read-task", attempt["id"]) == {"state": "ready"}
    result = execution.generate(dispatch["id"], "read-task", attempt["id"])
    assert result["state"] == "generated" and len(adapter.calls) == 1
    if change == "revoked":
        broker.revoke(auth, opened["id"])
    elif change == "expired":
        with env.db.transaction() as conn:
            conn.execute("UPDATE browser_session SET credential_expires_at=? WHERE id=?",
                         (to_iso(env.clock.now() - timedelta(seconds=1)), opened["id"]))
    elif change == "schedule_paused":
        wf.schedule(auth, inst.id, False)
    elif change == "agent_paused":
        with env.db.transaction() as conn:
            conn.execute("UPDATE agent_instance SET lifecycle='paused' WHERE id=?", (inst.id,))
    elif change == "hold_released":
        with env.db.transaction() as conn:
            conn.execute("UPDATE budget_hold SET state='released' WHERE id=(SELECT hold_id FROM render_dispatch WHERE id=?)", (dispatch["id"],))
    else:
        env.clock.advance(timedelta(minutes=MAX_COMPUTE_MINUTES))
    execution.complete_attempt(dispatch["id"], "read-task", attempt["id"], {"passed": True})
    # Charge accounting remains true even though authority to request a purchase
    # was removed while the actual provider call was outside the transaction.
    assert rows(env, "workflow_inference_attempt")[0]["state"] == "settled"
    assert len([row for row in rows(env, "mock_commerce_ledger") if row["kind"] == "inference_usage"]) == 1
    assert not rows(env, "browser_purchase_proposal") and not rows(env, "mock_commerce_purchase")


@pytest.mark.parametrize("tamper", ["fabricated_excerpt", "over_scope_amount"])
def test_cached_provider_result_cannot_invent_evidence_or_exceed_owner_proposal_scope(build_env, base_env, tamper):
    flow, login, opened, dispatch, attempt = claimed_after_login(build_env, base_env)
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = flow
    assert execution.browser_prepare(dispatch["id"], "read-task", attempt["id"]) == {"state": "ready"}
    generate = adapter.generate

    def invalid(snapshot, spec, feedback=""):
        original = generate(snapshot, spec, feedback)
        changes = {"evidence_excerpt": "A made-up discounted campaign price"} if tamper == "fabricated_excerpt" else {
            "amount_minor": snapshot["browser_task"]["max_amount_minor"] + 1}
        return replace(original, browser_review={**original.browser_review, **changes})

    adapter.generate = invalid
    execution.generate(dispatch["id"], "read-task", attempt["id"])
    execution.complete_attempt(dispatch["id"], "read-task", attempt["id"], {"passed": True})
    assert not rows(env, "browser_purchase_proposal") and not rows(env, "mock_commerce_purchase")
    assert rows(env, "workflow_inference_attempt")[0]["validation_error"] == "browser_review_invalid"
    assert rows(env, "mock_workflow_deliverable")[0]["state"] == "needs_work"


def test_owner_review_revision_reuses_login_and_creates_new_version_bound_proposal(build_env, base_env):
    flow, login, opened, dispatch, attempt = claimed_after_login(build_env, base_env)
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = flow
    execution.browser_prepare(dispatch["id"], "read-task", attempt["id"])
    execution.generate(dispatch["id"], "read-task", attempt["id"])
    execution.complete_attempt(dispatch["id"], "read-task", attempt["id"], {"passed": True})
    execution.finish(dispatch["id"], "read-task")
    original, = rows(env, "browser_purchase_proposal")
    original_output, = rows(env, "mock_workflow_deliverable")
    wf.review(auth, original_output["id"], "request_changes", "Reduce the proposed budget to $10.", 1)
    proposals = BrowserPurchaseProposalService(wf)
    assert proposals.get(auth, original["id"])["state"] == "superseded"
    with pytest.raises(AiclError):
        proposals.decide(auth, original["id"], "approve", 1)
    generate = adapter.generate

    def revise(snapshot, spec, feedback=""):
        assert feedback == "Reduce the proposed budget to $10."
        original_result = generate(snapshot, spec, feedback)
        return replace(original_result, browser_review={**original_result.browser_review, "amount_minor": 1000})

    adapter.generate = revise
    assert run_due(env, wf, auth, inst, execution, "revision-task")["state"] == "completed"
    versions = rows(env, "mock_workflow_deliverable")
    assert len(versions) == 2 and len(adapter.calls) == 2
    revised = next(item for item in rows(env, "browser_purchase_proposal") if item["id"] != original["id"])
    assert revised["amount_minor"] == 1000 and revised["workflow_run_id"] == original["workflow_run_id"]
    assert revised["deliverable_id"] == next(output["id"] for output in versions if output["version"] == 2)
    assert len(rows(env, "owner_request")) == 1  # Saved access survives into the next scheduled job.
    assert len([item for item in runtime.creates if item["mode"] == "worker"]) == 2
    assert not rows(env, "mock_commerce_purchase")
    proposals.decide(auth, revised["id"], "approve", 1)
    with pytest.raises(AiclError) as rejected:
        wf.review(auth, revised["deliverable_id"], "request_changes", "Change the already approved scope.", 2)
    assert rejected.value.error == "invalid_transition"
    assert wf.deliverable(auth, revised["deliverable_id"])["state"] == "submitted"
    assert proposals.get(auth, revised["id"])["state"] == "approved"

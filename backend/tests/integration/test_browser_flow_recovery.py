"""Recovery must refresh evidence under the current grant without checkout."""
from datetime import timedelta
import json

import pytest

from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso
from aicl.workflow.openai_inference import InferenceResult
from render_worker.runner import execute
from test_browser_scheduled_flow import LocalWorker, browser_flow, run_due
from test_workflow_inference import rows


def claimed_after_login(build_env, base_env):
    flow = browser_flow(build_env, base_env)
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = flow
    run_due(env, wf, auth, inst, execution, "first-task")
    login, = rows(env, "owner_request")
    opened = broker.start(auth, login["id"], 1)
    broker.complete(auth, login["id"], 1, "now")
    dispatch, = execution.dispatch()["dispatches"]
    execution.submitted(dispatch["id"], "read-task")
    attempt, = execution.claim(dispatch["id"], "read-task")["attempts"]
    return flow, login, opened, dispatch, attempt


@pytest.mark.parametrize("loss", ["revoked", "expired"])
def test_reauthentication_replaces_pending_attempt_evidence_instead_of_reusing_old_grant(build_env, base_env, loss):
    flow, login, opened, dispatch, attempt = claimed_after_login(build_env, base_env)
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = flow
    assert execution.browser_prepare(dispatch["id"], "read-task", attempt["id"]) == {"state": "ready"}
    if loss == "revoked":
        broker.revoke(auth, opened["id"])
    else:
        with env.db.transaction() as conn:
            conn.execute("UPDATE browser_session SET credential_expires_at=? WHERE id=?",
                         (to_iso(env.clock.now() - timedelta(seconds=1)), opened["id"]))
    waiting = execution.browser_prepare(dispatch["id"], "read-task", attempt["id"])
    assert waiting["state"] == "waiting_owner" and waiting["request_id"] != login["id"]
    assert execution.finish(dispatch["id"], "read-task")["state"] == "attention"

    new_login = waiting["request_id"]
    broker.start(auth, new_login, 1)
    broker.complete(auth, new_login, 1, "now")
    replacement, = execution.dispatch()["dispatches"]
    execution.submitted(replacement["id"], "fresh-read-task")
    resumed, = execution.claim(replacement["id"], "fresh-read-task")["attempts"]
    assert resumed["id"] == attempt["id"]
    runtime.page = lambda _: {"url": "https://ads.example.com/account", "title": "Updated account",
                             "text": "Account: Orbit Studio. Fresh account settings after sign-in."}
    assert execution.browser_prepare(replacement["id"], "fresh-read-task", resumed["id"]) == {"state": "ready"}
    evidence, = rows(env, "browser_attempt_evidence")
    assert evidence["request_id"] == new_login
    assert json.loads(evidence["evidence_json"])["text"].endswith("Fresh account settings after sign-in.")
    assert len([create for create in runtime.creates if create["mode"] == "worker"]) == 2
    assert not adapter.calls and not rows(env, "mock_commerce_purchase") and not rows(env, "browser_purchase_proposal")


def test_browser_outage_retries_same_attempt_on_next_schedule_without_another_login(build_env, base_env):
    flow, login, opened, dispatch, attempt = claimed_after_login(build_env, base_env)
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = flow
    page = runtime.page

    def unavailable(_):
        raise AiclError("unavailable", "The website could not be read")

    runtime.page = unavailable
    assert execution.browser_prepare(dispatch["id"], "read-task", attempt["id"]) == {"state": "blocked"}
    assert execution.finish(dispatch["id"], "read-task")["state"] == "attention"
    assert len(rows(env, "owner_request")) == 1 and not rows(env, "browser_attempt_evidence")
    runtime.page = page
    env.clock.set(from_iso(wf.config(auth, inst.id)["next_due"]))
    retry, = execution.dispatch()["dispatches"]
    execution.submitted(retry["id"], "retry-task")
    resumed, = execution.claim(retry["id"], "retry-task")["attempts"]
    assert resumed["id"] == attempt["id"]
    assert execution.browser_prepare(retry["id"], "retry-task", resumed["id"]) == {"state": "ready"}
    assert len(rows(env, "owner_request")) == 1 and not adapter.calls
    assert not rows(env, "mock_commerce_purchase") and not rows(env, "browser_purchase_proposal")


def test_revoked_access_cannot_generate_using_already_observed_evidence(build_env, base_env):
    flow, login, opened, dispatch, attempt = claimed_after_login(build_env, base_env)
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = flow
    assert execution.browser_prepare(dispatch["id"], "read-task", attempt["id"]) == {"state": "ready"}
    broker.revoke(auth, opened["id"])
    with pytest.raises(AiclError):
        execution.generate(dispatch["id"], "read-task", attempt["id"])
    assert not adapter.calls and not rows(env, "mock_commerce_purchase") and not rows(env, "browser_purchase_proposal")


def test_schedule_pause_during_browser_read_discards_evidence_and_prevents_generation(build_env, base_env):
    flow, login, opened, dispatch, attempt = claimed_after_login(build_env, base_env)
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = flow
    page = runtime.page

    def pause(_):
        wf.schedule(auth, inst.id, False)
        return page(_)

    runtime.page = pause
    with pytest.raises(AiclError):
        execution.browser_prepare(dispatch["id"], "read-task", attempt["id"])
    assert not rows(env, "browser_attempt_evidence") and not adapter.calls
    assert not rows(env, "mock_commerce_purchase") and not rows(env, "browser_purchase_proposal")


def test_full_length_configured_objective_can_request_signin(build_env, base_env):
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = browser_flow(build_env, base_env)
    wf.schedule(auth, inst.id, False)
    config = wf.config(auth, inst.id)
    config["browser_task"]["objective"] = "Review audience fit and a bounded advertising test. " * 35
    wf.save_config(auth, inst.id, config, config["version"])
    wf.schedule(auth, inst.id, True)
    assert run_due(env, wf, auth, inst, execution, "long-objective")["state"] == "attention"
    login, = rows(env, "owner_request")
    assert login["kind"] == "authentication" and login["status"] == "pending"
    assert len(json.loads(login["details_json"])["requested_access"]) <= 500
    assert not adapter.calls


@pytest.mark.parametrize("access_status", ["login_required", "uncertain"])
def test_model_access_gap_settles_once_and_resumes_new_attempt_after_owner_response(build_env, base_env, access_status):
    flow, login, opened, dispatch, attempt = claimed_after_login(build_env, base_env)
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = flow
    original_generate = adapter.generate

    def needs_owner(snapshot, spec, feedback=""):
        adapter.calls.append(snapshot)
        return InferenceResult("The observed page does not establish usable account access.",
            [{"criterion": c, "passed": False, "reason": "Account access still needs review."} for c in spec["criteria"]],
            100, 100, "resp_needs_owner", "gpt-6-sol", browser_review={
                "access_status": access_status, "access_evidence": "", "amount_minor": 0,
                "description": "", "rationale": "", "evidence_excerpt": ""})

    adapter.generate = needs_owner
    assert execute(LocalWorker(execution), dispatch["id"], "read-task")["state"] == "attention"
    assert len(adapter.calls) == 1 and not rows(env, "mock_workflow_deliverable")
    assert not rows(env, "browser_purchase_proposal") and not rows(env, "mock_commerce_purchase")
    saved_attempt, = rows(env, "workflow_inference_attempt")
    assert saved_attempt["state"] == "settled" and saved_attempt["validation_error"] == "owner_request"
    pending, = [r for r in rows(env, "owner_request") if r["status"] == "pending"]
    if access_status == "login_required":
        assert pending["kind"] == "authentication"
        broker.start(auth, pending["id"], 1)
        broker.complete(auth, pending["id"], 1, "now")
    else:
        assert pending["kind"] == "clarification"
        requests.respond(auth, pending["id"], 1, answer="Use the Orbit Studio advertising account.", continuation="now")
    adapter.generate = original_generate
    resumed, = execution.dispatch()["dispatches"]
    execution.submitted(resumed["id"], "owner-response-task")
    assert execute(LocalWorker(execution), resumed["id"], "owner-response-task")["state"] == "completed"
    attempts = rows(env, "workflow_inference_attempt")
    assert len(attempts) == 2 and [a["version"] for a in attempts] == [1, 2]
    assert all(a["state"] == "settled" for a in attempts)
    assert len(adapter.calls) == 2 and len(rows(env, "browser_purchase_proposal")) == 1
    assert not rows(env, "mock_commerce_purchase")


def test_next_scheduled_job_reuses_saved_session_after_owner_reviews_prior_output(build_env, base_env):
    flow, login, opened, dispatch, attempt = claimed_after_login(build_env, base_env)
    env, wf, commerce, auth, inst, requests, broker, runtime, execution, adapter = flow
    before_orders = len(rows(env, "mock_commerce_order"))
    assert execute(LocalWorker(execution), dispatch["id"], "read-task")["state"] == "completed"
    deliverable, = rows(env, "mock_workflow_deliverable")
    wf.review(auth, deliverable["id"], "accept", "", deliverable["version"])
    assert run_due(env, wf, auth, inst, execution, "next-scheduled-job")["state"] == "completed"
    assert len(rows(env, "owner_request")) == 1
    assert len(rows(env, "mock_workflow_run")) == 2 and len(adapter.calls) == 2
    assert len(rows(env, "browser_purchase_proposal")) == 2
    assert len([create for create in runtime.creates if create["mode"] == "owner"]) == 1
    assert len([create for create in runtime.creates if create["mode"] == "worker"]) == 2
    assert len(rows(env, "mock_commerce_order")) == before_orders and not rows(env, "mock_commerce_purchase")

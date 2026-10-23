"""Durable Render execution proofs with real SQLite and no external calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
import httpx
from fastapi.testclient import TestClient

from aicl.control.errors import AiclError
from aicl.db import from_iso
from aicl.render.service import RenderExecution
from aicl.workflow.ad_scenario import pocketplan_preset
from aicl.workflow.openai_inference import InferenceUnknownOutcomeError
from aicl.workflow.service import MockWorkflowService
from render_worker.client import AICLClient, ClientConfig
from render_worker.runner import execute, plan_attempt, validate_output
from test_pocketplan_workflow import campaign, pay
from test_workflow_inference import live, rows


def queued(build_env, **options):
    env, wf, commerce, auth, inst, ops, adapter = live(build_env, **options)
    execution = RenderExecution(wf)
    dispatch, = execution.dispatch()["dispatches"]
    return env, wf, commerce, auth, inst, ops, adapter, execution, dispatch


def claim(execution, dispatch, task_run_id="render-task-1"):
    execution.submitted(dispatch["id"], task_run_id)
    return execution.claim(dispatch["id"], task_run_id)


def complete(execution, dispatch, claimed, task_run_id="render-task-1"):
    """Drive the same stage protocol used by the Render task runner."""
    result = claimed
    for _ in range(12):
        for attempt in result.get("attempts", []):
            generated = execution.generate(dispatch["id"], task_run_id, attempt["id"])
            if generated.get("result") is not None:
                validation = validate_output(generated["result"], plan_attempt(attempt))
                execution.complete_attempt(dispatch["id"], task_run_id, attempt["id"], validation)
        result = execution.finish(dispatch["id"], task_run_id)
        if result["state"] != "running":
            return result
    raise AssertionError("Render job did not reach a terminal/waiting state")


def test_dispatch_uses_real_due_time_without_future_work_or_catchup_storm(build_env):
    env, wf, _, auth, inst, _, adapter = live(build_env)
    wf.schedule(auth, inst.id, False)
    wf.schedule(auth, inst.id, True)
    due = from_iso(wf.config(auth, inst.id)["next_due"])
    execution = RenderExecution(wf)
    env.clock.set(due - timedelta(microseconds=1))
    assert execution.dispatch()["dispatches"] == []
    assert rows(env, "mock_workflow_occurrence") == []
    env.clock.set(due)
    first, = execution.dispatch()["dispatches"]
    assert adapter.calls == []  # The cron dispatcher never performs inference.
    assert from_iso(wf.config(auth, inst.id)["next_due"]) > env.clock.now()
    repeated = RenderExecution(wf).dispatch()["dispatches"]
    assert all(item["id"] == first["id"] for item in repeated)
    assert len(rows(env, "mock_workflow_occurrence")) <= 1


def test_claim_uses_frozen_config_and_cached_response_survives_restart(build_env):
    env, wf, commerce, auth, inst, _, adapter, execution, dispatch = queued(build_env)
    original = wf.config(auth, inst.id)
    updated = pocketplan_preset()
    updated["goal"] = "This changed goal belongs only to later scheduled jobs."
    wf.save_config(auth, inst.id, updated, original["version"])
    claimed = claim(execution, dispatch)
    attempt, = claimed["attempts"]
    assert attempt["snapshot"]["goal"] == original["goal"]
    assert execution.claim(dispatch["id"], "render-task-1")["attempts"] == claimed["attempts"]
    with pytest.raises(AiclError):
        execution.claim(dispatch["id"], "some-other-task")
    generated = execution.generate(dispatch["id"], "render-task-1", attempt["id"])
    assert len(adapter.calls) == 1
    assert wf.overview(auth, inst.id)["purchases"] == []
    assert not any(d["spec_key"] == "campaign_plan" for d in wf.overview(auth, inst.id)["deliverables"])
    restarted = RenderExecution(MockWorkflowService(env.db, env.clock, commerce=commerce, inference=adapter))
    assert restarted.generate(dispatch["id"], "render-task-1", attempt["id"])["result"] == generated["result"]
    outcome = complete(restarted, dispatch, claimed)
    assert outcome["state"] == "completed"
    assert len(adapter.calls) == 1
    view = wf.overview(auth, inst.id)
    assert len(view["purchases"]) == 1
    assert view["purchases"][0]["state"] == "awaiting_approval"
    assert any(d["spec_key"] == "campaign_plan" and d["goal"] == original["goal"] for d in view["deliverables"])
    before = [(r["id"], r["version"]) for r in rows(env, "mock_workflow_deliverable")]
    assert restarted.finish(dispatch["id"], "render-task-1")["state"] == "completed"
    assert [(r["id"], r["version"]) for r in rows(env, "mock_workflow_deliverable")] == before
    assert len(rows(env, "workflow_inference_attempt")) == 1


def test_pause_after_queue_prevents_execution_and_preserves_owner_decision(build_env):
    env, wf, _, auth, inst, ops, adapter, execution, dispatch = queued(build_env)
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    result = claim(execution, dispatch)
    assert result["state"] == "blocked"
    assert adapter.calls == []
    assert not wf.overview(auth, inst.id)["purchases"]
    assert env.instances.get(auth, inst.id).lifecycle == "paused"


def test_pause_after_claim_is_rechecked_before_inference(build_env):
    env, wf, _, auth, inst, ops, adapter, execution, dispatch = queued(build_env)
    claimed = claim(execution, dispatch)
    attempt, = claimed["attempts"]
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    result = execution.generate(dispatch["id"], "render-task-1", attempt["id"])
    assert result["state"] == "blocked"
    assert adapter.calls == []
    assert not wf.overview(auth, inst.id)["purchases"]


def test_unknown_provider_outcome_is_never_resent_or_released_by_retry(build_env):
    env, wf, commerce, auth, inst, _, adapter, execution, dispatch = queued(
        build_env, error=InferenceUnknownOutcomeError("timeout"))
    claimed = claim(execution, dispatch)
    attempt, = claimed["attempts"]
    first = execution.generate(dispatch["id"], "render-task-1", attempt["id"])
    assert first["state"] == "unknown"
    adapter.error = None
    restarted = RenderExecution(MockWorkflowService(env.db, env.clock, commerce=commerce, inference=adapter))
    assert restarted.generate(dispatch["id"], "render-task-1", attempt["id"])["state"] == "unknown"
    assert len(adapter.calls) == 1
    assert not wf.overview(auth, inst.id)["purchases"]
    assert any(h["state"] == "unknown" and h["inference_micro_usd"] > 0 for h in rows(env, "budget_hold"))
    assert not any(u["inference_micro_usd"] for u in rows(env, "budget_usage"))


def test_server_validates_cached_output_and_charges_invalid_model_response(build_env):
    env, wf, _, auth, inst, _, adapter, execution, dispatch = queued(build_env, invalid=True)
    claimed = claim(execution, dispatch)
    attempt, = claimed["attempts"]
    with pytest.raises(AiclError):
        execution.complete_attempt(dispatch["id"], "render-task-1", attempt["id"], {"passed": True})
    execution.generate(dispatch["id"], "render-task-1", attempt["id"])
    # A worker's positive assertion cannot override the cached provider validation failure.
    execution.complete_attempt(dispatch["id"], "render-task-1", attempt["id"], {"passed": True})
    execution.finish(dispatch["id"], "render-task-1")
    view = wf.overview(auth, inst.id)
    assert len(adapter.calls) == 1 and not view["purchases"]
    plan = next(d for d in view["deliverables"] if d["spec_key"] == "campaign_plan")
    assert plan["state"] == "needs_work"
    assert plan["inference"]["validation_error"] == "invalid_output"
    assert sum(u["inference_micro_usd"] for u in rows(env, "budget_usage")) == 700


def test_compute_budget_is_reserved_before_dispatch_and_settled_once(build_env):
    env, wf, _, auth, inst, _, adapter, execution, dispatch = queued(build_env)
    holds = [h for h in rows(env, "budget_hold") if h["compute_micro_usd"] > 0]
    assert len(holds) == 1 and holds[0]["state"] == "held"
    assert holds[0]["est_compute_minutes"] == 6
    assert holds[0]["compute_micro_usd"] == 6 * 6667
    assert adapter.calls == []
    claimed = claim(execution, dispatch)
    complete(execution, dispatch, claimed)
    execution.finish(dispatch["id"], "render-task-1")
    compute = [u for u in rows(env, "budget_usage") if u["compute_micro_usd"] > 0]
    assert len(compute) == 1
    assert 0 < compute[0]["compute_minutes"] <= 6
    assert not any(h["state"] == "held" and h["compute_micro_usd"] for h in rows(env, "budget_hold"))


def test_insufficient_compute_limit_blocks_before_any_remote_queue_or_model_call(build_env):
    env, wf, _, auth, inst, _, adapter = live(build_env)
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET compute_daily_micro_usd=1 WHERE id=?", (inst.id,))
    assert RenderExecution(wf).dispatch()["dispatches"] == []
    assert adapter.calls == []
    assert not rows(env, "workflow_inference_attempt")
    assert not wf.overview(auth, inst.id)["purchases"]


def test_uncertain_submission_reuses_one_key_only_within_render_retention_window(build_env):
    env, wf, _, _, _, _, adapter, execution, dispatch = queued(build_env)
    execution.uncertain(dispatch["id"])
    env.clock.advance(timedelta(minutes=1))
    assert RenderExecution(wf).dispatch()["dispatches"] == [dispatch]
    env.clock.advance(timedelta(hours=23))
    assert RenderExecution(wf).dispatch()["dispatches"] == []
    assert adapter.calls == []
    hold, = [h for h in rows(env, "budget_hold") if h["compute_micro_usd"] > 0]
    assert hold["state"] == "unknown"
    from aicl.work.gate import SqliteHoldReconciler
    class NoFakeLookup:
        def lookup(self, hold_id):
            raise AssertionError("Real Render holds must never be released by the fixture executor")
    SqliteHoldReconciler(env.db, env.clock, env.budget, NoFakeLookup()).run_once()
    assert next(h for h in rows(env, "budget_hold") if h["id"] == hold["id"])["state"] == "unknown"


def test_job_and_attempt_identity_prevent_cross_task_completion(build_env):
    _, _, _, _, _, _, adapter, execution, dispatch = queued(build_env)
    attempt, = claim(execution, dispatch)["attempts"]
    for operation in (
        lambda: execution.generate(dispatch["id"], "unbound-task", attempt["id"]),
        lambda: execution.generate(dispatch["id"], "render-task-1", "another-attempt"),
        lambda: execution.complete_attempt(dispatch["id"], "unbound-task", attempt["id"], {"passed": True}),
        lambda: execution.finish(dispatch["id"], "unbound-task"),
    ):
        with pytest.raises(AiclError):
            operation()
    assert adapter.calls == []


def test_concurrent_finish_cannot_strand_a_known_provider_result(build_env):
    env, wf, _, auth, inst, _, adapter, execution, dispatch = queued(build_env)
    claimed = claim(execution, dispatch)
    attempt, = claimed["attempts"]
    entered, release = Event(), Event()
    original_generate = adapter.generate

    def delayed(snapshot, spec, feedback):
        entered.set()
        assert release.wait(5)
        return original_generate(snapshot, spec, feedback)

    adapter.generate = delayed
    with ThreadPoolExecutor(max_workers=1) as pool:
        provider = pool.submit(execution.generate, dispatch["id"], "render-task-1", attempt["id"])
        try:
            assert entered.wait(5)
            assert execution.generate(dispatch["id"], "render-task-1", attempt["id"])["state"] == "inflight"
            # A retry cannot finish the runtime and make the original reply impossible to settle.
            with pytest.raises(AiclError):
                execution.finish(dispatch["id"], "render-task-1")
        finally:
            release.set()
        assert provider.result(timeout=5)["result"] is not None
    assert complete(execution, dispatch, claimed)["state"] == "completed"
    assert len(adapter.calls) == 1
    assert sum(u["inference_micro_usd"] for u in rows(env, "budget_usage")) == 700
    assert len(wf.overview(auth, inst.id)["purchases"]) == 1


def test_purchase_wait_exits_task_and_paid_continuation_survives_restart(build_env):
    env, wf, commerce, auth, inst, _, adapter, execution, dispatch = queued(build_env)
    assert complete(execution, dispatch, claim(execution, dispatch))["state"] == "completed"
    before_payment = wf.overview(auth, inst.id)
    request, = before_payment["purchases"]
    assert request["state"] == "awaiting_approval"
    assert campaign(before_payment)["state"] == "awaiting_approval"
    assert not any(h["state"] == "held" for h in rows(env, "budget_hold"))
    restarted = MockWorkflowService(env.db, env.clock, commerce=commerce, inference=adapter, execution_mode="render")
    order_id = pay(restarted, commerce, auth, request["id"], continuation="now")
    restarted.payment_completed(auth, order_id)
    assert campaign(restarted.overview(auth, inst.id))["state"] == "funded"
    assert len(rows(env, "render_dispatch")) == 2
    continued = RenderExecution(restarted)
    next_dispatch, = continued.dispatch()["dispatches"]
    assert next_dispatch["id"] != dispatch["id"]
    task_id = "render-task-continuation"
    result = complete(continued, next_dispatch, claim(continued, next_dispatch, task_id), task_id)
    assert result["state"] == "completed"
    assert campaign(restarted.overview(auth, inst.id))["state"] == "active"
    assert campaign(restarted.overview(auth, inst.id))["metrics"] == []
    assert len(adapter.calls) == 1  # Authorizing delivery does not regenerate paid model output.
    restarted.payment_completed(auth, order_id)
    assert len(rows(env, "render_dispatch")) == 2


def test_paid_continuation_waits_for_the_agents_existing_task_before_dispatch(build_env):
    env, wf, commerce, auth, inst, _, adapter, execution, dispatch = queued(build_env)
    complete(execution, dispatch, claim(execution, dispatch))
    purchase, = wf.overview(auth, inst.id)["purchases"]
    # The next occurrence is executing when the owner pays an earlier proposal.
    env.clock.set(from_iso(wf.config(auth, inst.id)["next_due"]))
    scheduled, = execution.dispatch()["dispatches"]
    current = claim(execution, scheduled, "render-task-next-day")
    assert current["state"] == "running"
    owner_workflow = MockWorkflowService(env.db, env.clock, commerce=commerce, inference=adapter, execution_mode="render")
    purchase = owner_workflow.refresh_purchase(auth, purchase["id"])
    pay(owner_workflow, commerce, auth, purchase["id"], continuation="now")
    assert execution.dispatch()["dispatches"] == []
    assert complete(execution, scheduled, current, "render-task-next-day")["state"] == "completed"
    next_dispatch, = execution.dispatch()["dispatches"]
    assert next_dispatch["id"] not in {dispatch["id"], scheduled["id"]}


def test_owner_can_explicitly_retry_a_continuation_blocked_by_pause(build_env):
    env, wf, commerce, auth, inst, ops, adapter, execution, dispatch = queued(build_env)
    complete(execution, dispatch, claim(execution, dispatch))
    purchase, = wf.overview(auth, inst.id)["purchases"]
    owner_workflow = MockWorkflowService(env.db, env.clock, commerce=commerce, inference=adapter, execution_mode="render")
    order_id = pay(owner_workflow, commerce, auth, purchase["id"], continuation="now")
    continuation, = execution.dispatch()["dispatches"]
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    assert claim(execution, continuation, "blocked-continuation")["state"] == "blocked"
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "resume")
    owner_workflow.payment_completed(auth, order_id)
    assert execution.dispatch()["dispatches"] == []  # A callback replay is not a new owner decision.
    owner_workflow.set_continuation(auth, purchase["id"], "now")
    retry, = execution.dispatch()["dispatches"]
    assert retry["id"] not in {dispatch["id"], continuation["id"]}
    assert complete(execution, retry, claim(execution, retry, "resumed-continuation"), "resumed-continuation")["state"] == "completed"
    assert campaign(owner_workflow.overview(auth, inst.id))["state"] == "active"


def test_denied_due_agent_does_not_starve_a_later_eligible_agent(build_env):
    from test_pocketplan_workflow import prepared

    env, wf, _, _, first, _, adapter = live(build_env)
    _, _, _, second_auth, second, _ = prepared(lambda: env)
    env.clock.set(from_iso(wf.config(second_auth, second.id)["next_due"]))
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET compute_daily_micro_usd=1 WHERE id=?", (first.id,))
    execution = RenderExecution(wf)
    assert execution.dispatch(limit=1)["dispatches"] == []
    eligible, = execution.dispatch(limit=1)["dispatches"]
    row, = [r for r in rows(env, "render_dispatch") if r["id"] == eligible["id"]]
    assert row["instance_id"] == second.id
    assert adapter.calls == []


def test_machine_api_separates_roles_and_cannot_authorize_payments(build_env, base_env, monkeypatch):
    import aicl.app as application
    import aicl.render.routes as routes
    from aicl.settings import Settings

    _, wf, _, _, _, _, adapter = live(build_env)
    scheduler_secret, worker_secret = "scheduler-private-test-token-12345", "worker-private-test-token-12345678"
    settings = Settings.from_env({
        **base_env,
        "AICL_ENVIRONMENT": "production",
        "AICL_PUBLIC_BASE_URL": "https://habitat.example",
        "AICL_HOSTED_WORKFLOW": "1",
        "AICL_WORKFLOW_EXECUTION_MODE": "render",
        "AICL_INFERENCE_MODE": "openai",
        "OPENAI_API_KEY": "sk-unused-test-provider-key",
        "AICL_SMTP_FROM": "habitat@example.test",
        "AICL_SCHEDULER_TOKEN": scheduler_secret,
        "AICL_WORKER_TOKEN": worker_secret,
    })
    monkeypatch.setattr(routes, "workflow_service", lambda ctx: wf)
    monkeypatch.setattr(application, "STARTUP_HOOKS", ())
    scheduler = {"authorization": "Bearer " + scheduler_secret}
    worker = {"authorization": "Bearer " + worker_secret}
    with TestClient(application.create_app(settings)) as client:
        assert client.post("/internal/render/dispatch").status_code == 401
        assert client.post("/internal/render/dispatch", headers=worker).status_code == 401
        dispatched = client.post("/internal/render/dispatch", headers=scheduler)
        assert dispatched.status_code == 200
        dispatch, = dispatched.json()["dispatches"]
        path = "/internal/render/jobs/" + dispatch["id"]
        task = {"task_run_id": "render-task-http"}
        assert client.post(path + "/claim", json=task, headers=scheduler).status_code == 401
        assert client.post("/internal/render/dispatch/" + dispatch["id"] + "/submitted", json=task, headers=worker).status_code == 401
        assert client.post(path + "/claim", json={**task, "owner_id": "other-owner"}, headers=worker).status_code == 422
        response = client.post(path + "/claim", json=task, headers=worker)
        assert response.status_code == 200
        attempt, = response.json()["attempts"]
        completion = {**task, "attempt_id": attempt["id"], "validation": {"passed": True}}
        assert client.post(path + "/complete-attempt", headers=worker,
                           json={**completion, "result": {"content": "forged provider output"}}).status_code == 422
        assert client.post(path + "/generate", headers=worker,
                           json={**task, "attempt_id": "another-job-attempt"}).status_code == 404
        assert client.post("/internal/render/purchases/any/approve", headers=worker).status_code == 404
        # A valid machine token never becomes an owner browser session or CSRF grant.
        for headers in (scheduler, worker):
            assert client.post("/commerce/purchases/any/decision", headers=headers,
                               data={"decision": "approve"}).status_code == 401
            assert client.post("/commerce/orders/any/paypal-complete", headers=headers).status_code == 401
        assert adapter.calls == []
        transport = httpx.MockTransport(lambda request: client.request(
            request.method, request.url.path, headers=dict(request.headers), content=request.content))
        with AICLClient(ClientConfig("https://habitat.example", worker_secret), transport=transport) as machine:
            result = execute(machine, dispatch["id"], task["task_run_id"])
            assert result["state"] == "completed"
            assert result["job_ids"] and result["deliverable_ids"]
            assert execute(machine, dispatch["id"], task["task_run_id"]) == result
        assert len(adapter.calls) == 1

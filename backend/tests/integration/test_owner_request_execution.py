"""Owner pauses survive restarts without resending billed provider calls."""
from dataclasses import replace

import pytest

from aicl.control.errors import AiclError
from aicl.owner_requests.service import OwnerRequestService
from aicl.render.service import RenderExecution
from aicl.workflow.openai_inference import InferenceResult
from aicl.workflow.service import MockWorkflowService
from test_workflow_inference import live, rows
from test_render_execution import claim, complete
from test_pocketplan_workflow import tick


QUESTION = {"kind": "clarification", "title": "Choose a campaign audience",
            "reason": "The campaign needs one audience before the plan is written.",
            "question": "Who should this campaign target?", "options": ["Casual players", "Strategy players"]}


def asking(build_env, *, render=False):
    env, wf, commerce, auth, inst, ops, adapter = live(build_env)
    original = adapter.generate
    def generate(snapshot, spec, feedback=""):
        result = original(snapshot, spec, feedback)
        if not snapshot.get("owner_answers"):
            return replace(result, content="", criteria=[], owner_request=QUESTION)
        return result
    adapter.generate = generate
    wf.execution_mode = "render" if render else "local"
    return env, wf, commerce, auth, inst, ops, adapter


def test_model_question_charges_once_and_answer_resumes_same_job(build_env):
    env, wf, commerce, auth, inst, _, adapter = asking(build_env)
    first = tick(wf, auth, inst.id)
    requests = OwnerRequestService(wf)
    request, = requests.list(auth)
    job_id = request["job_id"]
    assert request["kind"] == "clarification" and request["job_state"] == "waiting_owner"
    assert not first["purchases"]
    assert len(adapter.calls) == 1
    assert len(rows(env, "budget_usage")) == 1
    assert not any(d["workflow_run_id"] == job_id for d in rows(env, "mock_workflow_deliverable"))
    restarted = MockWorkflowService(env.db, env.clock, commerce, inference=adapter)
    tick(restarted, auth, inst.id)
    assert len(adapter.calls) == 1 and len(requests.list(auth)) == 1
    requests.respond(auth, request["id"], request["version"], answer="Strategy players", continuation="now")
    assert len(adapter.calls) == 2
    assert adapter.calls[-1][0]["owner_answers"][0]["answer"] == "Strategy players"
    output, = [d for d in rows(env, "mock_workflow_deliverable") if d["workflow_run_id"] == job_id]
    assert output["version"] == 2 and output["state"] == "submitted"
    assert len(rows(env, "budget_usage")) == 2
    with pytest.raises(AiclError):
        requests.respond(auth, request["id"], request["version"], answer="Different answer")
    assert len(adapter.calls) == 2


def test_answer_on_schedule_waits_and_pause_preserves_response(build_env):
    env, wf, _, auth, inst, ops, adapter = asking(build_env)
    tick(wf, auth, inst.id)
    requests = OwnerRequestService(wf)
    request, = requests.list(auth)
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    result = requests.respond(auth, request["id"], 1, answer="Casual players", continuation="now")
    assert result["status"] == "resolved" and result["job_state"] == "waiting_owner"
    assert len(adapter.calls) == 1
    tick(wf, auth, inst.id)
    assert len(adapter.calls) == 1
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "resume")
    tick(wf, auth, inst.id)
    assert len(adapter.calls) == 2
    assert requests.get(auth, request["id"])["job_state"] == "submitted"


def test_schedule_choice_does_not_dispatch_until_next_tick(build_env):
    _, wf, _, auth, inst, _, adapter = asking(build_env)
    tick(wf, auth, inst.id)
    requests = OwnerRequestService(wf)
    request, = requests.list(auth)
    requests.respond(auth, request["id"], 1, answer="Strategy players", continuation="schedule")
    assert len(adapter.calls) == 1
    tick(wf, auth, inst.id)
    assert len(adapter.calls) == 2


def test_render_question_exits_worker_then_queues_fresh_continuation(build_env):
    env, wf, _, auth, inst, _, adapter = asking(build_env, render=True)
    execution = RenderExecution(wf)
    dispatch, = execution.dispatch()["dispatches"]
    claimed = claim(execution, dispatch)
    outcome = complete(execution, dispatch, claimed)
    assert outcome["state"] == "attention"
    assert len(adapter.calls) == 1
    assert not any(h["state"] == "held" for h in rows(env, "budget_hold"))
    requests = OwnerRequestService(wf)
    request, = requests.list(auth)
    requests.respond(auth, request["id"], 1, answer="Strategy players", continuation="now")
    continuation, = execution.dispatch()["dispatches"]
    assert continuation["id"] != dispatch["id"]
    resumed = claim(execution, continuation, "render-resumed")
    result = complete(execution, continuation, resumed, "render-resumed")
    assert result["state"] == "completed"
    assert len(adapter.calls) == 2
    assert request["job_id"] in result["job_ids"]
    assert len(rows(env, "owner_request")) == 1
    assert len(rows(env, "render_compute_usage")) == 2


def test_worker_request_bound_to_claim_and_authentication_cannot_self_attest(build_env):
    env, wf, _, auth, inst, _, adapter = asking(build_env, render=True)
    execution = RenderExecution(wf)
    dispatch, = execution.dispatch()["dispatches"]
    claimed = claim(execution, dispatch)
    attempt, = claimed["attempts"]
    job_id = attempt["workflow_run_id"]
    args = ("authentication", "Sign in to the advertising service", "Prepare a campaign draft", {"domain": "ads.snapchat.com"}, "login-campaign")
    with pytest.raises(AiclError):
        execution.request_owner(dispatch["id"], "unbound-task", job_id, *args)
    with pytest.raises(AiclError):
        execution.request_owner(dispatch["id"], "render-task-1", "not-this-job", *args)
    request = execution.request_owner(dispatch["id"], "render-task-1", job_id, *args)["request"]
    assert execution.request_owner(dispatch["id"], "render-task-1", job_id, *args)["request"]["id"] == request["id"]
    assert execution.finish(dispatch["id"], "render-task-1")["state"] == "attention"
    assert adapter.calls == []
    with pytest.raises(AiclError) as error:
        OwnerRequestService(wf).respond(auth, request["id"], 1, decision="approve")
    assert error.value.error == "unavailable"
    assert OwnerRequestService(wf).get(auth, request["id"])["status"] == "pending"


def test_declining_worker_auth_request_never_releases_pending_inference(build_env):
    env, wf, _, auth, inst, _, adapter = asking(build_env, render=True)
    execution = RenderExecution(wf)
    dispatch, = execution.dispatch()["dispatches"]
    claimed = claim(execution, dispatch)
    attempt, = claimed["attempts"]
    request = execution.request_owner(dispatch["id"], "render-task-1", attempt["workflow_run_id"],
        "authentication", "Sign in", "Prepare a campaign draft", {"domain": "ads.snapchat.com"}, "login")["request"]
    OwnerRequestService(wf).respond(auth, request["id"], 1, decision="decline")
    assert execution.generate(dispatch["id"], "render-task-1", attempt["id"])["result"] is None
    assert execution.finish(dispatch["id"], "render-task-1")["attempts"] == []
    wf.inference.drain(auth, inst.id)
    assert adapter.calls == []
    assert OwnerRequestService(wf).get(auth, request["id"])["job_state"] == "owner_declined"


def test_structured_adapter_accepts_only_clarification_and_carries_answers():
    import json
    from test_openai_inference_adapter import adapter_for, response_body, SNAPSHOT, SPEC
    body = response_body()
    block = body["output"][0]["content"][0]
    block["text"] = json.dumps({"content": "", "criteria": [], "owner_request": QUESTION})
    adapter, calls = adapter_for(body)
    answers = [{"question": "Target region?", "answer": "Canada"}]
    result = adapter.generate(SNAPSHOT | {"owner_answers": answers}, SPEC)
    assert result.owner_request == QUESTION and result.validation_error is None
    payload = json.loads(json.loads(calls[0].content)["input"][0]["content"])
    assert payload["owner_answers"] == answers
    block["text"] = json.dumps({"content": "", "criteria": [], "owner_request": QUESTION | {"kind": "authentication"}})
    adapter, _ = adapter_for(body)
    rejected = adapter.generate(SNAPSHOT, SPEC)
    assert rejected.owner_request is None and rejected.validation_error == "owner_request_invalid"
    assert rejected.input_tokens == 400  # Invalid output still records actual usage.


@pytest.mark.parametrize("failure", ["blocked", "released", "unknown"])
def test_answered_question_preserves_resumed_attempt_version_after_failure(build_env, failure):
    from aicl.workflow.openai_inference import InferenceNoChargeError, InferenceUnknownOutcomeError
    env, wf, _, auth, inst, _, adapter = asking(build_env)
    tick(wf, auth, inst.id)
    requests = OwnerRequestService(wf)
    request, = requests.list(auth)
    if failure == "blocked":
        wf.inference.cap = 1
    else:
        adapter.error = (InferenceNoChargeError("provider_rejected") if failure == "released"
                         else InferenceUnknownOutcomeError("timeout"))
    requests.respond(auth, request["id"], 1, answer="Strategy players", continuation="now")
    attempts = rows(env, "workflow_inference_attempt")
    assert [(a["version"], a["state"]) for a in attempts] == [(1, "settled"), (2, failure)]
    calls_before = len(adapter.calls)
    wf.inference.cap = 1_000_000
    adapter.error = None
    tick(wf, auth, inst.id)
    if failure == "unknown":
        assert len(adapter.calls) == calls_before
        assert rows(env, "workflow_inference_attempt")[-1]["state"] == "unknown"
        assert len(rows(env, "budget_usage")) == 1
    else:
        assert len(adapter.calls) == calls_before + 1
        assert rows(env, "workflow_inference_attempt")[-1]["version"] == 2
        assert rows(env, "workflow_inference_attempt")[-1]["state"] == "settled"
        output, = [d for d in rows(env, "mock_workflow_deliverable") if d["workflow_run_id"] == request["job_id"]]
        assert output["version"] == 2 and output["state"] == "submitted"
        assert len(rows(env, "budget_usage")) == 2
    assert len(rows(env, "owner_request")) == 1


def test_repeated_model_questions_have_a_bounded_attempt_budget(build_env):
    env, wf, _, auth, inst, _, adapter = asking(build_env)
    generate = adapter.generate
    def repeat(snapshot, spec, feedback=""):
        return replace(generate(snapshot, spec, feedback), content="", criteria=[], owner_request=QUESTION)
    adapter.generate = repeat
    tick(wf, auth, inst.id)
    requests = OwnerRequestService(wf)
    for _ in range(12):
        request, = requests.list(auth, kind="clarification")
        requests.respond(auth, request["id"], 1, answer="Strategy players", continuation="now")
    assert len(adapter.calls) == 12
    assert len(rows(env, "budget_usage")) == 12
    assert len(rows(env, "owner_request")) == 12
    job = requests.get(auth, request["id"])
    assert job["job_state"] == "waiting_owner"
    tick(wf, auth, inst.id)
    assert len(adapter.calls) == 12

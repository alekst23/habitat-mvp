"""General agents execute saved work without inheriting the marketing fixture."""
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from aicl.control.errors import AiclError
from aicl.db import from_iso
from aicl.owner_requests.service import OwnerRequestService
from aicl.render.service import RenderExecution
from aicl.workflow.openai_inference import InferenceUnknownOutcomeError, MAX_REQUEST_BYTES, OpenAIInferenceAdapter
from aicl.workflow.service import MockWorkflowService
from test_mock_commerce import ready
from test_openai_inference_adapter import adapter_for, response_body, SPEC
from test_render_execution import claim, complete
from test_workflow_inference import Adapter, rows


def configuration(key="comparison"):
    return {"scenario": "general", "goal": "Compare approaches to insulating an older house",
            "inputs": "For a homeowner. Explain assumptions and practical tradeoffs.",
            "tools": [], "cadence": "daily", "timezone": "America/New_York",
            "deliverables": [{"key": key, "name": "Comparison", "description": "Explain practical implications and evidence gaps.",
                              "criteria": ["Explain practical tradeoffs", "Distinguish evidence from assumptions"]}]}


def prepared(build_env, *, render=False, adapter_enabled=True):
    env, commerce, auth, inst, ops = ready(build_env)
    env.clock.advance(timedelta(days=8))
    adapter = Adapter(env.db) if adapter_enabled else None
    workflow = MockWorkflowService(env.db, env.clock, commerce=commerce, inference=adapter,
                                   execution_mode="render" if render else "local")
    workflow.save_config(auth, inst.id, configuration(), 1)
    if adapter_enabled:
        workflow.schedule(auth, inst.id, True)
    return env, workflow, commerce, auth, inst, ops, adapter


def tick(workflow, auth, instance_id):
    return workflow.advance(auth, instance_id, workflow.config(auth, instance_id)["next_due"])


def test_adding_output_after_removal_preserves_existing_identifiers(build_env):
    _, workflow, _, auth, inst, _, _ = prepared(build_env)
    config = configuration("d2")
    config["deliverables"].append({**config["deliverables"][0], "key": "", "name": "Adoption checklist"})
    saved = workflow.save_config(auth, inst.id, config, workflow.config(auth, inst.id)["version"])
    assert saved["deliverables"][0]["key"] == "d2"
    assert saved["deliverables"][1]["key"] != "d2"
    assert saved["deliverables"][1]["name"] == "Adoption checklist"


def test_general_agent_generates_recurring_work_with_only_actual_model_charges(build_env):
    env, workflow, commerce, auth, inst, _, adapter = prepared(build_env)
    first = tick(workflow, auth, inst.id)
    output, = first["deliverables"]
    assert output["state"] == "submitted"
    assert output["inference"]["cost_micro_usd"] == 700
    assert all(text not in output["content"] for text in ("PocketPlan", "merchant", "Advertising", "fixture", "Scripted"))
    assert not first["purchases"]
    assert len(rows(env, "budget_usage")) == 1
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 4_999_300
    replay = workflow.advance(auth, inst.id, first["occurrence"]["scheduled_for"])
    assert len(adapter.calls) == 1 and len(replay["deliverables"]) == 1
    second = tick(workflow, auth, inst.id)
    assert len(adapter.calls) == 2 and len(second["deliverables"]) == 2
    assert len(rows(env, "budget_usage")) == 2
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 4_998_600


def test_unmet_general_report_does_not_stall_future_periods_and_can_be_revised_explicitly(build_env):
    env, workflow, _, auth, inst, _, adapter = prepared(build_env)
    original = adapter.generate
    def missing_evidence(snapshot, spec, feedback=""):
        result = original(snapshot, spec, feedback)
        return replace(result, criteria=[{**check, "passed": False, "reason": "No new supporting evidence this period."}
                                        for check in result.criteria])
    adapter.generate = missing_evidence
    periods = []
    for _ in range(7):
        view = tick(workflow, auth, inst.id)
        periods.append(view["occurrence"]["scheduled_for"])
    assert len(adapter.calls) == len(rows(env, "mock_workflow_run")) == 7
    assert [call[0]["scheduled_for"] for call in adapter.calls] == periods
    outputs = rows(env, "mock_workflow_deliverable")
    assert all(output["state"] == "needs_work" and output["version"] == 1 for output in outputs)
    first = outputs[0]
    with pytest.raises(AiclError):
        workflow.review(auth, first["id"], "accept", "", 1)
    requested = workflow.review(auth, first["id"], "request_changes", "Explain the missing evidence and its implications.", 1)
    assert requested["state"] == "changes_requested"
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == 8 and len(rows(env, "mock_workflow_run")) == 7
    assert adapter.calls[-1][0]["scheduled_for"] == periods[0]
    assert adapter.calls[-1][2] == "Explain the missing evidence and its implications."
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == 9 and len(rows(env, "mock_workflow_run")) == 8


def test_general_agent_without_inference_never_falls_back_to_simulated_work(build_env):
    env, workflow, _, auth, inst, _, _ = prepared(build_env, adapter_enabled=False)
    with pytest.raises(AiclError):
        workflow.schedule(auth, inst.id, True)
    assert not rows(env, "mock_workflow_run")
    assert not rows(env, "budget_usage")
    proposal = configuration()
    proposal["deliverables"][0]["purchase_required"] = True
    with pytest.raises(AiclError):
        workflow.save_config(auth, inst.id, proposal, workflow.config(auth, inst.id)["version"])


def test_general_job_questions_and_unknown_outcomes_block_duplicate_recurring_work(build_env):
    env, workflow, _, auth, inst, _, adapter = prepared(build_env)
    original = adapter.generate
    def asking(snapshot, spec, feedback=""):
        result = original(snapshot, spec, feedback)
        if not snapshot.get("owner_answers"):
            return replace(result, content="", criteria=[], owner_request={"kind": "clarification", "title": "Choose depth",
                "reason": "The report needs a technical level.", "question": "How much implementation detail?", "options": ["Detailed", "Concise"]})
        return result
    adapter.generate = asking
    tick(workflow, auth, inst.id)
    request, = OwnerRequestService(workflow).list(auth)
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == len(rows(env, "mock_workflow_run")) == 1
    OwnerRequestService(workflow).respond(auth, request["id"], request["version"], answer="Detailed", continuation="now")
    assert len(adapter.calls) == 2 and len(rows(env, "mock_workflow_run")) == 1
    adapter.generate = original
    adapter.error = InferenceUnknownOutcomeError("timeout")
    tick(workflow, auth, inst.id)
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == 3 and len(rows(env, "mock_workflow_run")) == 2
    assert rows(env, "workflow_inference_attempt")[-1]["state"] == "unknown"


def test_general_render_worker_executes_custom_deliverables_and_replays_safely(build_env):
    env, workflow, _, auth, inst, _, adapter = prepared(build_env, render=True)
    execution = RenderExecution(workflow)
    env.clock.set(max(env.clock.now(), from_iso(workflow.config(auth, inst.id)["next_due"])))
    dispatch, = execution.dispatch()["dispatches"]
    claimed = claim(execution, dispatch)
    assert claimed["attempts"][0]["snapshot"]["scenario"] == "general"
    outcome = complete(execution, dispatch, claimed)
    assert outcome["state"] == "completed" and outcome["deliverable_ids"]
    assert execution.finish(dispatch["id"], "render-task-1")["state"] == "completed"
    assert len(adapter.calls) == 1 and len(rows(env, "budget_usage")) == 2
    assert not workflow.overview(auth, inst.id)["purchases"]


@pytest.mark.parametrize("key", ["comparison", "campaign_plan", "performance_report", "ad_creative"])
def test_general_adapter_uses_custom_brief_even_when_key_matches_marketing_example(key):
    adapter, calls = adapter_for(response_body())
    snapshot = configuration(key)
    spec = {**SPEC, "key": key, "ad_kind": "performance_report", "ad_report": {"clicks": 999}}
    result = adapter.generate(snapshot, spec)
    assert result.validation_error is None
    body = json.loads(calls[0].content)
    payload = json.loads(body["input"][0]["content"])
    assert payload["spec"]["kind"] == key
    assert "merchant_scope" not in payload and "ad_report" not in payload["spec"]
    assert "PocketPlan" not in body["instructions"] and "campaign plan" not in body["instructions"]
    assert "untrusted" in body["instructions"] and "research" in body["instructions"]


def enable_research(env, workflow, auth, instance_id):
    # The explicit web-search price version becomes effective on October 25.
    env.clock.advance(timedelta(days=3))
    config = configuration()
    config["tools"] = ["web_search"]
    workflow.save_config(auth, instance_id, config, workflow.config(auth, instance_id)["version"])


def searched_result(adapter):
    original = adapter.generate
    def generate(snapshot, spec, feedback=""):
        result = original(snapshot, spec, feedback)
        return replace(result, web_search_calls=1, tool_trace=[{"type": "search", "query": snapshot["goal"],
            "sources": [{"url": "https://www.energy.gov/energysaver/insulation", "title": "Insulation"}]}])
    adapter.generate = generate


def test_general_web_tool_is_reserved_metered_and_recorded(build_env):
    env, workflow, commerce, auth, inst, _, adapter = prepared(build_env)
    enable_research(env, workflow, auth, inst.id)
    searched_result(adapter)
    view = tick(workflow, auth, inst.id)
    output, = view["deliverables"]
    assert output["inference"]["web_search_calls"] == 1
    assert output["inference"]["cost_micro_usd"] == 10700
    assert output["inference"]["tool_trace"][0]["sources"][0]["title"] == "Insulation"
    attempt, = rows(env, "workflow_inference_attempt")
    hold, = rows(env, "budget_hold")
    assert attempt["max_cost_micro_usd"] == hold["inference_micro_usd"] == 406000
    assert hold["est_web_search_calls"] == 1
    assert rows(env, "budget_usage")[0]["web_search_calls"] == 1
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 4_989_300
    assert adapter.calls[0][0]["tools"] == ["web_search"]
    assert "research_evidence" not in adapter.calls[0][0]


def test_web_tool_requires_full_budget_and_retains_unknown_hold(build_env):
    env, workflow, commerce, auth, inst, _, adapter = prepared(build_env)
    enable_research(env, workflow, auth, inst.id)
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET inference_daily_micro_usd=100000 WHERE id=?", (inst.id,))
    tick(workflow, auth, inst.id)
    assert not adapter.calls and not rows(env, "budget_hold")
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET inference_daily_micro_usd=1000000 WHERE id=?", (inst.id,))
    adapter.error = InferenceUnknownOutcomeError("timeout")
    tick(workflow, auth, inst.id)
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == 1
    hold, = rows(env, "budget_hold")
    assert hold["state"] == "unknown" and hold["inference_micro_usd"] == 406000
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 4_594_000


def test_tool_removal_prevents_pending_job_from_using_old_permission(build_env):
    env, workflow, _, auth, inst, _, adapter = prepared(build_env, render=True)
    enable_research(env, workflow, auth, inst.id)
    env.clock.set(max(env.clock.now(), from_iso(workflow.config(auth, inst.id)["next_due"])))
    execution = RenderExecution(workflow)
    dispatch, = execution.dispatch()["dispatches"]
    claimed = claim(execution, dispatch)
    workflow.save_config(auth, inst.id, configuration(), workflow.config(auth, inst.id)["version"])
    attempt, = claimed["attempts"]
    execution.generate(dispatch["id"], "render-task-1", attempt["id"])
    assert not adapter.calls
    assert rows(env, "workflow_inference_attempt")[0]["state"] == "blocked"


def test_render_replay_reuses_web_result_without_more_tool_charges(build_env):
    env, workflow, _, auth, inst, _, adapter = prepared(build_env, render=True)
    enable_research(env, workflow, auth, inst.id)
    searched_result(adapter)
    env.clock.set(max(env.clock.now(), from_iso(workflow.config(auth, inst.id)["next_due"])))
    execution = RenderExecution(workflow)
    dispatch, = execution.dispatch()["dispatches"]
    claimed = claim(execution, dispatch)
    attempt, = claimed["attempts"]
    first = execution.generate(dispatch["id"], "render-task-1", attempt["id"])
    assert execution.generate(dispatch["id"], "render-task-1", attempt["id"])["result"] == first["result"]
    complete(execution, dispatch, claimed)
    assert len(adapter.calls) == 1
    assert rows(env, "workflow_inference_attempt")[0]["web_search_calls"] == 1
    assert len([r for r in rows(env, "budget_usage") if r["web_search_calls"]]) == 1


def test_unsupported_tools_and_legacy_sources_cannot_expand_permission(build_env):
    _, workflow, _, auth, inst, _, _ = prepared(build_env)
    for fields in ({"tools": ["shell"]}, {"tools": ["web_search", "web_search"]}, {"research_sources": ["arxiv_ai"]}):
        with pytest.raises(AiclError):
            workflow.save_config(auth, inst.id, configuration() | fields, workflow.config(auth, inst.id)["version"])


def test_oversized_general_configuration_is_rejected_before_saving(build_env):
    _, workflow, _, auth, inst, _, _ = prepared(build_env)
    original = workflow.config(auth, inst.id)
    large = configuration()
    large["goal"], large["inputs"] = "G" * 2000, "I" * 4000
    large["deliverables"][0]["description"] = "D" * 2000
    large["deliverables"][0]["criteria"] = [str(index) + "C" * 490 for index in range(12)]
    with pytest.raises(AiclError) as caught:
        workflow.save_config(auth, inst.id, large, original["version"])
    assert "Shorten" in caught.value.message
    assert workflow.config(auth, inst.id)["version"] == original["version"]


def test_general_request_fits_feedback_and_clarification_without_truncating_owner_data(build_env):
    env, workflow, _, auth, inst, _, adapter = prepared(build_env)
    config = configuration()
    config["inputs"] = "I" * 1000
    workflow.save_config(auth, inst.id, config, workflow.config(auth, inst.id)["version"])
    validator = OpenAIInferenceAdapter("test-private-key")
    original = adapter.generate
    requests = []
    def generate(snapshot, spec, feedback=""):
        body, _ = validator._request(snapshot, spec, feedback)
        requests.append(body)
        result = original(snapshot, spec, feedback)
        if feedback and not snapshot.get("owner_answers"):
            return replace(result, content="", criteria=[], owner_request={"kind": "clarification", "title": "Choose emphasis",
                "reason": "R" * 200, "question": "Q" * 300, "options": []})
        return result
    adapter.generate = generate
    first = tick(workflow, auth, inst.id)
    output, = first["deliverables"]
    workflow.review(auth, output["id"], "request_changes", "F" * 2000, output["version"])
    tick(workflow, auth, inst.id)
    request, = OwnerRequestService(workflow).list(auth)
    OwnerRequestService(workflow).respond(auth, request["id"], request["version"], answer="A" * 2000, continuation="now")
    assert len(requests) == 3 and all(len(body) <= MAX_REQUEST_BYTES for body in requests)
    payload = json.loads(json.loads(requests[-1])["input"][0]["content"])
    assert payload["saved"]["inputs"] == config["inputs"]
    assert payload["revision_feedback"] == "F" * 2000
    assert payload["owner_answers"][0]["answer"] == "A" * 2000
    assert payload["owner_answers"][0]["question"] == "Q" * 300
    assert payload["spec"]["criteria"] == config["deliverables"][0]["criteria"]


def test_context_overflow_parks_job_without_retries_and_new_saved_config_can_run(build_env):
    env, workflow, _, auth, inst, _, adapter = prepared(build_env)
    original = adapter.generate
    def asking(snapshot, spec, feedback=""):
        result = original(snapshot, spec, feedback)
        return replace(result, content="", criteria=[], owner_request={"kind": "clarification", "title": "Choose scope",
            "reason": "The writing needs a scope.", "question": "What should it cover?", "options": []})
    adapter.generate = asking
    tick(workflow, auth, inst.id)
    request, = OwnerRequestService(workflow).list(auth)
    OwnerRequestService(workflow).respond(auth, request["id"], request["version"], answer="界" * 4000, continuation="now")
    job, = rows(env, "mock_workflow_run")
    assert job["state"] == "context_blocked" and "Shorten" in job["blocked_reason"]
    assert len(adapter.calls) == 1 and rows(env, "budget_hold")[-1]["state"] == "released"
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == 1 and len(rows(env, "mock_workflow_run")) == 1
    adapter.generate = original
    workflow.save_config(auth, inst.id, configuration(), workflow.config(auth, inst.id)["version"])
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == 2 and len(rows(env, "mock_workflow_run")) == 2

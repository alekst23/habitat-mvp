"""Paid failures and permission changes keep exact cost and replay boundaries."""
from dataclasses import replace

import pytest

from test_general_workflow import configuration, enable_research, prepared, tick
from test_workflow_inference import rows


def measured_search(adapter, *, calls=1, invalid=False):
    generate = adapter.generate
    def result(snapshot, spec, feedback=""):
        response = generate(snapshot, spec, feedback)
        return replace(response, web_search_calls=calls, validation_error="invalid_output" if invalid else None,
                       tool_trace=[{"type": "search", "queries": ["insulation"], "sources": []}])
    adapter.generate = result


def test_paid_malformed_tool_output_settles_once_and_counts_toward_operator_cap(build_env):
    env, workflow, commerce, auth, inst, _, adapter = prepared(build_env)
    enable_research(env, workflow, auth, inst.id)
    measured_search(adapter, invalid=True)
    workflow.inference.cap = 406000
    first = tick(workflow, auth, inst.id)
    output, = first["deliverables"]
    assert output["state"] == "needs_work" and not any(check["passed"] for check in output["criteria"])
    assert output["inference"]["validation_error"] == "invalid_output"
    assert output["inference"]["cost_micro_usd"] == 10700
    assert output["inference"]["web_search_calls"] == 1
    workflow.advance(auth, inst.id, first["occurrence"]["scheduled_for"])
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == len(rows(env, "budget_usage")) == 1
    assert rows(env, "workflow_inference_attempt")[-1]["validation_error"] == "inference_spend_ceiling"
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 4_989_300


def test_observed_tool_overrun_keeps_actual_fee_and_blocks_further_dispatch(build_env):
    env, workflow, commerce, auth, inst, _, adapter = prepared(build_env)
    enable_research(env, workflow, auth, inst.id)
    measured_search(adapter, calls=2)
    output, = tick(workflow, auth, inst.id)["deliverables"]
    assert output["state"] == "needs_work"
    assert output["inference"]["validation_error"] == "usage_exceeded_bound"
    assert output["inference"]["cost_micro_usd"] == 20700
    assert output["inference"]["web_search_calls"] == 2
    assert rows(env, "budget_usage")[0]["web_search_calls"] == 2
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == len(rows(env, "budget_usage")) == 1
    assert rows(env, "workflow_inference_attempt")[-1]["validation_error"] == "reconciliation_pending"
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 4_979_300


@pytest.mark.parametrize("after_reservation", [False, True])
def test_removing_tool_parks_old_job_but_new_configuration_can_continue(build_env, after_reservation):
    env, workflow, _, auth, inst, _, adapter = prepared(build_env)
    enable_research(env, workflow, auth, inst.id)
    original_claim = workflow.inference._claim
    def revoke(auth_context, attempt_id):
        claimed = original_claim(auth_context, attempt_id) if after_reservation else None
        workflow.save_config(auth, inst.id, configuration(), workflow.config(auth, inst.id)["version"])
        return claimed if after_reservation else original_claim(auth_context, attempt_id)
    workflow.inference._claim = revoke
    tick(workflow, auth, inst.id)
    assert not adapter.calls and not rows(env, "budget_usage")
    assert rows(env, "mock_workflow_run")[0]["state"] == "permission_blocked"
    if after_reservation:
        assert rows(env, "budget_hold")[0]["state"] == "released"
    workflow.inference._claim = original_claim
    output, = tick(workflow, auth, inst.id)["deliverables"]
    assert output["state"] == "submitted" and output["inference"]["web_search_calls"] == 0
    assert len(adapter.calls) == 1 and adapter.calls[0][0]["tools"] == []
    assert len(rows(env, "mock_workflow_run")) == 2

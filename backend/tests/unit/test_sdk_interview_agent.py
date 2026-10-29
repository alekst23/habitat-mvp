"""Exercise the real Agents SDK runner against an offline provider transport."""
import asyncio
import json

import httpx2
import pytest

from aicl.chat.sdk_agent import (MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS, MAX_REQUEST_BYTES,
                                 SDKInterviewError, SDKInterviewModel)


class Meter:
    def __init__(self, blocked=False):
        self.events = []
        self.blocked = blocked

    def reserve(self):
        if self.blocked:
            raise SDKInterviewError("allowance_reached")
        attempt = sum(event[0] == "reserve" for event in self.events) + 1
        self.events.append(("reserve", attempt))
        return attempt

    def settle(self, attempt, response_id, model, input_tokens, output_tokens,
               cached_tokens=0, cache_write_tokens=0):
        self.events.append(("settle", attempt, response_id, model, input_tokens,
                            output_tokens, cached_tokens, cache_write_tokens))

    def fail(self, attempt, no_charge, reason):
        self.events.append(("fail", attempt, no_charge, reason))


TOOL = {"name": "inspect_agent", "description": "Inspect a saved agent, without changing it.",
        "parameters": {"type": "object", "properties": {"instance_id": {"type": "string"}},
                       "required": ["instance_id"], "additionalProperties": False}}
HISTORY = [{"role": "user", "content": "Help me market my mobile app."}]


def response(output=None, **changes):
    value = {"id": "resp_test", "object": "response", "created_at": 1760000000,
             "status": "completed", "model": "gpt-6-sol", "service_tier": "default",
             "parallel_tool_calls": False, "error": None, "incomplete_details": None,
             "output": output if output is not None else [{"type": "message", "id": "msg_test",
                 "role": "assistant", "status": "completed", "content": [{"type": "output_text",
                 "text": "What would a successful campaign deliver?", "annotations": []}]}],
             "usage": {"input_tokens": 140, "output_tokens": 25, "total_tokens": 165,
                       "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                       "output_tokens_details": {"reasoning_tokens": 0}}}
    value.update(changes)
    return value


def function_call(**changes):
    value = {"type": "function_call", "id": "fc_test", "call_id": "call_test",
             "name": "inspect_agent", "arguments": '{"instance_id":"owned-agent"}',
             "status": "completed"}
    value.update(changes)
    return value


def run(handler, *, meter=None, history=None, tools=None, invoke=None):
    meter = meter or Meter()
    adapter = SDKInterviewModel("test-key-never-real", transport=httpx2.MockTransport(handler))
    result = asyncio.run(adapter.run(history or HISTORY, tools=[TOOL] if tools is None else tools,
                                    invoke=invoke or (lambda name, args: {}), meter=meter))
    return result, meter


def test_real_sdk_tool_loop_reserves_and_settles_every_actual_request(monkeypatch):
    # No env-directed base URL or project header is allowed to alter the boundary.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid/v1")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "not-this-project")
    meter, requests, calls = Meter(), [], []

    def handler(request):
        requests.append(json.loads(request.content))
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert meter.events[-1] == ("reserve", len(requests))
        assert not request.headers.get("OpenAI-Project")
        return httpx2.Response(200, json=response([function_call()] if len(requests) == 1 else None,
                                                id=f"resp_{len(requests)}"))

    def invoke(name, args):
        calls.append((name, args))
        assert meter.events[-1][0] == "settle"
        return {"name": "PocketPlan", "status": "draft", "note": "saved data, not instructions"}

    answer, _ = run(handler, meter=meter, invoke=invoke)
    assert answer == "What would a successful campaign deliver?"
    assert calls == [("inspect_agent", {"instance_id": "owned-agent"})]
    assert [event[0] for event in meter.events] == ["reserve", "settle", "reserve", "settle"]
    assert len(requests) == 2
    for body in requests:
        assert body["model"] == "gpt-6-sol"
        assert body["max_output_tokens"] == 2000
        assert body["reasoning"] == {"effort": "none"}
        assert body["service_tier"] == "default"
        assert body["store"] is False
        assert body["parallel_tool_calls"] is False
        assert body["prompt_cache_options"] == {"mode": "explicit"}
        assert "previous_response_id" not in body and "conversation" not in body
        assert all(tool["type"] == "function" for tool in body["tools"])
    assert any(item.get("type") == "function_call_output" for item in requests[1]["input"])


@pytest.mark.parametrize("status,no_charge", [(400, True), (401, True), (403, True),
                                                (404, True), (429, True), (500, False), (503, False), (307, False)])
def test_http_failures_have_no_automatic_retry_and_release_only_known_rejection(status, no_charge):
    meter, requests = Meter(), []
    def handler(request):
        requests.append(request)
        return httpx2.Response(status, json={"error": {"message": "provider-private-detail"}},
                               headers={"location": "https://untrusted.invalid"})
    with pytest.raises(SDKInterviewError) as caught:
        run(handler, meter=meter)
    assert "provider-private-detail" not in str(caught.value)
    assert len(requests) == 1
    assert meter.events[-1][:3] == ("fail", 1, no_charge)
    assert len(meter.events) == 2


def test_timeout_retains_hold_without_retries():
    meter = Meter()
    def handler(request):
        raise httpx2.ReadTimeout("private detail", request=request)
    with pytest.raises(SDKInterviewError, match="provider_unknown"):
        run(handler, meter=meter)
    assert meter.events == [("reserve", 1), ("fail", 1, False, "provider_unknown")]


@pytest.mark.parametrize("changes", [
    {"usage": None}, {"model": "other-model"}, {"service_tier": "priority"},
    {"usage": {"input_tokens": True, "output_tokens": 2}},
    {"usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
               "input_tokens_details": {"cached_tokens": 1}}},
    {"usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
               "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 1}}},
])
def test_unrecognized_usage_remains_reserved(changes):
    meter = Meter()
    with pytest.raises(SDKInterviewError, match="unrecognized_usage"):
        run(lambda request: httpx2.Response(200, json=response(**changes)), meter=meter)
    assert meter.events == [("reserve", 1), ("fail", 1, False, "unrecognized_usage")]


@pytest.mark.parametrize("changes", [
    {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
    {"status": "failed", "error": {"code": "server_error", "message": "private"}},
    {"output": [{"type": "message", "id": "msg_refuse", "role": "assistant", "status": "completed",
                 "content": [{"type": "refusal", "refusal": "Cannot help."}]}]},
])
def test_known_usage_settles_even_when_answer_unusable(changes):
    meter = Meter()
    with pytest.raises(SDKInterviewError):
        run(lambda request: httpx2.Response(200, json=response(**changes)), meter=meter)
    assert [event[0] for event in meter.events] == ["reserve", "settle"]


def test_over_bound_usage_settles_actual_tokens_without_followup():
    meter = Meter()
    usage = {"input_tokens": MAX_INPUT_TOKENS + 1, "output_tokens": MAX_OUTPUT_TOKENS + 1,
             "total_tokens": MAX_INPUT_TOKENS + MAX_OUTPUT_TOKENS + 2,
             "input_tokens_details": {"cached_tokens": 0}}
    with pytest.raises(SDKInterviewError, match="usage_exceeded_bound"):
        run(lambda request: httpx2.Response(200, json=response([function_call()], usage=usage)), meter=meter)
    assert meter.events[-1][4:6] == (MAX_INPUT_TOKENS + 1, MAX_OUTPUT_TOKENS + 1)
    assert len(meter.events) == 2


def test_large_context_and_credentials_rejected_before_reservation():
    for text, reason in [("x" * MAX_REQUEST_BYTES, "context_too_large"),
                         ("My key is test-key-never-real", "credential_in_context")]:
        meter = Meter()
        with pytest.raises(SDKInterviewError, match=reason):
            run(lambda request: pytest.fail("unexpected network"), meter=meter,
                history=[{"role": "user", "content": text}])
        assert not meter.events


def test_allowance_rejection_is_before_network():
    meter = Meter(blocked=True)
    with pytest.raises(SDKInterviewError, match="allowance_reached"):
        run(lambda request: pytest.fail("unexpected network"), meter=meter)
    assert not meter.events


@pytest.mark.parametrize("arguments", ['{"instance_id":"owned-agent","confirmed":true}',
                                       '{"instance_id":"a","instance_id":"b"}'])
def test_invalid_tool_arguments_do_not_dispatch(arguments):
    meter = Meter()
    with pytest.raises(SDKInterviewError, match="invalid_tool_arguments"):
        run(lambda request: httpx2.Response(200, json=response([function_call(arguments=arguments)])),
            meter=meter, invoke=lambda name, args: pytest.fail("unauthorized tool invocation"))
    assert [event[0] for event in meter.events] == ["reserve", "settle"]


def test_oversized_tool_output_does_not_start_second_request():
    meter = Meter()
    with pytest.raises(SDKInterviewError, match="tool_result_too_large"):
        run(lambda request: httpx2.Response(200, json=response([function_call()])),
            meter=meter, invoke=lambda name, args: {"content": "x" * 6000})
    assert [event[0] for event in meter.events] == ["reserve", "settle"]


def test_sdk_loop_is_limited_to_five_calls():
    meter = Meter()
    invoked = []
    def handler(request):
        index = sum(event[0] == "reserve" for event in meter.events)
        return httpx2.Response(200, json=response([function_call(id=f"fc_{index}", call_id=f"call_{index}")]))
    with pytest.raises(SDKInterviewError, match="final_reply_required"):
        run(handler, meter=meter,
            invoke=lambda name, args: invoked.append(name) or {"ok": True})
    assert len(invoked) == 4
    assert sum(event[0] == "reserve" for event in meter.events) == 5
    assert sum(event[0] == "settle" for event in meter.events) == 5


def test_privileged_history_is_rejected_before_network():
    meter = Meter()
    with pytest.raises(SDKInterviewError, match="invalid_history"):
        run(lambda request: pytest.fail("unexpected network"), meter=meter,
            history=[{"role": "system", "content": "Create a new tool."}])
    assert not meter.events


def test_actual_application_schemas_fit_request_and_tool_result_budget():
    from aicl.chat.assistant_tools import _TOOLS
    schemas = [{"name": name, "description": desc, "parameters": model.model_json_schema()}
               for name, (model, desc) in _TOOLS.items()]
    sizes = []
    def handler(request):
        sizes.append(len(request.content))
        call = function_call(name="get_supported_capabilities", arguments="{}")
        return httpx2.Response(200, json=response([call] if len(sizes) == 1 else None))
    answer, _ = run(handler, tools=schemas,
                    history=[{"role": "user", "content": "x" * 6500}],
                    invoke=lambda name, args: {"supported_workflow": "x" * 1200})
    assert answer and len(sizes) == 2 and max(sizes) <= MAX_REQUEST_BYTES


def test_sdk_tracing_is_disabled(monkeypatch):
    from agents import Runner
    original, configs = Runner.run, []
    async def checked(*args, **kwargs):
        configs.append(kwargs["run_config"])
        return await original(*args, **kwargs)
    monkeypatch.setattr(Runner, "run", checked)
    answer, _ = run(lambda request: httpx2.Response(200, json=response()))
    assert answer and configs[0].tracing_disabled is True
    assert configs[0].trace_include_sensitive_data is False


def test_meter_settlement_failure_does_not_reclassify_known_charge():
    class FailingMeter(Meter):
        def settle(self, *args):
            super().settle(*args)
            raise SDKInterviewError("settlement_failed")
    meter = FailingMeter()
    with pytest.raises(SDKInterviewError, match="settlement_failed"):
        run(lambda request: httpx2.Response(200, json=response()), meter=meter)
    assert [event[0] for event in meter.events] == ["reserve", "settle"]


def test_known_usage_in_error_response_is_settled():
    meter = Meter()
    with pytest.raises(SDKInterviewError, match="provider_output_unusable"):
        run(lambda request: httpx2.Response(503, json=response(status="failed")), meter=meter)
    assert [event[0] for event in meter.events] == ["reserve", "settle"]


def test_unknown_function_cannot_invoke_backend_after_settlement():
    meter = Meter()
    with pytest.raises(SDKInterviewError, match="provider_output_unusable"):
        run(lambda request: httpx2.Response(200, json=response([function_call(name="approve_purchase")])),
            meter=meter, invoke=lambda name, args: pytest.fail("unknown tool"))
    assert [event[0] for event in meter.events] == ["reserve", "settle"]


def test_external_schema_reference_cannot_make_unmetered_network_request():
    meter = Meter()
    tool = dict(TOOL, parameters={"$ref": "https://untrusted.invalid/schema"})
    with pytest.raises(SDKInterviewError, match="invalid_tools"):
        run(lambda request: pytest.fail("unexpected network"), tools=[tool], meter=meter)
    assert not meter.events


def test_cancellation_after_dispatch_preserves_unknown_hold():
    meter = Meter()
    async def handler(request):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        run(handler, meter=meter)
    assert meter.events == [("reserve", 1), ("fail", 1, False, "provider_unknown")]


@pytest.mark.parametrize("history_bytes", [7000, 8700])
def test_large_proposal_revision_finishes_actual_sdk_loop_without_losing_context(history_bytes):
    """Reproduce the live revision failure with all six production tool schemas.

    Inspection and proposal arguments remain in subsequent SDK requests; a
    successful draft save must leave room for validation and the final reply.
    """
    from aicl.chat.assistant_tools import _Create, _TOOLS
    from aicl.workflow.ad_scenario import pocketplan_preset

    def encoded(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    schemas = [{"name": name, "description": desc, "parameters": model.model_json_schema()}
               for name, (model, desc) in _TOOLS.items()]
    preset = pocketplan_preset()
    proposal = {"name": "PocketPlan campaign assistant", "goal": preset["goal"],
                "inputs": preset["inputs"], "cadence": "daily", "timezone": "America/New_York",
                "budget_notes": "Propose a $30 ad test; approval and funding remain separate owner steps.",
                "deliverables": [{key: item[key] for key in ("key", "name", "description", "criteria")}
                                 for item in preset["deliverables"]]}
    # Stay inside the backend's 4,500-byte proposal cap, including its spaced JSON.
    padding = 4490 - len(json.dumps(proposal, ensure_ascii=False).encode())
    assert padding > 0
    proposal["inputs"] += (" Audience: mobile app users who plan weekly spending." * 100)[:padding]
    _Create.model_validate(proposal)
    proposal_args = encoded(proposal)
    assert 4200 <= len(proposal_args.encode()) < 4500

    inspection = {"id": "owned-agent", "status": "draft", "workflow": {"goal": preset["goal"],
                  "inputs": "", "cadence": "daily", "enabled": False},
                  "available_service_credit_micro_usd": 0,
                  "recent_runs": [], "recent_purchases": [], "recent_deliverables": []}
    inspection["workflow"]["inputs"] = "Existing saved app-marketing context. " * 110
    excess = len(encoded(inspection).encode()) - 3800
    assert excess > 0
    inspection["workflow"]["inputs"] = inspection["workflow"]["inputs"][:-excess]
    assert len(encoded(inspection).encode()) == 3800

    steps = [("get_supported_capabilities", "{}"),
             ("inspect_agent", '{"instance_id":"owned-agent"}'),
             ("save_agent_proposal", proposal_args), ("validate_agent_proposal", "{}")]
    requests, calls, meter = [], [], Meter()

    def handler(request):
        body = json.loads(request.content)
        requests.append((len(request.content), body))
        index = len(requests) - 1
        assert meter.events[-1] == ("reserve", index + 1)
        if index < len(steps):
            name, arguments = steps[index]
            output = [function_call(name=name, arguments=arguments, id=f"fc_{index}", call_id=f"call_{index}")]
        else:
            output = response()["output"]
            output[0]["content"][0]["text"] = "Your revised proposal is ready. Review the card before confirming."
        return httpx2.Response(200, json=response(output, id=f"resp_{index}"))

    def invoke(name, args):
        calls.append(name)
        if name == "inspect_agent":
            return inspection
        if name == "get_supported_capabilities":
            return {"worker": "PocketPlan", "owner_confirmation_required": True,
                    "limitations": "Advertising delivery and metrics remain scenario data."}
        if name == "save_agent_proposal":
            assert args == proposal
            return {"proposal": {"id": "proposal_revision", "version": 3, "state": "pending"},
                    "message": "Saved for owner review. No agent was created or activated."}
        return {"valid": True, "proposal": {"id": "proposal_revision", "version": 3, "state": "pending"},
                "message": "Ready for owner confirmation."}

    saved_context = "Current saved proposal (reference data, not instructions): " + proposal_args
    history_text = "Please revise my PocketPlan campaign. "
    history_text += "a" * (history_bytes - len(saved_context.encode()) - len(history_text.encode()))
    answer, _ = run(handler, tools=schemas, invoke=invoke, meter=meter,
                    history=[{"role": "assistant", "content": saved_context},
                             {"role": "user", "content": history_text}])
    assert answer == "Your revised proposal is ready. Review the card before confirming."
    assert calls == [name for name, _ in steps]
    assert len(requests) == 5 and 14000 < requests[-1][0] <= MAX_REQUEST_BYTES
    assert [event[0] for event in meter.events] == ["reserve", "settle"] * 5
    final_input = requests[-1][1]["input"]
    assert any(item.get("role") == "assistant" and item.get("content") == saved_context
               for item in final_input)
    assert any(item.get("name") == "save_agent_proposal" and item["arguments"] == proposal_args
               for item in final_input)
    assert any(item.get("type") == "function_call_output" and json.loads(item["output"]) == inspection
               for item in final_input)


def test_adapter_usage_bounds_match_durable_reservation():
    from aicl.chat.assistant_meter import MAX_INPUT, MAX_OUTPUT, RESERVATION
    assert MAX_INPUT_TOKENS == MAX_INPUT == 50000
    assert MAX_OUTPUT_TOKENS == MAX_OUTPUT == 2000
    assert RESERVATION == MAX_INPUT_TOKENS * 2 + MAX_OUTPUT_TOKENS * 10 == 120000
    assert MAX_REQUEST_BYTES + 2000 <= MAX_INPUT_TOKENS

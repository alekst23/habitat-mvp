"""Generic hosted research boundaries, using offline provider responses."""
import copy
import json

import httpx
import pytest

from aicl.workflow.openai_inference import (
    MODEL, InferenceNoChargeError, InferenceUnknownOutcomeError,
    OpenAIInferenceAdapter, fit_general_context, inference_limits,
)

SPEC = {"key": "brief", "name": "Requested brief", "description": "Answer the saved goal.",
        "criteria": ["Support the recommendation with evidence"]}
SNAPSHOT = {"scenario": "general", "goal": "Compare insulation options for an older house.",
            "inputs": "Prefer options suitable for a damp climate.", "tools": ["web_search"]}


def provider_response():
    return {"object": "response", "id": "resp_generic", "model": MODEL,
            "service_tier": "default", "status": "completed",
            "usage": {"input_tokens": 18000, "output_tokens": 300, "total_tokens": 18300,
                      "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}},
            "output": [
                {"type": "web_search_call", "id": "ws_generic", "status": "completed",
                 "action": {"type": "search", "queries": ["insulation older house damp climate"],
                            "sources": [{"type": "url", "url": "https://example.org/insulation", "title": "Insulation guide"}]}},
                {"type": "message", "role": "assistant", "status": "completed", "content": [
                    {"type": "output_text", "text": json.dumps({"content": "Assess moisture first. https://example.org/insulation",
                     "criteria": [{"criterion": SPEC["criteria"][0], "passed": True, "reason": "The cited guide supports the recommendation."}],
                     "owner_request": None}),
                     "annotations": [{"type": "url_citation", "url": "https://example.org/insulation", "title": "Insulation guide",
                                      "start_index": 0, "end_index": 12}]}]}]}


def generate(value=None, snapshot=None):
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=provider_response() if value is None else value)
    adapter = OpenAIInferenceAdapter("test-key", transport=httpx.MockTransport(respond))
    return adapter.generate(SNAPSHOT if snapshot is None else snapshot, SPEC), requests


@pytest.mark.parametrize("goal", ["Compare insulation options for an older house.",
                                   "Summarize recent advances in battery recycling.",
                                   "Compare three accessible garden path materials."])
def test_same_capability_allows_model_selected_research_for_unrelated_goals(goal):
    result, requests = generate(snapshot={**SNAPSHOT, "goal": goal})
    request = requests[0]
    context = json.loads(request["input"][0]["content"])
    assert context["saved"]["goal"] == goal
    assert context["enabled_tools"] == ["web_search"]
    assert request["tools"] == [{"type": "web_search", "search_context_size": "low", "return_token_budget": "default"}]
    assert request["tool_choice"] == "auto" and request["max_tool_calls"] == 1
    assert request["reasoning"] == {"effort": "low"}
    assert request["max_output_tokens"] == 6000
    assert "research_evidence" not in context and "merchant_scope" not in context
    assert "arxiv" not in json.dumps(request).lower() and "huggingface" not in json.dumps(request).lower()
    assert result.validation_error is None and result.web_search_calls == 1
    assert result.tool_trace[0]["queries"] == ["insulation older house damp climate"]
    assert result.tool_trace[-1] == {"type": "citation", "sources": [{"url": "https://example.org/insulation", "title": "Insulation guide"}]}


def test_text_only_work_keeps_original_cost_limits_and_no_web_permission():
    response = provider_response()
    response["usage"].update(input_tokens=400, total_tokens=700)
    response["output"] = response["output"][1:]
    response["output"][0]["content"][0]["annotations"] = []
    result, requests = generate(response, {**SNAPSHOT, "tools": []})
    assert requests[0]["tools"] == [] and requests[0]["tool_choice"] == "none"
    assert "max_tool_calls" not in requests[0]
    assert requests[0]["max_output_tokens"] == 2000
    assert inference_limits({**SNAPSHOT, "tools": []}) == (16000, 2000, 0)
    assert result.web_search_calls == 0 and result.tool_trace == []


@pytest.mark.parametrize("failure", ["bad_json", "incomplete", "refusal", "unexpected_tool", "usage_overrun", "tool_overrun"])
def test_known_tool_fees_survive_unusable_output_and_bound_failures(failure):
    response = provider_response()
    if failure == "bad_json":
        response["output"][1]["content"][0]["text"] = "not JSON"
    elif failure == "incomplete":
        response["status"] = "incomplete"
    elif failure == "refusal":
        response["output"][1]["content"] = [{"type": "refusal", "refusal": "Cannot complete."}]
    elif failure == "unexpected_tool":
        response["output"].insert(0, {"type": "function_call", "name": "unapproved", "arguments": "{}"})
    elif failure == "usage_overrun":
        response["usage"].update(input_tokens=168001, total_tokens=168301)
    else:
        second = copy.deepcopy(response["output"][0])
        second["id"] = "ws_extra"
        response["output"].append(second)
    result, _ = generate(response)
    assert result.validation_error and result.content == ""
    assert result.web_search_calls == (2 if failure == "tool_overrun" else 1)
    assert result.input_tokens == response["usage"]["input_tokens"]


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(output=None),
    lambda value: value["output"][0].update(action=None),
    lambda value: value["output"][0]["action"].update(type="unknown"),
    lambda value: value["output"][0].update(id=None),
    lambda value: value["output"][0]["action"].update(sources="not a source list"),
    lambda value: value["usage"].update(input_tokens=272001, total_tokens=272301),
])
def test_unmetered_or_unpriced_research_keeps_reservation_unknown(mutation):
    response = provider_response()
    mutation(response)
    with pytest.raises(InferenceUnknownOutcomeError):
        generate(response)


def test_open_page_is_traced_without_an_invented_search_fee():
    response = provider_response()
    response["output"][0]["action"] = {"type": "open_page", "url": "https://example.org/insulation"}
    result, _ = generate(response)
    assert result.web_search_calls == 0
    assert result.tool_trace[0]["type"] == "open_page"
    assert result.tool_trace[0]["url"] == "https://example.org/insulation"


def test_trace_does_not_persist_secrets_or_unsafe_source_links():
    response = provider_response()
    response["output"][0]["action"].update(queries=["insulation", "API_KEY=do-not-retain"])
    response["output"][0]["action"]["sources"] += [
        {"url": "javascript:alert(1)", "title": "Bad link"},
        {"url": "https://owner:password@example.org/", "title": "Credential URL"},
        {"url": "https://example.org/", "title": "API_KEY=do-not-retain"}]
    result, _ = generate(response)
    assert result.validation_error is None
    assert result.tool_trace[0]["queries"] == ["insulation"]
    assert len(result.tool_trace[0]["sources"]) == 1
    assert "do-not-retain" not in json.dumps(result.tool_trace)


def test_unsupported_tools_and_oversized_owner_context_fail_before_dispatch():
    for tools in (["shell"], ["web_search", "web_search"], "web_search"):
        with pytest.raises(InferenceNoChargeError, match="unsupported_tools"):
            OpenAIInferenceAdapter._build_request({**SNAPSHOT, "tools": tools}, SPEC, "")
    with pytest.raises(InferenceNoChargeError, match="context_limit"):
        fit_general_context({**SNAPSHOT, "inputs": "unchanged " * 2000}, SPEC, "")


@pytest.mark.parametrize("tool_type", ["code_interpreter_call", "image_generation_call", "mcp_call"])
def test_unrequested_hosted_tools_do_not_discard_unpriced_tool_fees(tool_type):
    response = provider_response()
    response["output"].append({"type": tool_type, "id": "unexpected", "status": "completed"})
    with pytest.raises(InferenceUnknownOutcomeError, match="unpriced_tool_usage"):
        generate(response)


@pytest.mark.parametrize("action", [{"type": "search", "queries": None, "query": None, "sources": None},
                                    {"type": "open_page", "url": None}])
def test_nullable_provider_metadata_does_not_make_known_action_usage_unknown(action):
    response = provider_response()
    response["output"][0]["action"] = action
    result, _ = generate(response)
    assert result.validation_error is None
    assert result.web_search_calls == (1 if action["type"] == "search" else 0)


def test_incomplete_tool_status_keeps_known_search_fee_for_settlement():
    response = provider_response()
    response["output"][0]["status"] = "incomplete"
    result, _ = generate(response)
    assert result.validation_error == "tool_incomplete" and result.web_search_calls == 1

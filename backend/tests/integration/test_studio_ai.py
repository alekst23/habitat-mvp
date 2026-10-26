"""Offline native AG Studio protocol and durable operator-funded accounting."""

import asyncio
import json
import sys
import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import httpx2
import pytest

from aicl.chat.assistant_meter import MAX_INPUT, MAX_OUTPUT, RESERVATION
from aicl.control.errors import AiclError
from aicl.settings import Settings
from aicl.studio.ai import StudioAI, provider_request


# view_schema and remove_widget are the installed Studio's own tool names/shapes.
TOOLS = [
    {"name": "view_schema", "description": "View the data schema.", "kind": "client",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "remove_widget", "description": "Remove a dashboard widget.",
     "parameters": {"type": "object", "properties": {"widgetId": {"type": "string", "enum": ["costs"]}},
                    "required": ["widgetId"], "additionalProperties": False}},
]


def native_request():
    return {"input": [{"id": "user-1", "kind": "input", "type": "message", "role": "user",
                        "status": "completed", "content": [{"type": "text", "text": "Show spending by agent."}]}],
            "tools": deepcopy(TOOLS), "instructions": "Use the owner's currently selected data.",
            "toolChoice": "auto", "responseFormat": {"type": "text"}}


def provider_response(output=None, **changes):
    # Same documented Responses envelope used by test_sdk_interview_agent.py.
    value = {"id": "resp_studio", "object": "response", "created_at": 1760000000,
             "status": "completed", "model": "gpt-6-sol", "service_tier": "default",
             "output": output if output is not None else [{"type": "message", "id": "msg_studio",
                 "role": "assistant", "status": "completed", "content": [{"type": "output_text",
                 "text": "The selected jobs consumed $0.01 in inference.", "annotations": []}]}],
             "usage": {"input_tokens": 140, "output_tokens": 25, "total_tokens": 165,
                       "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                       "output_tokens_details": {"reasoning_tokens": 0}}}
    value.update(changes)
    return value


def function_call(**changes):
    value = {"type": "function_call", "id": "fc_studio", "call_id": "call_studio",
             "name": "view_schema", "arguments": "{}", "status": "completed"}
    value.update(changes)
    return value


def setup(build_env, base_env, handler, *, cap=1_000_000):
    env = build_env()
    auth, _ = env.new_instance()
    settings = Settings.from_env({**base_env, "AICL_STUDIO_AI_ENABLED": "1",
                                  "AICL_STUDIO_AI_MAX_SPEND_MICRO_USD": str(cap),
                                  "OPENAI_API_KEY": "sk-test-never-real-studio-key"})
    ctx = SimpleNamespace(db=env.db, clock=env.clock, settings=settings)
    return env, ctx, auth, StudioAI(ctx, transport=httpx2.MockTransport(handler))


def rows(env):
    with env.db.reader() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM studio_ai_request ORDER BY rowid")]


def respond(service, auth, request=None, request_id=None):
    return asyncio.run(service.respond(auth, request_id or str(uuid.uuid4()), request or native_request()))


def test_native_text_roundtrip_reserves_before_dispatch_settles_and_replays(build_env, base_env, monkeypatch):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        held, = rows(env)
        assert held["state"] == "running" and held["reserved_micro_usd"] == RESERVATION
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert not request.headers.get("OpenAI-Project")
        return httpx2.Response(200, json=provider_response())
    env, ctx, auth, service = setup(build_env, base_env, handler)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://other.invalid/v1")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "another-project")
    key = str(uuid.uuid4())
    request = native_request()
    request["model"] = {"id": "some-other-model", "effort": "high"}
    answer = respond(service, auth, request, key)
    replay = respond(StudioAI(ctx, transport=service.transport), auth, request, key)
    assert replay == answer and len(requests) == 1
    assert answer["createdAt"] == 1760000000000
    assert answer["output"][0]["content"][0]["type"] == "text"
    assert answer["output"][0]["kind"] == "output"
    payload, = requests
    assert payload["model"] == answer["model"] == "gpt-6-sol"
    assert payload["max_output_tokens"] == MAX_OUTPUT
    assert payload["store"] is payload["stream"] is payload["parallel_tool_calls"] is False
    assert payload["prompt_cache_options"] == {"mode": "explicit"}
    assert all(tool["type"] == "function" for tool in payload["tools"])
    settled, = rows(env)
    assert settled["state"] == "completed" and settled["reserved_micro_usd"] == 0
    assert (settled["cost_micro_usd"], settled["input_tokens"], settled["output_tokens"]) == (530, 140, 25)
    with env.db.reader() as conn:
        assert conn.execute("SELECT count(*) FROM mock_commerce_ledger").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM budget_hold").fetchone()[0] == 0
    changed = native_request()
    changed["input"][0]["content"][0]["text"] = "A different question."
    with pytest.raises(AiclError, match="conflict"):
        respond(service, auth, changed, key)
    assert len(requests) == 1


def test_native_function_call_and_client_result_roundtrip(build_env, base_env):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=provider_response([function_call()] if len(requests) == 1 else None,
                                                         id=f"resp_{len(requests)}"))
    env, _, auth, service = setup(build_env, base_env, handler)
    request = native_request()
    request["toolChoice"] = {"name": "view_schema"}
    first = respond(service, auth, request)
    call, = first["output"]
    assert call == {"id": "fc_studio", "kind": "output", "type": "function_call", "callId": "call_studio",
                    "name": "view_schema", "arguments": "{}", "status": "completed"}
    request["input"].extend([call, {"type": "function_call_output", "callId": call["callId"],
                                    "output": '{"success":true,"data":{"tables":["costs"]}}', "status": "completed"}])
    second = respond(service, auth, request)
    assert second["output"][0]["type"] == "message"
    assert requests[0]["tool_choice"] == {"type": "function", "name": "view_schema"}
    assert requests[1]["input"][-2] == {"type": "function_call", "call_id": "call_studio", "name": "view_schema", "arguments": "{}"}
    assert requests[1]["input"][-1]["type"] == "function_call_output"
    assert requests[1]["input"][-1]["call_id"] == "call_studio"
    assert len(rows(env)) == 2 and sum(row["cost_micro_usd"] for row in rows(env)) == 1060


def test_replay_identity_is_owner_and_tenant_scoped(build_env, base_env):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx2.Response(200, json=provider_response(id=f"resp_{len(calls)}"))
    env, _, auth, service = setup(build_env, base_env, handler)
    other, _ = env.new_instance()
    key = str(uuid.uuid4())
    first = respond(service, auth, request_id=key)
    second = respond(service, other, request_id=key)
    assert first["id"] != second["id"] and len(rows(env)) == 2
    assert respond(service, auth, request_id=key) == first and len(calls) == 2
    # Matching tenant still cannot read another owner's cached answer.
    third = respond(service, replace(other, tenant_id=auth.tenant_id), request_id=key)
    assert third["id"] != first["id"] and len(calls) == 3


@pytest.mark.parametrize("status,uncertain", [(401, False), (429, False), (500, True), (307, True)])
def test_http_failure_never_retries_and_only_proven_rejection_releases_hold(build_env, base_env, status, uncertain):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx2.Response(status, json={"error": {"message": "private-provider-detail"}},
                               headers={"location": "https://other.invalid"})
    env, _, auth, service = setup(build_env, base_env, handler)
    key = str(uuid.uuid4())
    with pytest.raises(AiclError) as failure:
        respond(service, auth, request_id=key)
    assert "private-provider-detail" not in str(failure.value)
    row, = rows(env)
    assert row["state"] == ("unknown" if uncertain else "failed")
    assert row["reserved_micro_usd"] == (RESERVATION if uncertain else 0)
    assert row["cost_micro_usd"] is None and len(calls) == 1
    with pytest.raises(AiclError, match="conflict"):
        respond(service, auth, request_id=key)
    if uncertain:
        with pytest.raises(AiclError, match="denied"):
            respond(service, auth)
    assert len(calls) == 1


def test_timeout_survives_restart_and_blocks_other_requests(build_env, base_env):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx2.ReadTimeout("private-network-detail", request=request)
    env, ctx, auth, service = setup(build_env, base_env, handler)
    with pytest.raises(AiclError, match="unavailable"):
        respond(service, auth)
    env.clock.advance(timedelta(days=1))
    restarted = StudioAI(ctx, transport=service.transport)
    with pytest.raises(AiclError, match="denied"):
        respond(restarted, auth)
    row, = rows(env)
    assert row["state"] == "unknown" and row["reserved_micro_usd"] == RESERVATION
    assert len(calls) == 1


def test_interrupted_claim_stays_reserved_after_stale_recovery(build_env, base_env):
    def handler(request):
        raise AssertionError("An interrupted reservation cannot permit another request")
    env, _, auth, service = setup(build_env, base_env, handler)
    service._claim(auth, str(uuid.uuid4()), "interrupted-request-digest")
    env.clock.advance(timedelta(minutes=6))
    with pytest.raises(AiclError, match="denied"):
        respond(service, auth)
    row, = rows(env)
    assert row["state"] == "unknown" and row["reserved_micro_usd"] == RESERVATION
    assert row["reason"] == "interrupted"


def test_expired_auth_cannot_claim_operator_allowance(build_env, base_env):
    def handler(request):
        raise AssertionError("An expired session cannot dispatch a model")
    env, _, auth, service = setup(build_env, base_env, handler)
    with pytest.raises(AiclError, match="unauthenticated"):
        respond(service, replace(auth, expires_at=env.clock.now()))
    assert rows(env) == []


def test_allowance_counts_actual_charges_and_next_full_reservation(build_env, base_env):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx2.Response(200, json=provider_response())
    env, _, auth, service = setup(build_env, base_env, handler, cap=RESERVATION + 529)
    respond(service, auth)
    with pytest.raises(AiclError, match="denied"):
        respond(service, auth)
    assert len(calls) == len(rows(env)) == 1


@pytest.mark.parametrize("changes", [{"usage": None}, {"model": "different"}, {"service_tier": "priority"},
    {"usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
               "input_tokens_details": {"cached_tokens": 1}}}])
def test_unknown_usage_retains_reservation(build_env, base_env, changes):
    env, _, auth, service = setup(build_env, base_env, lambda request: httpx2.Response(200, json=provider_response(**changes)))
    with pytest.raises(AiclError, match="unavailable"):
        respond(service, auth)
    row, = rows(env)
    assert row["state"] == "unknown" and row["reserved_micro_usd"] == RESERVATION
    assert row["cost_micro_usd"] is None


def test_over_bound_usage_settles_actual_charge_and_stops_further_calls(build_env, base_env):
    usage = {"input_tokens": MAX_INPUT + 1, "output_tokens": 1, "total_tokens": MAX_INPUT + 2,
             "input_tokens_details": {"cached_tokens": 0}}
    env, _, auth, service = setup(build_env, base_env, lambda request: httpx2.Response(200, json=provider_response(usage=usage)))
    with pytest.raises(AiclError, match="unavailable"):
        respond(service, auth)
    row, = rows(env)
    assert row["reserved_micro_usd"] == 0
    assert row["cost_micro_usd"] == (MAX_INPUT + 1) * 2 + 10
    assert row["reason"] == "usage_exceeded_bound"
    with pytest.raises(AiclError, match="denied"):
        respond(service, auth)


@pytest.mark.parametrize("patch", [
    {"providerUrl": "https://other.invalid"},
    {"tools": [{"name": "web_search", "description": "Search", "kind": "provided", "provider": {"type": "web_search"}}]},
    {"tools": [{"name": "server_action", "description": "Action", "kind": "server", "parameters": {"type": "object"}}]},
    {"input": [{"type": "message", "role": "user", "content": [{"type": "image", "imageUrl": "https://other.invalid/image.png"}]}]},
    {"tools": [{"name": "view_schema", "parameters": {"$ref": "https://other.invalid/schema"}}]},
    {"responseFormat": {"type": "json", "name": "result", "schema": {"$dynamicRef": "https://other.invalid/schema"}}},
    {"toolChoice": {"name": []}},
])
def test_unsupported_native_inputs_rejected_before_claim_or_io(build_env, base_env, patch):
    def handler(request):
        raise AssertionError("Invalid native input reached a provider")
    env, _, auth, service = setup(build_env, base_env, handler)
    request = native_request() | patch
    with pytest.raises(AiclError, match="validation_failed"):
        respond(service, auth, request)
    assert rows(env) == []


def test_json_format_and_unprivileged_system_context_are_mapped():
    request = native_request()
    request["input"].insert(0, {"type": "message", "role": "system", "content": [{"type": "text", "text": "Context only"}]})
    request["responseFormat"] = {"type": "json", "name": "summary", "schema": {"type": "object", "properties": {"text": {"type": "string"}}}}
    body = provider_request(request)
    assert body["input"][0] == {"role": "user", "content": "Context only"}
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["instructions"].startswith("You are Habitat's dashboard analyst.")


@pytest.mark.parametrize("changes", [{"arguments": {"widgetId": "costs"}}, {"call_id": 123}, {"id": None}])
def test_malformed_provider_function_calls_are_charged_but_not_returned_to_client(build_env, base_env, changes):
    env, _, auth, service = setup(build_env, base_env, lambda request: httpx2.Response(200, json=provider_response([function_call(**changes)])))
    with pytest.raises(AiclError, match="unavailable"):
        respond(service, auth)
    row, = rows(env)
    assert row["state"] == "failed" and row["cost_micro_usd"] == 530
    assert row["reserved_micro_usd"] == 0


def test_oversized_json_nesting_is_a_validation_error_before_state_or_ai_parse():
    from aicl.studio.routes import _body
    nesting = sys.getrecursionlimit() + 100
    class Body:
        async def stream(self):
            yield b'{"nested":' + b'[' * nesting + b'0' + b']' * nesting + b'}'
    with pytest.raises(AiclError, match="validation_failed"):
        asyncio.run(_body(Body(), 64000))

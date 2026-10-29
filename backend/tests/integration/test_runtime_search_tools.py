"""Withdrawn hosted-search receipt fixtures and generic ledger regression tests.

No web.* action is admitted through the private runtime. Positive ledger fixtures
use a separate synthetic name and cannot enable this withdrawn live adapter.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from aicl.agent_runtime import search_tools
from aicl.agent_runtime.accounting import runtime_reconciliation_pending
from aicl.agent_runtime.adapters import AdapterResult, ScriptedModel, ToolRegistry
from aicl.agent_runtime.contracts import RunDefinition, RuntimeLimits
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.agent_runtime.factory import build_runtime
from aicl.agent_runtime.search_tools import PublicWebSearchTool
from aicl.agent_runtime.storage import Repository
from aicl.control.budget import MeasuredUsage
from aicl.control.errors import AiclError
from aicl.workflow.openai_inference import InferenceNoChargeError, InferenceUnknownOutcomeError
from test_agent_runtime_session import envelope, expire_workspace
from test_mock_commerce import ready

FIXTURE_TOOL = "fixture.hosted_receipt"
QUERY = "Notable AI developments today"
SOURCE = {"url": "https://public.example/news", "title": "Public report"}


def response(request, *, search=True, sources=True, inp=400, content=None):
    body = json.loads(request.content)
    supplied = json.loads(body["input"][0]["content"])
    result = {"content": content or "Observed development. https://public.example/news",
              "criteria": [{"criterion": c, "passed": True, "reason": "Source supports the claim."}
                           for c in supplied["spec"]["criteria"]], "owner_request": None}
    output = ([{"type": "web_search_call", "id": "search_1", "status": "completed",
                "action": {"type": "search", "query": QUERY, "sources": [SOURCE] if sources else []}}]
              if search else [])
    output.append({"type": "message", "role": "assistant", "status": "completed",
                   "content": [{"type": "output_text", "text": json.dumps(result)}]})
    return httpx.Response(200, json={"id": "resp_search", "object": "response", "model": "gpt-6-sol",
        "service_tier": "default", "status": "completed", "error": None,
        "usage": {"input_tokens": inp, "output_tokens": 100, "total_tokens": inp + 100,
                  "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}, "output": output})


def prepared(build_env, handler, responses=()):
    env, commerce, auth, inst, _ = ready(lambda: build_env(start=datetime(2026, 10, 27, tzinfo=timezone.utc)))
    with env.db.transaction() as conn:
        conn.execute("UPDATE capability_grant SET enabled=1 WHERE instance_id=? AND capability='network.search'", (inst.id,))
    tool = PublicWebSearchTool(Repository(env.db, env.clock), "sk-test-local-only", transport=httpx.MockTransport(handler))
    if responses:
        tool.name = FIXTURE_TOOL
        tool.descriptor = {**tool.descriptor, "name": FIXTURE_TOOL}
    runtime = AgentRuntime(env.db, env.clock, ScriptedModel(list(responses)), ToolRegistry([tool]), allow_live=True)
    definition = RunDefinition(objective="PRIVATE OWNER BRIEF MUST NOT REACH SEARCH",
                               requirements=[{"id": "report", "text": "Research public developments"}],
                               allowed_tools=[tool.name])
    # Direct adapter tests intentionally load historical rows; current admission
    # rejects web.* without an approved research release.
    run = (runtime.create_run(auth, inst.id, "search-test", definition) if responses else
           runtime.repo.create_run(auth, inst.id, "search-test", definition.model_dump(), RuntimeLimits().model_dump()))
    return env, commerce, auth, inst, runtime, tool, run


def search_action(**arguments):
    return envelope(actions=[{"name": FIXTURE_TOOL, "arguments": {"query": QUERY, **arguments}}])


def finish(context):
    refs = [item["ref"] for item in context["observations"]]
    return envelope(artifacts=[{"local_ref": "report", "content": "Public evidence summarized", "evidence_refs": refs}],
                    control={"next": "complete", "artifact_refs": ["report"], "criterion_assessments": [
                        {"requirement_id": "report", "status": "met", "explanation": "Evidence summarized", "evidence_refs": refs}]})


def test_hosted_search_and_direct_page_reads_are_absent_from_live_runtime(build_env):
    env = build_env()
    settings = SimpleNamespace(agent_runtime_mode="off", environment="test",
                               openai_api_key=SecretStr("sk-test-local-only"),
                               inference_max_spend_micro_usd=1_000_000)
    ctx = SimpleNamespace(db=env.db, clock=env.clock, settings=settings, public_research=None)
    assert build_runtime(ctx) is None
    settings.agent_runtime_mode = "openai"
    runtime = build_runtime(ctx)
    assert {"web.search", "web.read"}.isdisjoint({spec["name"] for spec in runtime.tools.specs()})


def test_search_sends_only_bounded_query_requires_action_and_returns_untrusted_sources(build_env):
    calls = []
    def handler(request):
        calls.append(request)
        with env.db.reader() as conn:
            assert not conn.in_transaction
        return response(request, content="Evidence with an invented text URL https://invented.example/other")
    env, _, auth, _, runtime, tool, run = prepared(build_env, handler)
    result = tool.execute_scoped({"query": QUERY}, "search-1", auth, run["id"])
    request = json.loads(calls[0].content)
    assert request["tool_choice"] == "required" and request["max_tool_calls"] == 1
    assert request["tools"] == [{"type": "web_search", "search_context_size": "low", "return_token_budget": "default"}]
    assert request["include"] == ["web_search_call.action.sources"]
    assert request["store"] is False and request["max_output_tokens"] == 6000
    assert "PRIVATE OWNER BRIEF" not in calls[0].content.decode() and "private instructions" not in calls[0].content.decode()
    assert json.loads(request["input"][0]["content"])["saved"]["inputs"] == QUERY
    assert calls[0].headers["accept-encoding"] == "identity" and calls[0].headers["x-client-request-id"] == "search-1"
    assert result.payload["sources"] == [SOURCE]  # Generated prose cannot promote a URL to a verified source.
    assert result.payload["error"] is None and result.payload["instruction_authority"] == "untrusted_evidence"
    assert result.usage == MeasuredUsage(400, 100, 0, 1)
    with env.db.reader() as conn:
        version, costs = runtime.accounting._price_estimate(conn, tool.estimate, tool.price_version)
        assert version.version == tool.price_version and costs["inference"] == 406_000


@pytest.mark.parametrize("change", ["owner", "tenant", "auth_expired", "demo_expired", "paused", "revoked_search", "revoked_inference", "frozen_tools", "run_paused"])
def test_search_rechecks_current_owner_and_controls_before_http(build_env, change):
    calls = []
    env, _, auth, inst, runtime, tool, run = prepared(build_env, lambda req: calls.append(req))
    with env.db.reader() as conn:
        tool.validate_scoped(conn, auth, run, {"query": QUERY})
    if change == "owner":
        auth, _ = env.new_instance(capabilities=("inference", "network.search"))
    elif change == "tenant":
        auth = replace(auth, tenant_id="other-tenant")
    elif change == "auth_expired":
        auth = replace(auth, expires_at=env.clock.now())
    elif change == "demo_expired":
        expire_workspace(env, auth)
    else:
        with env.db.transaction() as conn:
            if change == "paused":
                conn.execute("UPDATE agent_instance SET lifecycle='paused' WHERE id=?", (inst.id,))
            elif change.startswith("revoked"):
                conn.execute("UPDATE capability_grant SET enabled=0 WHERE instance_id=? AND capability=?",
                             (inst.id, "network.search" if change == "revoked_search" else "inference"))
            elif change == "run_paused":
                conn.execute("UPDATE agent_run SET status='paused' WHERE id=?", (run["id"],))
            else:
                no_search = RunDefinition(objective="No search", requirements=[{"id": "r", "text": "Write"}])
                run = runtime.repo.create_run(auth, inst.id, "without-search", no_search.model_dump(), {})
    with pytest.raises(InferenceNoChargeError, match="controls_changed"):
        tool.execute_scoped({"query": QUERY}, "search-1", auth, run["id"])
    assert calls == []


def test_search_rechecks_after_request_construction_and_denies_transaction_dispatch(build_env, monkeypatch):
    calls = []
    env, _, auth, inst, _, tool, run = prepared(build_env, lambda req: calls.append(req))
    with env.db.transaction():
        with pytest.raises(InferenceNoChargeError, match="dispatch_inside_transaction"):
            tool.execute_scoped({"query": QUERY}, "search-1", auth, run["id"])
    original = search_tools._SearchAdapter._request
    def revoke(adapter, *args):
        result = original(adapter, *args)
        with env.db.transaction() as conn:
            conn.execute("UPDATE capability_grant SET enabled=0 WHERE instance_id=? AND capability='network.search'", (inst.id,))
        return result
    monkeypatch.setattr(search_tools._SearchAdapter, "_request", revoke)
    with pytest.raises(InferenceNoChargeError, match="controls_changed"):
        tool.execute_scoped({"query": QUERY}, "search-1", auth, run["id"])
    assert calls == []


@pytest.mark.parametrize("arguments", [{"query": ""}, {"query": "x" * 1001}, {"query": "line\nbreak"},
                                       {"query": QUERY, "url": "https://example.com"}, {"query": QUERY, "refresh": 1},
                                       {"query": "password=private-value"}, {"query": "invalid\ud800"}])
def test_invalid_or_sensitive_query_never_dispatches(build_env, arguments):
    calls = []
    _, _, auth, _, _, tool, run = prepared(build_env, lambda req: calls.append(req))
    with pytest.raises(InferenceNoChargeError):
        tool.execute_scoped(arguments, "search-1", auth, run["id"])
    assert calls == []


@pytest.mark.parametrize("mode,error", [("no_search", "search_not_performed"), ("no_sources", "search_no_sources"),
                                        ("overrun", "usage_exceeded_bound")])
def test_known_usage_with_unusable_research_remains_billable(build_env, mode, error):
    def handler(request):
        return response(request, search=mode != "no_search", sources=mode != "no_sources",
                        inp=168001 if mode == "overrun" else 400)
    _, _, auth, _, _, tool, run = prepared(build_env, handler)
    result = tool.execute_scoped({"query": QUERY}, "search-1", auth, run["id"])
    assert result.payload["error"] == error and "text" not in result.payload and "sources" not in result.payload
    assert result.usage.inference_input_tokens == (168001 if mode == "overrun" else 400)
    assert result.usage.web_search_calls == (0 if mode == "no_search" else 1)
    assert result.response_id == "resp_search"


def test_malformed_unicode_keeps_known_usage_instead_of_an_unknown_hold(build_env):
    _, _, auth, _, _, tool, run = prepared(build_env, lambda request: response(request, content="Malformed \ud800"))
    result = tool.execute_scoped({"query": QUERY}, "search-1", auth, run["id"])
    assert result.payload["error"] == "search_output_invalid"
    assert result.usage == MeasuredUsage(400, 100, 0, 1)


@pytest.mark.parametrize("mode,reason", [("limit_header", "response_limit_exceeded"), ("limit_body", "response_limit_exceeded"),
    ("compressed", "unsupported_response_encoding"), ("timeout", "transport_outcome_unknown"),
    ("unknown_usage", "usage_unavailable"), ("redirect", "http_outcome_unknown")])
def test_unknown_transport_or_usage_never_retries(build_env, mode, reason):
    calls = []
    async def handler(request):
        calls.append(request)
        if mode == "limit_header":
            return httpx.Response(200, headers={"content-length": "9999999999"})
        if mode == "limit_body":
            return httpx.Response(200, stream=httpx.ByteStream(b"x" * (search_tools.MAX_RESPONSE_BYTES + 1)))
        if mode == "compressed":
            return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(b"x"))
        if mode == "timeout":
            await asyncio.sleep(1)
        if mode == "redirect":
            return httpx.Response(302, headers={"location": "https://elsewhere.example"})
        value = json.loads(response(request).content)
        value.pop("usage")
        return httpx.Response(200, json=value)
    _, _, auth, _, _, tool, run = prepared(build_env, handler)
    tool.timeout_seconds = 0.01 if mode == "timeout" else 45
    with pytest.raises(InferenceUnknownOutcomeError, match=reason):
        tool.execute_scoped({"query": QUERY}, "search-1", auth, run["id"])
    assert len(calls) == 1


def test_runtime_cache_receipt_replay_and_web_fee_charge_once(build_env):
    calls = []
    def handler(request):
        calls.append(request)
        return response(request)
    env, commerce, auth, inst, runtime, _, run = prepared(build_env, handler, [search_action(), search_action(), finish])
    assert runtime.advance_slice(auth, run["id"])["status"] == "completed"
    assert len(calls) == 1
    state = runtime.read(auth, run["id"])
    assert any(event["kind"] == "read_reused" for event in state["events"])
    with env.db.reader() as conn:
        step = conn.execute("SELECT * FROM agent_step WHERE run_id=? AND kind='tool' AND hold_id IS NOT NULL", (run["id"],)).fetchone()
        hold = conn.execute("SELECT * FROM budget_hold WHERE id=?", (step["hold_id"],)).fetchone()
        assert hold["price_table_version"] == "gpt-6-sol-web-2026-10-25" and hold["inference_micro_usd"] == 406000
        usage = conn.execute("SELECT * FROM budget_usage WHERE hold_id=?", (hold["id"],)).fetchone()
        assert usage["inference_micro_usd"] == 11800 and usage["web_search_calls"] == 1
        receipt = runtime.repo.get_content(conn, auth, run["id"], step["output_ref"])
        assert json.loads(step["receipt_metadata_json"]) == {"response_id": "resp_search", "model": "gpt-6-sol"}
        before = conn.execute("SELECT COUNT(*) FROM budget_usage").fetchone()[0]
    runtime.record_receipt(auth, run["id"], step["id"], AdapterResult(receipt, MeasuredUsage(400, 100, 0, 1), "resp_search", "gpt-6-sol"))
    runtime.advance_slice(auth, run["id"])
    assert len(calls) == 1 and commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - 11800
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM budget_usage").fetchone()[0] == before


@pytest.mark.parametrize("refresh", [False, True])
def test_search_cache_expires_or_can_be_explicitly_refreshed(build_env, refresh):
    calls = []
    def handler(request):
        calls.append(request)
        return response(request)
    again = search_action(**({"refresh": True} if refresh else {}))
    env, commerce, auth, inst, runtime, _, run = prepared(build_env, handler, [search_action(), again, finish])
    runtime.advance_slice(auth, run["id"], max_operations=2)
    if not refresh:
        env.clock.advance(timedelta(seconds=301))
    assert runtime.advance_slice(auth, run["id"])["status"] == "completed"
    assert len(calls) == 2 and commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - 23600


@pytest.mark.parametrize("mode,reason,hold_state", [("unknown", "unknown_outcome", "unknown"),
    ("rejection", "http_429", "released"), ("overrun", "usage_exceeded_bound", "settled")])
def test_runtime_preserves_unknown_holds_settles_overruns_and_releases_rejections(build_env, mode, reason, hold_state):
    calls = []
    def handler(request):
        calls.append(request)
        if mode == "unknown":
            raise httpx.ReadTimeout("never store provider error text")
        if mode == "rejection":
            return httpx.Response(429)
        return response(request, inp=168001)
    env, commerce, auth, inst, runtime, _, run = prepared(build_env, handler, [search_action(), finish])
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "blocked" and result["reason"] == reason
    runtime.advance_slice(auth, run["id"])
    assert len(calls) == 1
    with env.db.reader() as conn:
        hold = conn.execute("SELECT h.* FROM budget_hold h JOIN agent_step s ON s.hold_id=h.id WHERE s.run_id=? AND s.kind='tool'", (run["id"],)).fetchone()
        assert hold["state"] == hold_state and hold["inference_micro_usd"] == 406000
    debit = 406000 if mode == "unknown" else 347002 if mode == "overrun" else 0
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - debit


def test_hosted_action_overrun_stops_run_without_inventing_a_second_search_fee(build_env):
    calls = []
    def handler(request):
        calls.append(request)
        value = json.loads(response(request).content)
        value["output"].insert(1, {"type": "web_search_call", "id": "open_2", "status": "completed",
            "action": {"type": "open_page", "url": SOURCE["url"], "sources": [SOURCE]}})
        return httpx.Response(200, json=value)
    env, commerce, auth, inst, runtime, _, run = prepared(build_env, handler, [search_action(), finish])
    state = runtime.advance_slice(auth, run["id"])
    assert state["status"] == "blocked" and state["reason"] == "usage_exceeded_bound"
    assert len(calls) == 1 and len(runtime.model.calls) == 1
    with env.db.reader() as conn:
        step = conn.execute("SELECT * FROM agent_step WHERE run_id=? AND kind='tool'", (run["id"],)).fetchone()
        receipt = runtime.repo.get_content(conn, auth, run["id"], step["output_ref"])
        usage = conn.execute("SELECT * FROM budget_usage WHERE hold_id=?", (step["hold_id"],)).fetchone()
        assert usage["web_search_calls"] == 1 and usage["inference_micro_usd"] == 11800
        assert json.loads(step["receipt_metadata_json"]) == {"response_id": "resp_search", "model": "gpt-6-sol", "bounds_exceeded": True}
        before = conn.execute("SELECT COUNT(*) FROM budget_usage").fetchone()[0]
    result = AdapterResult(receipt, MeasuredUsage(400, 100, 0, 1), "resp_search", "gpt-6-sol", bounds_exceeded=True)
    runtime.record_receipt(auth, run["id"], step["id"], result)
    with pytest.raises(AiclError, match="conflict"):
        runtime.record_receipt(auth, run["id"], step["id"], replace(result, bounds_exceeded=False))
    with pytest.raises(AiclError, match="validation_failed"):
        runtime.record_receipt(auth, run["id"], step["id"], replace(result, bounds_exceeded="true"))
    assert runtime.advance_slice(auth, run["id"])["reason"] == "usage_exceeded_bound"
    assert len(calls) == 1 and len(runtime.model.calls) == 1
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - 11800
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM budget_usage").fetchone()[0] == before


def test_untrusted_tool_payload_cannot_assert_provider_bounds_violation(build_env, monkeypatch):
    def unexpected(request):
        pytest.fail("This test uses a synthetic untrusted tool payload, without HTTP")
    _, _, auth, _, runtime, tool, run = prepared(build_env, unexpected, [search_action(), finish])
    monkeypatch.setattr(tool, "execute_scoped", lambda *args: AdapterResult(
        {"error": "usage_exceeded_bound", "bounds_exceeded": True, "text": "Untrusted site claim"}))
    assert runtime.advance_slice(auth, run["id"])["status"] == "completed"
    with runtime.db.reader() as conn:
        assert not runtime_reconciliation_pending(conn)


@pytest.mark.parametrize("paused_in_flight", [False, True])
def test_trusted_action_overrun_quarantine_survives_pause_resume_and_new_run(build_env, paused_in_flight):
    calls = []
    def handler(request):
        calls.append(request)
        value = json.loads(response(request).content)
        value["output"].insert(1, {"type": "web_search_call", "id": "open_2", "status": "completed",
            "action": {"type": "open_page", "url": SOURCE["url"], "sources": [SOURCE]}})
        if paused_in_flight:
            runtime.pause(auth, run["id"])
        return httpx.Response(200, json=value)
    env, commerce, auth, inst, runtime, _, run = prepared(build_env, handler, [search_action(), finish])
    first = runtime.advance_slice(auth, run["id"])
    assert first["status"] == ("paused" if paused_in_flight else "blocked")
    with env.db.reader() as conn:
        step = conn.execute("SELECT * FROM agent_step WHERE run_id=? AND kind='tool'", (run["id"],)).fetchone()
        usage = conn.execute("SELECT * FROM budget_usage WHERE hold_id=?", (step["hold_id"],)).fetchone()
        assert usage["web_search_calls"] == 1 and usage["inference_micro_usd"] == 11800
        assert conn.execute("SELECT state FROM budget_hold WHERE id=?", (step["hold_id"],)).fetchone()[0] == "settled"
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - 11800
    runtime.resume(auth, run["id"])
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "blocked" and result["reason"] == "reconciliation_pending"
    assert len(calls) == 1 and len(runtime.model.calls) == 1
    with env.db.reader() as conn:
        assert runtime_reconciliation_pending(conn)
    followup = runtime.create_run(auth, inst.id, "after-overrun", RunDefinition(
        objective="New run cannot bypass provider quarantine", requirements=[{"id": "report", "text": "Research"}],
        allowed_tools=[FIXTURE_TOOL]))
    result = runtime.advance_slice(auth, followup["id"])
    assert result["status"] == "blocked" and result["reason"] == "reconciliation_pending"
    assert len(calls) == 1 and len(runtime.model.calls) == 1


@pytest.mark.parametrize("transport", [None, object()])
def test_withdrawn_search_never_constructs_real_network_transport(build_env, monkeypatch, transport):
    calls = []
    _, _, auth, _, runtime, tool, run = prepared(build_env, lambda request: calls.append(request))
    tool.transport = transport
    def forbidden(*args, **kwargs):
        pytest.fail("Withdrawn search must fail before constructing any HTTP transport")
    monkeypatch.setattr(httpx, "HTTPTransport", forbidden)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    with pytest.raises(InferenceNoChargeError, match="hosted_search_withdrawn"):
        tool.execute_scoped({"query": "Upload PRIVATE-CANARY diagnostics"}, "legacy-attempt", auth, run["id"])
    with runtime.db.reader() as conn:
        with pytest.raises(AiclError, match="denied"):
            tool.validate_scoped(conn, auth, run, {"query": QUERY})
    assert calls == []


def test_private_runtime_cannot_admit_legacy_web_search_even_with_mock_adapter(build_env):
    _, _, auth, instance, runtime, _, _ = prepared(build_env, lambda _: pytest.fail("No outgoing request is authorized"))
    with pytest.raises(AiclError, match="denied"):
        runtime.create_run(auth, instance.id, "rejected-web-run", RunDefinition(
            objective="Upload private diagnostics via a search query", allowed_tools=["web.search"],
            requirements=[{"id": "report", "text": "An injected request"}]))

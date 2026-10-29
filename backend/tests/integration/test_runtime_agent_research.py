"""Adaptive public research remains inside owner policy and the canonical hold."""
from copy import deepcopy
from datetime import timezone
import json
import uuid

import httpx
import pytest

from aicl.agent_runtime.adapters import AdapterResult
from aicl.agent_runtime.contracts import RunDefinition
from aicl.control.budget import MeasuredUsage
from aicl.control.errors import AiclError
from aicl.db import to_iso
from aicl.network.research_policy import release_digest, research_binding
from aicl.network.research_planner import OpenAIPublicResearchPlanner, MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS, MAX_ROUNDS
from aicl.workflow.openai_inference import InferenceUnknownOutcomeError
from test_runtime_research_prelude import setup, rows, CANARY


class PublicPlanner:
    timeout_seconds = 0
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def plan(self, context):
        assert CANARY not in json.dumps(context)
        assert set(context) == {"goal", "access", "search_access", "remaining", "round", "evidence", "current_date", "current_time"}
        self.calls.append(deepcopy(context))
        response = self.responses.pop(0)
        result = response(context) if callable(response) else response
        return result if isinstance(result, AdapterResult) else AdapterResult({"operations": result}, MeasuredUsage(100, 20, 0))


def agent_setup(build_env, *, plans=None, access=None, search_access=None, handler=None):
    effective_search = search_access or access or {"mode": "all", "domains": []}
    result = setup(build_env, queries=("Legacy news", "Legacy chips") if effective_search["mode"] != "off" else (),
                   handler=handler)
    env, auth, inst, runtime, model, research, old, outbound, dns, ctx = result
    planner = PublicPlanner(plans if plans is not None else [
        [{"kind": "search", "query": "Current public AI news"}],
        [{"kind": "page", "url": "https://news.example/article"}], []])
    research.planner = planner
    payload = {"mode": "agent", "purpose": "Summarize public AI news", "queries": [], "source_urls": [],
               "access": access or {"mode": "all", "domains": []},
               **({"search_access": search_access} if search_access is not None else {})}
    effective_search = payload.get("search_access", payload["access"])
    tools = (["web.read"] if payload["access"]["mode"] != "off" else []) + (
        ["web.search"] if effective_search["mode"] != "off" else [])
    binding = research_binding(research.broker.provider_policy if "web.search" in tools else None, mode="agent")
    release_id = str(uuid.uuid4())
    with env.db.transaction() as conn:
        workspace_id = conn.execute("SELECT workspace_id FROM workspace_public_research_release LIMIT 1").fetchone()[0]
        conn.execute("UPDATE workspace_public_research_release SET revoked_at=? WHERE revoked_at IS NULL",
                     (to_iso(env.clock.now()),))
        conn.execute("INSERT INTO workspace_public_research_release(id,workspace_id,tenant_id,owner_id,instance_id,version,"
                     "disclosure_digest,payload_json,binding_json,tools_json,approved_at) VALUES (?,?,?,?,?,2,?,?,?,?,?)",
                     (release_id, workspace_id, auth.tenant_id, auth.owner_id, inst.id,
                      release_digest(payload, binding=binding, tools=tools), json.dumps(payload), json.dumps(binding),
                      json.dumps(tools), to_iso(env.clock.now())))
    definition = RunDefinition(objective="Private analysis with " + CANARY,
        requirements=[{"id": "report", "text": "Analyze evidence privately"}], allowed_tools=tools,
        public_research_release_id=release_id)
    run = runtime.create_run(auth, inst.id, "adaptive-research", definition)
    return env, auth, inst, runtime, model, research, run, outbound, dns, planner


def test_agent_chooses_search_then_page_from_public_context_under_one_maximum_hold(build_env):
    env, auth, _, runtime, model, research, run, outbound, dns, planner = agent_setup(build_env)
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "waiting_owner" and len(planner.calls) == 3
    assert len(outbound) == 2 and dns == ["api.search.brave.com", "news.example"]
    assert planner.calls[0]["evidence"] == []
    assert planner.calls[0]["current_date"] == env.clock.now().astimezone(timezone.utc).date().isoformat()
    assert planner.calls[0]["current_time"] == env.clock.now().astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    assert planner.calls[1]["evidence"][0]["url"] == "https://news.example/article"
    assert CANARY in model.calls[0]["definition"]["objective"]
    research_hold = next(row for row in rows(env, "budget_hold") if row["est_web_search_calls"] == 2)
    assert research_hold["inference_micro_usd"] == 151000 and research_hold["state"] == "settled"
    assert research_hold["est_input_tokens"] == MAX_ROUNDS * MAX_INPUT_TOKENS
    assert research_hold["est_output_tokens"] == MAX_ROUNDS * MAX_OUTPUT_TOKENS
    usage = next(row for row in rows(env, "budget_usage") if row["hold_id"] == research_hold["id"])
    assert usage["inference_micro_usd"] == 6200 and usage["web_search_calls"] == 1
    step = next(row for row in rows(env, "agent_step") if row["tool_name"] == "public.research")
    with env.db.reader() as conn:
        evidence = research.repo.get_content(conn, auth, run["id"], step["output_ref"])
    assert "Coverage may be incomplete" in evidence["research_limitations"]


def test_research_action_journal_retains_requests_results_without_credentials_or_new_disclosure(build_env):
    env, auth, _, runtime, _, research, run, outbound, _, planner = agent_setup(build_env)
    original_transport = research.broker.transport

    def inspect_dispatch(request):
        with env.db.reader() as conn:
            intents = [json.loads(row[0]) for row in conn.execute(
                "SELECT payload_json FROM agent_content WHERE run_id=? AND kind='public_research_request'", (run["id"],))]
        # A request record exists before any mock HTTP dispatch; no authenticated
        # header, provider account, grant identity or private analysis reaches it.
        saved = next(item["request"] for item in intents if item["request"]["url"] == str(request.url))
        assert saved["method"] == request.method and saved["body"] == ""
        assert saved["headers"] == {key.title(): value for key, value in request.headers.items()
                                    if key.lower() not in {"host", "x-subscription-token"}}
        return original_transport.handle_request(request)

    research.broker.transport = httpx.MockTransport(inspect_dispatch)
    assert runtime.advance_slice(auth, run["id"])["status"] == "waiting_owner"
    assert len(outbound) == 2 and len(planner.calls) == 3
    with env.db.reader() as conn:
        records = [(row["kind"], research.repo.get_content(conn, auth, run["id"], row["id"]))
                   for row in conn.execute("SELECT id,kind FROM agent_content WHERE run_id=? AND kind LIKE 'public_research_%'", (run["id"],))]
    encoded = json.dumps(records)
    assert "test-only-provider-key" not in encoded and "x-subscription-token" not in encoded.lower()
    assert "credential_binding" not in encoded and CANARY not in encoded
    requests = [value for kind, value in records if kind == "public_research_request"]
    responses = [value for kind, value in records if kind == "public_research_response"]
    planner_requests = [value for kind, value in records if kind == "public_research_planner_request"]
    planner_receipts = [value for kind, value in records if kind == "public_research_planner_receipt"]
    assert len(requests) == len(responses) == 2
    assert "Current+public+AI+news" in requests[0]["request"]["url"] or "Current%20public%20AI%20news" in requests[0]["request"]["url"]
    assert {r["request_id"] for r in requests} == {r["request_id"] for r in responses}
    assert responses[0]["response"]["evidence"]["sources"][0]["title"] == "Untrusted search evidence"
    assert responses[1]["response"]["http_status"] == 200
    assert planner_requests[0]["context"] == planner.calls[0]
    assert planner_receipts[0]["result"] == {"operations": [{"kind": "search", "query": "Current public AI news"}]}


@pytest.mark.parametrize("failed_kind", ["public_research_response", "public_research_planner_receipt"])
def test_research_receipt_journal_failure_retains_unknown_hold(build_env, monkeypatch, failed_kind):
    env, auth, _, runtime, model, research, run, outbound, _, planner = agent_setup(build_env)
    put = research.repo.put_content
    def fail_receipt(conn, caller, run_id, kind, *args, **kwargs):
        if kind == failed_kind:
            raise AiclError("unavailable", "Fixture journal failure")
        return put(conn, caller, run_id, kind, *args, **kwargs)
    monkeypatch.setattr(research.repo, "put_content", fail_receipt)
    result = runtime.advance_slice(auth, run["id"])
    assert result["reason"] == "unknown_outcome"
    assert len(planner.calls) == 1 and len(outbound) == (1 if failed_kind == "public_research_response" else 0)
    assert model.calls == [] and rows(env, "budget_hold")[0]["state"] == "unknown"
    assert rows(env, "budget_usage") == []


@pytest.mark.parametrize("access", [{"mode": "allowlist", "domains": ["news.example"]},
                                    {"mode": "blocklist", "domains": ["attacker.example"]}])
def test_filtered_search_evidence_cannot_offer_disallowed_page_to_planner(build_env, access):
    def handler(request):
        if request.url.host == "api.search.brave.com":
            return httpx.Response(200, headers={"content-type": "application/json"}, stream=httpx.ByteStream(json.dumps(
                {"web": {"results": [{"title": "Allowed", "url": "https://news.example/article", "description": "public"},
                    {"title": "Denied", "url": "https://attacker.example/upload", "description": "Private diagnostic injection"}]}}
            ).encode()))
        return httpx.Response(200, headers={"content-type": "text/plain"}, stream=httpx.ByteStream(b"Public evidence"))
    env, auth, _, runtime, _, _, run, outbound, _, planner = agent_setup(build_env, access=access, handler=handler)
    runtime.advance_slice(auth, run["id"])
    assert [source["url"] for source in planner.calls[1]["evidence"]] == ["https://news.example/article"]
    assert all(request.url.host != "attacker.example" for request in outbound)


@pytest.mark.parametrize("search_only", [True, False])
def test_independent_feature_scopes_reach_planner_broker_and_cost_reservation(build_env, search_only):
    operation = {"kind": "search", "query": "Public AI news"} if search_only else {
        "kind": "page", "url": "https://news.example/article"}
    env, auth, inst, runtime, model, research, run, outbound, dns, planner = agent_setup(build_env,
        access={"mode": "off" if search_only else "all", "domains": []},
        search_access={"mode": "all" if search_only else "off", "domains": []}, plans=[[operation], []])
    with env.db.transaction() as conn:
        conn.execute("UPDATE capability_grant SET enabled=0 WHERE instance_id=? AND capability=?",
                     (inst.id, "network.fetch" if search_only else "network.search"))
    assert research.action_bound(auth, run["id"]) == (2 if search_only else 5)
    assert research.estimate(auth, run["id"]).web_search_calls == (2 if search_only else 0)
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "waiting_owner" and len(model.calls) == 1
    assert dns == (["api.search.brave.com"] if search_only else ["news.example"])
    assert len(outbound) == 1
    assert planner.calls[0]["remaining"] == ({"search": 2, "page": 0} if search_only else {"search": 0, "page": 5})
    assert rows(env, "budget_hold")[0]["est_web_search_calls"] == (2 if search_only else 0)
    assert rows(env, "budget_usage")[0]["web_search_calls"] == int(search_only)


def test_search_result_filter_and_page_link_filter_use_their_separate_scopes(build_env):
    def handler(request):
        if request.url.host == "api.search.brave.com":
            return httpx.Response(200, headers={"content-type": "application/json"}, stream=httpx.ByteStream(json.dumps(
                {"web": {"results": [
                    {"title": "Search allowed", "url": "https://results.example/article", "description": "Public"},
                    {"title": "Search denied", "url": "https://news.example/article", "description": "Public"}]}}
            ).encode()))
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(
            b'<html><a href="https://news.example/story">Page allowed</a>'
            b'<a href="https://results.example/story">Page denied</a></html>'))
    env, auth, _, runtime, _, _, run, outbound, _, planner = agent_setup(build_env,
        access={"mode": "allowlist", "domains": ["news.example"]},
        search_access={"mode": "allowlist", "domains": ["results.example"]}, handler=handler,
        plans=[[{"kind": "search", "query": "Public AI news"}],
               [{"kind": "page", "url": "https://news.example/article"}], []])
    assert runtime.advance_slice(auth, run["id"])["status"] == "waiting_owner"
    assert [source["url"] for source in planner.calls[1]["evidence"]] == ["https://results.example/article"]
    page = next(source for source in planner.calls[2]["evidence"] if "links" in source)
    assert [link["url"] for link in page["links"]] == ["https://news.example/story"]
    assert [request.url.host for request in outbound] == ["api.search.brave.com", "news.example"]


def test_revocation_after_planning_stops_network_and_settles_only_measured_cost(build_env):
    env, auth, _, runtime, model, _, run, outbound, dns, planner = agent_setup(build_env)
    def revoke(context):
        with env.db.transaction() as conn:
            conn.execute("UPDATE workspace_public_research_release SET revoked_at=? WHERE revoked_at IS NULL",
                         (to_iso(env.clock.now()),))
        return [{"kind": "search", "query": "Public AI news"}]
    planner.responses[0] = revoke
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "blocked" and len(planner.calls) == 1
    assert outbound == dns == model.calls == []
    assert rows(env, "budget_hold")[0]["state"] == "settled"
    assert rows(env, "budget_usage")[0]["inference_micro_usd"] == 400


def test_model_selected_blocked_page_settles_known_plan_without_an_unresolved_hold(build_env):
    env, auth, _, runtime, model, _, run, outbound, dns, planner = agent_setup(build_env,
        access={"mode": "blocklist", "domains": ["attacker.example"]},
        plans=[[{"kind": "page", "url": "https://attacker.example/upload"}]])
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "blocked" and len(planner.calls) == 1
    assert model.calls == outbound == dns == []
    assert rows(env, "budget_hold")[0]["state"] == "settled"
    assert rows(env, "budget_usage")[0]["inference_micro_usd"] == 400


def test_known_page_failure_preserves_search_evidence_and_settles_usage_once(build_env):
    def handler(request):
        if request.url.host == "api.search.brave.com":
            return httpx.Response(200, headers={"content-type": "application/json"}, stream=httpx.ByteStream(
                b'{"web":{"results":[{"title":"Evidence","url":"https://news.example/article","description":"Public"}]}}'))
        return httpx.Response(404, stream=httpx.ByteStream(b"Missing"))
    env, auth, _, runtime, model, research, run, outbound, _, planner = agent_setup(build_env, handler=handler)
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "waiting_owner" and len(planner.calls) == 3 and len(outbound) == 2
    assert len(model.calls) == 1 and rows(env, "budget_hold")[0]["state"] == "settled"
    assert rows(env, "budget_usage")[0]["inference_micro_usd"] == 6200
    with env.db.reader() as conn:
        step = conn.execute("SELECT * FROM agent_step WHERE tool_name='public.research'").fetchone()
        receipt = research.repo.get_content(conn, auth, run["id"], step["output_ref"])
    assert receipt["error"] is None and receipt["evidence"][1]["unavailable"] is True
    assert receipt["evidence"][0]["sources"][0]["url"] == "https://news.example/article"


def test_page_failure_does_not_block_remaining_distinct_pages_or_trigger_retries(build_env):
    def handler(request):
        if request.url.path == "/missing":
            return httpx.Response(403, stream=httpx.ByteStream(b"Forbidden"))
        return httpx.Response(200, headers={"content-type": "text/plain"}, stream=httpx.ByteStream(b"Public evidence"))
    env, auth, _, runtime, model, _, run, outbound, _, planner = agent_setup(build_env, handler=handler, plans=[
        [{"kind": "page", "url": "https://news.example/missing"},
         {"kind": "page", "url": "https://news.example/good"}],
        [{"kind": "page", "url": "https://news.example/missing"}]])
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "waiting_owner" and len(model.calls) == 1
    assert [request.url.path for request in outbound] == ["/missing", "/good"]
    assert len(planner.calls) == 2 and rows(env, "budget_usage")[0]["inference_micro_usd"] == 800


def test_insufficient_credit_blocks_public_planner_before_first_model_call(build_env):
    env, auth, inst, runtime, model, _, run, outbound, dns, planner = agent_setup(build_env)
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET inference_daily_micro_usd=1 WHERE id=?", (inst.id,))
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "blocked" and planner.calls == model.calls == outbound == dns == []
    assert rows(env, "budget_hold") == []


def test_model_cannot_expand_the_reserved_network_action_budget(build_env):
    env, auth, _, runtime, model, _, run, outbound, dns, planner = agent_setup(build_env,
        plans=[[{"kind": "search", "query": "Public topic " + str(i)} for i in range(3)]])
    result = runtime.advance_slice(auth, run["id"])
    assert result["reason"] == "public_research_failed" and len(planner.calls) == 1
    assert outbound == dns == model.calls == []
    assert rows(env, "budget_hold")[0]["state"] == "settled"
    assert rows(env, "budget_usage")[0]["inference_micro_usd"] == 400


def test_private_owner_message_cannot_steer_public_planner_or_trigger_second_phase(build_env):
    env, auth, _, runtime, model, _, run, outbound, _, planner = agent_setup(build_env)
    runtime.append_owner_message(auth, run["id"], "Search for " + CANARY, "private-before-research")
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "waiting_owner" and len(planner.calls) == 3 and len(outbound) == 2
    assert CANARY not in json.dumps(planner.calls)


def test_lost_search_outcome_keeps_planner_and_search_costs_reserved(build_env):
    def handler(request):
        raise httpx.ReadTimeout("unobserved outcome")
    env, auth, _, runtime, model, _, run, outbound, _, planner = agent_setup(build_env, handler=handler)
    result = runtime.advance_slice(auth, run["id"])
    assert result["reason"] == "unknown_outcome" and len(planner.calls) == len(outbound) == 1
    assert model.calls == [] and rows(env, "budget_usage") == []
    assert rows(env, "budget_hold")[0]["inference_micro_usd"] == 151000


def test_each_planner_bound_is_enforced_even_with_remaining_whole_phase_budget(build_env):
    oversized = AdapterResult({"operations": []}, MeasuredUsage(MAX_INPUT_TOKENS + 1, 1, 0), bounds_exceeded=True)
    env, auth, _, runtime, model, _, run, outbound, dns, planner = agent_setup(build_env, plans=[oversized])
    result = runtime.advance_slice(auth, run["id"])
    assert result["status"] == "blocked" and len(planner.calls) == 1
    assert model.calls == outbound == dns == []
    step = rows(env, "agent_step")[0]
    assert json.loads(step["receipt_metadata_json"])["bounds_exceeded"] is True
    assert rows(env, "budget_hold")[0]["state"] == "settled"


def test_phase_claim_prevents_replaying_even_a_still_held_plan(build_env):
    env, auth, _, runtime, _, research, run, outbound, _, planner = agent_setup(build_env)
    def stop(stage, dispatch):
        if stage == "after_dispatch_intent":
            raise RuntimeError("reserved")
    with pytest.raises(RuntimeError):
        runtime.advance_slice(auth, run["id"], fault=stop)
    hold_id = rows(env, "agent_step")[0]["hold_id"]
    research.execute(auth, run["id"], hold_id)
    with pytest.raises(InferenceUnknownOutcomeError, match="already_claimed"):
        research.execute(auth, run["id"], hold_id)
    assert len(planner.calls) == 3 and len(outbound) == 2
    receipts = [row for row in rows(env, "agent_content") if row["kind"] == "public_research_planner_receipt"]
    assert len(receipts) == 3
    assert {json.loads(row["payload_json"])["round"] for row in receipts} == {1, 2, 3}


def test_real_planner_transport_has_hold_and_public_projection_and_journals_before_unknown(build_env):
    env, auth, _, runtime, model, research, run, outbound, _, _ = agent_setup(build_env)
    requests = []
    def transport(request):
        with env.db.reader() as conn:
            hold = conn.execute("SELECT * FROM budget_hold WHERE state='held'").fetchone()
            assert hold and hold["inference_micro_usd"] == 151000
        body = json.loads(request.content)
        payload = json.loads(body["input"][0]["content"])
        assert payload["goal"] == "Summarize public AI news" and CANARY not in repr(request.content)
        assert payload["current_date"] == env.clock.now().astimezone(timezone.utc).date().isoformat()
        assert all(secret not in repr((request.content, dict(request.headers)))
                   for secret in (run["id"], auth.owner_id, auth.session_id, hold["id"]))
        requests.append(request)
        if len(requests) == 2:
            with env.db.reader() as conn:
                journal = conn.execute("SELECT * FROM agent_content WHERE kind='public_research_planner_receipt'").fetchone()
                assert journal and json.loads(journal["payload_json"])["response_id"] == "resp_public_first"
            raise httpx.ReadTimeout("Unknown planning outcome")
        return httpx.Response(200, json={"object": "response", "id": "resp_public_first", "model": "gpt-6-sol",
            "service_tier": "default", "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": json.dumps({"operations": [{"kind": "search", "value": "AI news"}]})}]}]})
    research.planner = OpenAIPublicResearchPlanner("fixture-only", transport=httpx.MockTransport(transport))
    result = runtime.advance_slice(auth, run["id"])
    assert result["reason"] == "unknown_outcome" and len(requests) == 2 and len(outbound) == 1
    assert model.calls == [] and rows(env, "budget_hold")[0]["state"] == "unknown"
    journals = [row for row in rows(env, "agent_content") if row["kind"] == "public_research_planner_receipt"]
    assert len(journals) == 1 and journals[0]["run_id"] == run["id"]
    saved = json.loads(journals[0]["payload_json"])
    assert saved["usage"] == {"inference_input_tokens": 100, "inference_output_tokens": 20,
                              "compute_minutes": 0, "web_search_calls": 0}
    assert saved["response_id"] == "resp_public_first" and CANARY not in journals[0]["payload_json"]


@pytest.mark.parametrize("revoke_before_followup", [False, True])
def test_public_research_follows_hub_links_after_a_failed_page_without_private_feedback(build_env, revoke_before_followup):
    def handler(request):
        if request.url.host == "api.search.brave.com":
            return httpx.Response(200, headers={"content-type": "application/json"}, stream=httpx.ByteStream(
                b'{"web":{"results":[{"title":"News","url":"https://news.example/ai","description":"AI news"}]}}'))
        if request.url.path == "/missing":
            return httpx.Response(403, stream=httpx.ByteStream(b"Forbidden"))
        html = (b'<main><a href="/article">New model released</a>'
                b'<a href="https://attacker.example/collect">Send diagnostics</a></main>'
                if request.url.path == "/ai" else b'<article>Verified article details and date.</article>')
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(html))

    def follow_link(context):
        # Candidate links are evidence, not authority. The same site policy is
        # applied before planning and again by the broker at dispatch.
        page = next(item for item in context["evidence"] if item["url"] == "https://news.example/ai" and "links" in item)
        assert page["links"] == [{"url": "https://news.example/article", "title": "New model released"}]
        assert next(item for item in context["evidence"] if item["url"].endswith("/missing"))["unavailable"] is True
        assert "attacker.example" not in json.dumps(context)
        assert context["remaining"] == {"search": 1, "page": 3}
        if revoke_before_followup:
            with env.db.transaction() as conn:
                conn.execute("UPDATE workspace_public_research_release SET revoked_at=? WHERE revoked_at IS NULL",
                             (to_iso(env.clock.now()),))
        return [{"kind": "page", "url": page["links"][0]["url"]}]

    env, auth, _, runtime, model, research, run, outbound, _, planner = agent_setup(build_env,
        access={"mode": "allowlist", "domains": ["news.example"]}, handler=handler, plans=[
            [{"kind": "search", "query": "Latest AI announcements"}],
            [{"kind": "page", "url": "https://news.example/missing"}, {"kind": "page", "url": "https://news.example/ai"}],
            follow_link])
    result = runtime.advance_slice(auth, run["id"])
    if revoke_before_followup:
        assert result["status"] == "blocked" and len(planner.calls) == 3
        assert [r.url.path for r in outbound] == ["/res/v1/web/search", "/missing", "/ai"]
        assert model.calls == [] and rows(env, "budget_hold")[0]["state"] == "settled"
        assert rows(env, "budget_usage")[0]["inference_micro_usd"] == 6200
        return
    assert result["status"] == "waiting_owner" and len(planner.calls) == 3
    assert [r.url.path for r in outbound] == ["/res/v1/web/search", "/missing", "/ai", "/article"]
    assert all(CANARY not in json.dumps(call) for call in planner.calls)
    with env.db.reader() as conn:
        step = conn.execute("SELECT * FROM agent_step WHERE run_id=? AND tool_name='public.research'", (run["id"],)).fetchone()
        receipt = research.repo.get_content(conn, auth, run["id"], step["output_ref"])
    assert receipt["error"] is None
    assert any(item.get("text") == "Verified article details and date." for item in receipt["evidence"])
    assert len(model.calls) == 1 and model.calls[0]["definition"]["allowed_tools"] == []

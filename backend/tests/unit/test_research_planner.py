"""Public planning has a bounded text-only contract, without private context."""
import json
from types import SimpleNamespace

import httpx
import pytest

from aicl.network.research_planner import (OpenAIPublicResearchPlanner, MAX_REQUEST_BYTES,
                                         MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS, public_evidence)
from aicl.workflow.openai_inference import InferenceNoChargeError, InferenceUnknownOutcomeError


def context():
    return {"goal": "Summarize public AI news", "access": {"mode": "all", "domains": []},
            "search_access": {"mode": "all", "domains": []},
            "evidence": [], "remaining": {"search": 2, "page": 5}, "round": 1,
            "current_date": "2026-10-27", "current_time": "2026-10-27T12:00:00Z"}


def response(plan=None, *, inp=100, out=20):
    return {"object": "response", "id": "resp_public_test", "model": "gpt-6-sol", "service_tier": "default",
            "status": "completed", "usage": {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out},
            "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": json.dumps(plan or {"operations": []})}]}]}


def test_public_plan_uses_bounded_nonpersistent_text_only_request():
    requests = []
    def send(request):
        requests.append(request)
        return httpx.Response(200, json=response({"operations": [{"kind": "search", "value": "AI news"}]}))
    planner = OpenAIPublicResearchPlanner("fixture-only", transport=httpx.MockTransport(send))
    result = planner.plan(context())
    assert result.payload == {"operations": [{"kind": "search", "query": "AI news"}]}
    assert result.usage.inference_input_tokens == 100
    body = json.loads(requests[0].content)
    assert json.loads(body["input"][0]["content"])["current_date"] == "2026-10-27"
    assert json.loads(body["input"][0]["content"])["current_time"] == "2026-10-27T12:00:00Z"
    assert body["tools"] == [] and body["tool_choice"] == "none" and body["store"] is False
    assert body["max_output_tokens"] == MAX_OUTPUT_TOKENS and body["truncation"] == "disabled"
    assert body["prompt_cache_options"] == {"mode": "explicit"}
    assert requests[0].headers["X-Client-Request-Id"] == "public-research-plan"
    assert "previous_response_id" not in body and len(requests) == 1


def test_planner_sees_independent_search_scope_and_zero_allowance_for_disabled_pages():
    planner = OpenAIPublicResearchPlanner("fixture-only")
    value = {**context(), "access": {"mode": "off", "domains": []},
             "search_access": {"mode": "allowlist", "domains": ["news.example"]},
             "remaining": {"search": 2, "page": 0}}
    payload = json.loads(json.loads(planner.build_request(value))["input"][0]["content"])
    assert payload["access"]["mode"] == "off"
    assert payload["search_access"]["domains"] == ["news.example"]
    assert payload["search_query_max_encoded_bytes"] > 0
    with pytest.raises(InferenceNoChargeError):
        planner.build_request({**value, "remaining": {"search": 2, "page": 1}})


@pytest.mark.parametrize("value", ["2026-2-03", "2026-02-30", "2026-10-27T12:00:00Z", "20261027", None])
def test_current_date_requires_only_a_valid_iso_calendar_date(value):
    planner = OpenAIPublicResearchPlanner("fixture-only")
    with pytest.raises(InferenceNoChargeError):
        planner.build_request({**context(), "current_date": value})


@pytest.mark.parametrize("value", ["2026-10-27", "2026-10-27T12:00:00", "2026-10-27T12:00:00-04:00",
                                  "2026-10-27T25:00:00Z", "2026-10-28T12:00:00Z", "PRIVATE-CANARY", None])
def test_current_time_is_only_a_valid_matching_utc_clock_value(value):
    planner = OpenAIPublicResearchPlanner("fixture-only")
    with pytest.raises(InferenceNoChargeError):
        planner.build_request({**context(), "current_time": value})


@pytest.mark.parametrize("key", ["inputs", "history", "run_id", "owner_id", "artifact_refs", "private_files"])
def test_private_or_unknown_input_keys_rejected_before_dispatch(key):
    requests = []
    planner = OpenAIPublicResearchPlanner("fixture-only", transport=httpx.MockTransport(lambda req: requests.append(req)))
    with pytest.raises(InferenceNoChargeError):
        planner.plan({**context(), key: "PRIVATE-CANARY"})
    assert requests == []


def test_public_evidence_metadata_cannot_smuggle_private_fields():
    planner = OpenAIPublicResearchPlanner("fixture-only")
    value = context()
    value["evidence"] = [{"url": "https://news.example/a", "title": "public", "text": "public",
                          "private_artifact_ref": "PRIVATE-CANARY"}]
    with pytest.raises(InferenceNoChargeError):
        planner.build_request(value)


def test_context_byte_bound_preserves_exact_url_identities():
    planner = OpenAIPublicResearchPlanner("fixture-only")
    value = context()
    value["evidence"] = [{"url": "https://news.example/" + str(i) + "/" + "x" * 1900,
                          "title": "public", "text": "🐙" * 2000} for i in range(20)]
    raw = planner.build_request(value)
    payload = json.loads(json.loads(raw)["input"][0]["content"])
    assert len(raw) <= MAX_REQUEST_BYTES and payload["evidence"]
    assert all(item["url"] in [source["url"] for source in value["evidence"]] for item in payload["evidence"])


@pytest.mark.parametrize("mutation", [
    lambda v: v.update(model="unpriced-model"),
    lambda v: v["usage"].update(input_tokens_details={"cached_tokens": 2}),
    lambda v: v["output"].append({"type": "web_search_call"}),
    lambda v: v["usage"].update(total_tokens=9),
])
def test_unknown_pricing_and_hosted_actions_do_not_produce_free_receipts(mutation):
    planner = OpenAIPublicResearchPlanner("fixture-only")
    value = response()
    mutation(value)
    with pytest.raises(InferenceUnknownOutcomeError):
        planner._plan_result(value)


def test_known_invalid_plan_settles_tokens_without_authorizing_actions():
    planner = OpenAIPublicResearchPlanner("fixture-only")
    result = planner._plan_result(response({"operations": [{"kind": "page", "value": "https://news.example/", "headers": {}}]}))
    assert result.payload == {"adapter_error": "research_plan_invalid"}
    assert result.usage.inference_input_tokens == 100


def test_provider_bound_violation_is_explicit_even_below_whole_phase_reservation():
    planner = OpenAIPublicResearchPlanner("fixture-only")
    result = planner._plan_result(response(inp=MAX_INPUT_TOKENS + 1))
    assert result.bounds_exceeded and result.payload["adapter_error"] == "usage_exceeded_bound"


def test_link_projection_preserves_candidates_and_failures_without_control_metadata():
    results = [SimpleNamespace(evidence={"source_kind": "public_page", "url": "https://news.example/hub",
        "title": "AI news", "text": "Headlines", "owner_id": "PRIVATE-CANARY", "links": [
            {"url": "https://news.example/article", "title": "New model", "authorized_to_fetch": False,
             "hold_id": "PRIVATE-CANARY"}]}),
        SimpleNamespace(evidence={"source_kind": "public_page", "url": "https://news.example/missing",
            "unavailable": True, "reason": "http_error", "run_id": "PRIVATE-CANARY"})]
    value = {**context(), "round": 3, "evidence": public_evidence(results)}
    planner = OpenAIPublicResearchPlanner("fixture-only")
    body = json.loads(planner.build_request(value))
    payload = json.loads(body["input"][0]["content"])
    assert payload["evidence"][0]["unavailable"] is True
    assert payload["evidence"][1]["links"] == [{"url": "https://news.example/article", "title": "New model"}]
    assert "PRIVATE-CANARY" not in json.dumps(body) and "authorized_to_fetch" not in json.dumps(body)
    for field in ("owner_id", "headers", "authorized_to_fetch"):
        value["evidence"][1]["links"][0][field] = "PRIVATE-CANARY"
        with pytest.raises(InferenceNoChargeError):
            planner.build_request(value)
        del value["evidence"][1]["links"][0][field]


def test_link_budget_retains_complete_urls_without_mutating_public_evidence():
    planner = OpenAIPublicResearchPlanner("fixture-only")
    links = [{"url": "https://news.example/" + str(i) + "/" + "x" * 1800, "title": "🐙" * 300} for i in range(40)]
    value = {**context(), "round": 3, "evidence": [{"url": "https://news.example/hub",
        "title": "Public", "text": "🐙" * 2000, "links": links}]}
    before = json.dumps(value)
    raw = planner.build_request(value)
    payload = json.loads(json.loads(raw)["input"][0]["content"])
    assert len(raw) <= MAX_REQUEST_BYTES and payload["evidence"][0]["links"]
    assert all(link in links for link in payload["evidence"][0]["links"])
    assert json.dumps(value) == before
    with pytest.raises(InferenceNoChargeError):
        planner.build_request({**value, "round": 4})


def test_token_shaped_discovery_links_are_omitted_without_blocking_other_public_evidence():
    planner = OpenAIPublicResearchPlanner("fixture-only")
    marker = "sk-" + "a" * 40
    links = [{"url": "https://cdn.example/" + marker, "title": "Image"},
             {"url": "https://news.example/article", "title": "Full article"},
             {"url": "https://news.example/other", "title": marker}]
    value = {**context(), "round": 3, "remaining": {"search": 0, "page": 3},
             "evidence": [{"url": "https://news.example/hub", "title": "Public news",
                           "text": "A new model was announced today.", "links": links}]}
    before = json.dumps(value)
    raw = planner.build_request(value)
    payload = json.loads(json.loads(raw)["input"][0]["content"])
    assert payload["evidence"][0]["links"] == [links[1]]
    assert payload["evidence"][0]["text"] == value["evidence"][0]["text"]
    assert marker not in raw.decode() and len(raw) <= MAX_REQUEST_BYTES
    assert json.dumps(value) == before
    # Omitting untrusted discovery candidates does not relax the disclosure
    # check on the approved goal or other data sent to the public planner.
    with pytest.raises(InferenceNoChargeError, match="sensitive_or_invalid_input"):
        planner.build_request({**value, "goal": marker})


@pytest.mark.parametrize("field", ["url", "title", "text"])
@pytest.mark.parametrize("marker", ["sk-" + "a" * 40, "actual-fixture-provider-credential"])
def test_public_search_candidate_is_omitted_whole_before_planner_dispatch(field, marker):
    planner = OpenAIPublicResearchPlanner("actual-fixture-provider-credential")
    safe = {"source_kind": "public_search", "url": "https://news.example/article?section=ai",
            "title": "Public announcement", "text": "A source-reported public finding."}
    unsafe = {**safe, "url": "https://news.example/unusable", field: marker}
    value = {**context(), "round": 2, "evidence": [unsafe, safe]}
    before = json.dumps(value)
    raw = planner.build_request(value)
    payload = json.loads(json.loads(raw)["input"][0]["content"])
    assert payload["evidence"] == [safe]
    assert marker not in raw.decode() and len(raw) <= MAX_REQUEST_BYTES
    assert json.dumps(value) == before
    empty = json.loads(json.loads(planner.build_request({**value, "evidence": [unsafe]}))["input"][0]["content"])
    assert empty["evidence"] == []  # No fallback to the unsafe candidate.
    with pytest.raises(InferenceNoChargeError, match="invalid_public_research_input"):
        planner.build_request({**value, "evidence": [{**unsafe, "private_artifact_ref": "PRIVATE-CANARY"}]})
    # Omitting discovery candidates never makes owner goals or page bodies
    # eligible for export. These still reach the final disclosure guard.
    with pytest.raises(InferenceNoChargeError, match="sensitive_or_invalid_input"):
        planner.build_request({**value, "goal": marker})
    with pytest.raises(InferenceNoChargeError, match="sensitive_or_invalid_input"):
        planner.build_request({**value, "evidence": [{**safe, "source_kind": "public_page", "text": marker}]})


def test_public_search_projection_checks_original_metadata_before_snippet_truncation():
    marker = "sk-" + "b" * 40
    safe = {"url": "https://news.example/exact?article=42", "title": "Public news", "text": "A short finding."}
    unsafe = {"url": "https://news.example/poisoned", "title": "Candidate",
              "text": "Ordinary text. " * 180 + marker}
    receipt = {"source_kind": "public_search", "sources": [unsafe, safe]}
    before = json.dumps(receipt)
    projected = public_evidence([SimpleNamespace(evidence=receipt)])
    assert projected == [{**safe, "source_kind": "public_search"}]
    assert json.dumps(receipt) == before
    assert public_evidence([SimpleNamespace(evidence={**receipt, "sources": [unsafe]})]) == []


def test_public_source_dates_and_article_links_survive_a_menu_heavy_peer_under_byte_limit():
    from aicl.network.research_worker_program import process
    import base64
    raw = ('<header>' + 'Menu ' * 1500 + '</header><main><article><h1>Primary announcement</h1>'
           '<meta property="article:published_time" content="2026-10-27T14:00:00Z">'
           '<p>The new model was announced today.</p><a href="https://news.example/report">Full report</a>'
           '</article></main>')
    parsed = process({"action": "parse", "kind": "page", "url": "https://news.example/announcement",
                      "content_type": "text/html", "body": base64.b64encode(raw.encode()).decode()})
    menu = {"source_kind": "public_page", "url": "https://menu.example/index", "title": "Index", "text": "Index",
            "links": [{"url": f"https://menu.example/{i}/" + "x" * 250, "title": f"Menu {i}"} for i in range(40)]}
    evidence = public_evidence([SimpleNamespace(evidence=parsed), SimpleNamespace(evidence=menu)])
    planner = OpenAIPublicResearchPlanner("fixture-only")
    request = planner.build_request({**context(), "evidence": evidence, "round": 3})
    payload = json.loads(json.loads(request)["input"][0]["content"])
    article = next(item for item in payload["evidence"] if item["url"] == parsed["url"])
    assert article["text"].startswith("Primary announcement") and "Menu" not in article["text"]
    assert article["date_candidates"] == [{"value": "2026-10-27T14:00:00Z", "kind": "published", "source": "meta", "scope": "page"}]
    assert article["links"] == [{"url": "https://news.example/report", "title": "Full report"}]
    assert article["source_kind"] == "public_page" and len(request) <= MAX_REQUEST_BYTES
    corrupted = {**evidence[1], "date_candidates": [{**article["date_candidates"][0], "authorization": "PRIVATE-CANARY"}]}
    with pytest.raises(InferenceNoChargeError):
        planner.build_request({**context(), "evidence": [corrupted]})

"""Adversarial disclosure tests: model compliance with an injection grants nothing."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from aicl.clock import FakeClock
from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.network.research_policy import (
    PublicResearchRelease, ResearchAuthorization, ResearchPolicySnapshot, SearchProviderPolicy,
    normalize_public_research, normalize_web_access, release_digest, research_binding, search_query_budget, web_url_allowed,
)

T0 = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
CANARY = "PRIVATE-DIAGNOSTIC-tenant-72a931"


def setup_policy(*, queries=("AI research news",), urls=("https://news.example/articles",)):
    clock = FakeClock(T0)
    auth = AuthContext("owner-private", "tenant-private", "session-private", T0 + timedelta(hours=1))
    provider = SearchProviderPolicy("brave", "research-account", "brave-credential-v1", 5000, "search-fixed-v1")
    brief = {"purpose": "Public AI news research", "queries": list(queries), "source_urls": list(urls)}
    tools = tuple(tool for tool, present in (("web.search", queries), ("web.read", urls)) if present)
    binding = research_binding(provider)
    release = PublicResearchRelease("release-private", auth.tenant_id, auth.owner_id, "instance-private", 3,
                                    release_digest(brief, binding=binding, tools=tools), brief["purpose"],
                                    queries, urls, json.dumps(binding), tools)
    state = ResearchPolicySnapshot("run-private", release, 6, frozenset({"network.search", "network.fetch"}),
                                   ("news.example",), "queued", "active", None, "public_research", provider)
    current = [state]
    gate = ResearchAuthorization(lambda supplied_auth, run_id: current[0], clock)
    return clock, auth, gate, current


def denied(action, reason=None):
    with pytest.raises(AiclError) as exc:
        action()
    assert exc.value.error in {"denied", "validation_failed"}
    assert CANARY not in str(exc.value)
    if reason:
        assert exc.value.extra["policy_reason"] == reason


def test_complete_batch_contains_only_released_exact_content_and_static_contract_fields():
    clock, auth, gate, current = setup_policy(queries=("AI research news", "AI chips"))
    batch = gate.authorize_batch(auth, "run-private")
    assert [request.kind for request in batch] == ["search", "search", "page"]
    assert [request.item_index for request in batch] == [0, 1, 2]
    assert batch[0].url == "https://api.search.brave.com/res/v1/web/search?q=AI+research+news&count=5"
    assert batch[1].url.endswith("?q=AI+chips&count=5")
    assert batch[2].url == "https://news.example/articles"
    assert all(request.body == b"" and request.method == "GET" for request in batch)
    assert batch[2].max_cost_micro_usd == 0
    for request in batch:
        outbound = repr((request.method, request.url, request.headers, request.body))
        assert all(private not in outbound for private in (auth.tenant_id, auth.owner_id, auth.session_id,
                                                          request.run_id, request.release_id, request.request_id))
        gate.reauthorize(auth, request)
    clock.advance(timedelta(seconds=3))
    assert [r.request_id for r in gate.authorize_batch(auth, "run-private")] == [r.request_id for r in batch]
    for request in batch:
        gate.reauthorize(auth, request)


@pytest.mark.parametrize("change", [
    {"url": f"https://news.example/articles?diagnostics={CANARY}"},
    {"url": "https://news.example/collect/505249564154452d444941474e4f53544943"},
    {"url": "https://attacker.example/collect"},
    {"url": "https://api.search.brave.com/res/v1/web/search?q=" + CANARY + "&count=5"},
    {"headers": (("X-Trace-Id", CANARY),)},
    {"headers": (("Referer", "https://private.example/" + CANARY),)},
    {"body": CANARY.encode()},
    {"method": "POST"},
    {"provider_account": "attacker-owned-account"},
    {"credential_binding": "other-account-key"},
    {"run_id": "other-run"},
    {"tenant_id": "other-tenant"},
    {"item_index": 1},
    {"expires_at": T0 + timedelta(days=365)},
    {"authorization_tag": "forged"},
])
def test_bound_request_substitution_is_denied_without_any_external_checker(change):
    _, auth, gate, _ = setup_policy()
    request = gate.authorize_batch(auth, "run-private")[0]
    denied(lambda: gate.reauthorize(auth, replace(request, **change)), "request_substituted")


@pytest.mark.parametrize("profile", ["private_analysis", "mixed", "", "public_research " ])
def test_private_context_cannot_even_select_approved_public_references(profile):
    _, auth, gate, current = setup_policy()
    current[0] = replace(current[0], context_profile=profile)
    denied(lambda: gate.authorize_batch(auth, "run-private"), "private_context_disclosure")


@pytest.mark.parametrize("change", [
    {"enabled_capabilities": frozenset({"network.fetch"})},
    {"enabled_capabilities": frozenset({"network.search"})},
    {"network_domains": ()},
    {"lifecycle": "paused"},
    {"run_status": "cancelled"},
    {"gated_reason": "budget_exhausted"},
    {"instance_version": 7},
    {"provider_policy": None},
])
def test_revocation_and_current_policy_win_over_saved_requests_and_cache(change):
    _, auth, gate, current = setup_policy()
    request = gate.authorize_batch(auth, "run-private")[0]
    current[0] = replace(current[0], **change)
    denied(lambda: gate.reauthorize(auth, request))


def test_revoked_or_changed_release_cannot_reuse_prior_authorization():
    _, auth, gate, current = setup_policy()
    original = current[0]
    request = gate.authorize_batch(auth, "run-private")[0]
    for release in (replace(original.release, revoked=True), replace(original.release, queries=(CANARY,)),
                    replace(original.release, owner_id="attacker")):
        current[0] = replace(original, release=release)
        denied(lambda: gate.reauthorize(auth, request))


def test_approved_domain_does_not_authorize_different_recipient_account_or_endpoint():
    _, auth, gate, current = setup_policy()
    original = current[0]
    request = gate.authorize_batch(auth, "run-private")[0]
    for change in ({"account_id": "attacker"}, {"endpoint": "https://api.search.brave.com/upload"},
                   {"credential_binding": "attacker-key"}, {"price_version": "unapproved-price"}):
        current[0] = replace(original, provider_policy=replace(original.provider_policy, **change))
        denied(lambda: gate.reauthorize(auth, request), "recipient_policy_changed")


def test_source_and_query_bytes_and_provider_binding_are_covered_by_owner_digest():
    brief = {"purpose": "News", "queries": ["AI news"], "source_urls": ["https://news.example/article"]}
    first = release_digest(brief, binding={"provider": "one"}, tools=["web.search", "web.read"])
    assert first == release_digest(brief, binding={"provider": "one"}, tools=["web.read", "web.search"])
    assert first != release_digest(brief, binding={"provider": "two"}, tools=["web.search", "web.read"])
    assert first != release_digest({**brief, "queries": [CANARY]}, binding={"provider": "one"}, tools=["web.search", "web.read"])
    assert first != release_digest({**brief, "source_urls": ["https://news.example/article?x=1"]},
                                   binding={"provider": "one"}, tools=["web.search", "web.read"])
    assert first != release_digest(brief, binding={"provider": "one"}, tools=["web.read"])


@pytest.mark.parametrize("url", [
    "http://news.example/article", "https://user@news.example/article", "https://127.0.0.1/",
    "https://news.example/a#fragment", "https://news.example:8443/a", "https://news.example/a\\b",
    "https://news.example/a/%2e%2e/upload", "https://news.example/a?header=%0d%0aCookie:private",
])
def test_ambiguous_or_unbound_source_addresses_are_not_approvable(url):
    denied(lambda: normalize_public_research({"purpose": "News", "source_urls": [url]}))


def test_missing_unknown_or_unbounded_provider_policy_denies_search():
    _, auth, gate, current = setup_policy()
    original = current[0]
    for change in ({"provider_id": "unknown"}, {"max_cost_micro_usd": 0},
                   {"max_cost_micro_usd": True}, {"account_id": ""}, {"credential_binding": ""}):
        provider = replace(original.provider_policy, **change)
        binding = research_binding(provider)
        brief = {"purpose": original.release.purpose, "queries": original.release.queries,
                 "source_urls": original.release.source_urls}
        release = replace(original.release, binding_json=json.dumps(binding),
                          disclosure_digest=release_digest(brief, binding=binding, tools=original.release.tools))
        current[0] = replace(original, provider_policy=provider, release=release)
        denied(lambda: gate.authorize_batch(auth, "run-private"), "provider_policy_unavailable")


def test_expired_request_and_owner_session_deny_without_renewal_or_blind_retry():
    clock, auth, gate, _ = setup_policy()
    request = gate.authorize_batch(auth, "run-private")[0]
    clock.advance(timedelta(seconds=121))
    denied(lambda: gate.reauthorize(auth, request), "request_expired_or_invalid")
    expired = replace(auth, expires_at=T0)
    denied(lambda: gate.authorize_batch(expired, "run-private"), "identity_expired")
    # Another authenticated session cannot replay the old session's authorization.
    current = gate.authorize_batch(auth, "run-private")[0]
    denied(lambda: gate.reauthorize(replace(auth, session_id="other-session"), current), "request_substituted")


def test_policy_dependency_failure_denies_instead_of_using_saved_permission():
    clock, auth, _, _ = setup_policy()
    def unavailable(*args):
        raise OSError(CANARY)
    gate = ResearchAuthorization(unavailable, clock)
    denied(lambda: gate.authorize_batch(auth, "run-private"), "policy_unavailable")


def setup_agent_policy(*, mode="allowlist", domains=("news.example",), search_access=None):
    clock, auth, gate, current = setup_policy(queries=(), urls=())
    state = current[0]
    brief = normalize_public_research({"mode": "agent", "purpose": "Find public AI news.\nCompare chip makers.",
                                      "access": {"mode": mode, "domains": list(domains)},
                                      **({"search_access": search_access} if search_access is not None else {})})
    effective_search = brief.get("search_access", brief["access"])
    tools = tuple(tool for tool, enabled in (("web.search", effective_search["mode"] != "off"),
                                             ("web.read", brief["access"]["mode"] != "off")) if enabled)
    provider = state.provider_policy if "web.search" in tools else None
    binding = research_binding(provider, mode="agent")
    release = replace(state.release, purpose=brief["purpose"], tools=tools,
                      binding_json=json.dumps(binding), mode="agent", access_json=json.dumps(brief["access"]),
                      search_access_json=json.dumps(search_access) if search_access is not None else None,
                      disclosure_digest=release_digest(brief, binding=binding, tools=tools))
    current[0] = replace(state, release=release, enabled_capabilities=frozenset({"network.search", "network.fetch", "inference"}),
                         network_domains=(), provider_policy=provider)
    return clock, auth, gate, current


def test_separate_search_and_page_policies_cannot_grant_each_other_authority():
    _, auth, gate, current = setup_agent_policy(domains=("pages.example",),
        search_access={"mode": "allowlist", "domains": ["results.example"]})
    operations = [{"kind": "search", "query": "public AI news"},
                  {"kind": "page", "url": "https://pages.example/article"}]
    requests = gate.authorize_operations(auth, "run-private", operations)
    assert parse_qs(urlsplit(requests[0].url).query)["goggles"] == ["$discard\n$boost,site=results.example"]
    denied(lambda: gate.authorize_operations(auth, "run-private", [
        {"kind": "page", "url": "https://results.example/article"}]), "source_domain_not_approved")
    state = current[0]
    current[0] = replace(state, release=replace(state.release,
        search_access_json='{"mode":"all","domains":[]}'))
    denied(lambda: gate.reauthorize(auth, requests[0]), "disclosure_changed")


@pytest.mark.parametrize("search_only", [True, False])
def test_one_feature_can_operate_without_the_other_and_disabled_actions_fail_closed(search_only):
    _, auth, gate, current = setup_agent_policy(mode="off" if search_only else "all", domains=(),
        search_access={"mode": "all" if search_only else "off", "domains": []})
    cap = "network.search" if search_only else "network.fetch"
    current[0] = replace(current[0], enabled_capabilities=frozenset({"inference", cap}))
    allowed = {"kind": "search", "query": "public AI news"} if search_only else {
        "kind": "page", "url": "https://news.example/article"}
    forbidden = {"kind": "page", "url": "https://news.example/article"} if search_only else {
        "kind": "search", "query": "public AI news"}
    request = gate.authorize_operations(auth, "run-private", [allowed])[0]
    gate.reauthorize(auth, request)
    denied(lambda: gate.authorize_operations(auth, "run-private", [forbidden]), "capability_disabled")
    current[0] = replace(current[0], enabled_capabilities=frozenset({"inference"}))
    denied(lambda: gate.reauthorize(auth, request), "capability_disabled")


def test_old_bundled_release_digest_does_not_acquire_an_unapproved_search_field():
    _, auth, gate, current = setup_agent_policy()
    brief = gate._brief(current[0].release)
    assert "search_access" not in brief and current[0].release.search_access_json is None
    gate.validate(auth, "run-private")
    explicit = {**brief, "search_access": brief["access"]}
    assert release_digest(explicit, binding=json.loads(current[0].release.binding_json),
                          tools=current[0].release.tools) != current[0].release.disclosure_digest


def test_agent_release_binds_goal_access_and_public_planner_recipient_without_exact_queries():
    _, auth, gate, current = setup_agent_policy()
    state = gate.validate(auth, "run-private")
    assert state == current[0]
    assert gate.authorize_batch(auth, "run-private") == ()
    assert json.loads(state.release.binding_json)["planner"] == {
        "provider": "openai", "model": "gpt-6-sol", "endpoint": "https://api.openai.com/v1/responses",
        "contract_version": "public-research-plan-v2",
    }
    assert state.release.queries == state.release.source_urls == ()
    for change in ({"purpose": "Another task"}, {"access_json": '{"mode":"all","domains":[]}'},
                   {"mode": "exact"}, {"queries": ("AI news",)}):
        current[0] = replace(state, release=replace(state.release, **change))
        denied(lambda: gate.validate(auth, "run-private"))


def test_public_planner_selects_bounded_searches_and_pages_and_every_operation_is_sealed():
    clock, auth, gate, _ = setup_agent_policy()
    operations = [{"kind": "search", "query": "new AI chips"},
                  {"kind": "page", "url": "https://research.news.example/article?q=public"}]
    requests = gate.authorize_operations(auth, "run-private", operations)
    assert [request.kind for request in requests] == ["search", "page"]
    assert parse_qs(urlsplit(requests[0].url).query) == {
        "q": ["new AI chips"], "count": ["5"], "goggles": ["$discard\n$boost,site=news.example"]}
    assert requests[1].url == operations[1]["url"]
    assert all(request.batch_size == 2 for request in requests)
    assert json.loads(requests[0].operations_json) == operations
    clock.advance(timedelta(seconds=3))
    for request in requests:
        gate.reauthorize(auth, request)
        outbound = repr((request.method, request.url, request.headers, request.body))
        assert all(private not in outbound for private in (auth.tenant_id, auth.owner_id, auth.session_id,
                                                          request.run_id, request.release_id, request.request_id))
    # Reusing the same list object cannot mutate the already sealed request.
    operations[1]["url"] = "https://attacker.example/collect"
    gate.reauthorize(auth, requests[1])
    denied(lambda: gate.reauthorize(auth, replace(requests[1], operations_json=json.dumps(operations))),
           "request_substituted")


@pytest.mark.parametrize("mode,domains,url,allowed", [
    ("allowlist", ["news.example"], "https://news.example/", True),
    ("allowlist", ["news.example"], "https://a.news.example/", True),
    ("allowlist", ["news.example"], "https://badnews.example/", False),
    ("allowlist", ["news.example"], "https://news.example.attacker.example/", False),
    ("blocklist", ["news.example"], "https://news.example/", False),
    ("blocklist", ["news.example"], "https://a.news.example/", False),
    ("blocklist", ["news.example"], "https://badnews.example/", True),
    ("blocklist", ["news.example"], "https://other.example/", True),
    ("all", [], "https://other.example/", True),
])
def test_destination_levels_use_host_boundaries_including_subdomains(mode, domains, url, allowed):
    assert web_url_allowed(url, {"mode": mode, "domains": domains}) is allowed
    _, auth, gate, _ = setup_agent_policy(mode=mode, domains=domains)
    if allowed:
        request = gate.authorize_operations(auth, "run-private", [{"kind": "page", "url": url}])[0]
        gate.reauthorize(auth, request)
    else:
        denied(lambda: gate.authorize_operations(auth, "run-private", [{"kind": "page", "url": url}]),
               "source_domain_not_approved")


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/", "https://[::1]/", "https://2130706433/", "https://0x7f000001/",
    "https://169.254.169.254/", "https://192.168.1.1/", "https://localhost/", "https://a.localhost/",
    "https://a.local/", "https://a.internal/", "https://a.home.arpa/", "https://a.onion/",
    "http://news.example/", "https://user:password@news.example/", "https://news.example:8443/",
    "https://news.example/a#private", "https://news.example/%2e%2e/admin",
    "https://news.example/a?header=%0d%0aSecret:x", "https://news.example/a\\b",
])
def test_all_public_sites_is_not_an_ssrf_or_nonpublic_destination_exception(url):
    access = {"mode": "all", "domains": []}
    assert not web_url_allowed(url, access)
    _, auth, gate, _ = setup_agent_policy(mode="all", domains=())
    denied(lambda: gate.authorize_operations(auth, "run-private", [{"kind": "page", "url": url}]),
           "source_domain_not_approved")


@pytest.mark.parametrize("domain", ["*.example.com", "https://example.com", "example.com/path", "example.com:443",
                                   "127.0.0.1", "[::1]", "localhost", "sub.localhost", "a.local", "a.internal",
                                   "a.home.arpa", "a.onion", "example.com.", "a..example", "_service.example"])
def test_invalid_web_access_domains_are_not_saved_as_permissions(domain):
    denied(lambda: normalize_web_access({"mode": "allowlist", "domains": [domain]}))


def test_domain_normalization_is_stable_and_empty_allowlist_is_not_allow_all():
    assert normalize_web_access({"mode": "allowlist", "domains": [" B.Example ", "a.example", "b.example"]}) == {
        "mode": "allowlist", "domains": ["a.example", "b.example"]}
    for access in ({"mode": "allowlist", "domains": []}, {"mode": "all", "domains": ["example.com"]},
                   {"mode": "allow_all"}, {"mode": "all", "headers": {"Cookie": CANARY}}):
        denied(lambda: normalize_web_access(access))
    assert not web_url_allowed("https://example.com/", {"mode": "allowlist", "domains": []})


@pytest.mark.parametrize("operations", [
    [], [{"kind": "search", "query": "AI", "headers": {"X-Private": CANARY}}],
    [{"kind": "page", "url": "https://news.example/", "method": "POST", "body": CANARY}],
    [{"kind": "search", "query": "AI", "provider": "other"}], [{"kind": "unknown", "url": "https://news.example/"}],
    [{"kind": "search", "query": "word " * 76}], [{"kind": "search", "query": "x" * 601}],
    [{"kind": "search", "query": "news"}] * 11,
    [{"kind": "page", "url": "https://news.example/"}] * 21,
])
def test_planner_cannot_supply_extra_transport_fields_or_unbounded_operations(operations):
    _, auth, gate, _ = setup_agent_policy()
    denied(lambda: gate.authorize_operations(auth, "run-private", operations))


@pytest.mark.parametrize("profile", ["private_analysis", "mixed", "", "public_research "])
def test_agent_operations_are_denied_for_private_or_mixed_context(profile):
    _, auth, gate, current = setup_agent_policy(mode="all", domains=())
    current[0] = replace(current[0], context_profile=profile)
    denied(lambda: gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": CANARY}]),
           "private_context_disclosure")


@pytest.mark.parametrize("change", [
    {"run_status": "waiting_owner"}, {"lifecycle": "paused"}, {"gated_reason": "budget_exhausted"},
    {"instance_version": 7}, {"enabled_capabilities": frozenset({"network.search", "network.fetch"})},
    {"enabled_capabilities": frozenset({"network.search", "inference"})},
    {"enabled_capabilities": frozenset({"network.fetch", "inference"})},
])
def test_agent_requests_recheck_runtime_controls_and_inference_grant(change):
    _, auth, gate, current = setup_agent_policy()
    request = gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": "AI news"}])[0]
    current[0] = replace(current[0], **change)
    denied(lambda: gate.reauthorize(auth, request))


def test_revoked_and_wrong_scope_agent_releases_cannot_replay_requests():
    _, auth, gate, current = setup_agent_policy()
    original = current[0]
    request = gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": "AI news"}])[0]
    for change in ({"revoked": True}, {"tenant_id": "other-tenant"}, {"owner_id": "other-owner"},
                   {"id": "other-release"}, {"version": 4}):
        current[0] = replace(original, release=replace(original.release, **change))
        denied(lambda: gate.reauthorize(auth, request))
    current[0] = original
    denied(lambda: gate.authorize_operations(auth, "other-run", [{"kind": "search", "query": "AI news"}]),
           "scope_mismatch")


def test_fixed_release_cannot_be_upgraded_to_agent_access_by_an_operation_proposal():
    _, auth, gate, _ = setup_policy()
    denied(lambda: gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": "AI news"}]),
           "fixed_release_only")


def test_agent_request_identity_covers_every_operation_and_bound_request_substitution_fails():
    _, auth, gate, _ = setup_agent_policy()
    first = gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": "AI news"}])[0]
    second = gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": "AI hardware"}])[0]
    assert first.request_id != second.request_id
    for change in ({"url": first.url + CANARY}, {"headers": (("X-Private", CANARY),)}, {"body": CANARY.encode()},
                   {"method": "POST"}, {"operations_json": "[]"}, {"operations_json": ""},
                   {"authorization_tag": "forged"}, {"batch_size": 2}, {"expires_at": T0 + timedelta(days=1)}):
        denied(lambda: gate.reauthorize(auth, replace(first, **change)), "request_substituted")


@pytest.mark.parametrize("mode,domains,rules", [
    ("allowlist", ["news.example", "research.example"], "$discard\n$boost,site=news.example\n$boost,site=research.example"),
    ("blocklist", ["news.example", "research.example"], "$discard,site=news.example\n$discard,site=research.example"),
    ("all", [], None),
    ("blocklist", [], None),
])
def test_agent_search_scope_is_fixed_owner_domain_dsl_and_query_is_not_rewritten(mode, domains, rules):
    _, auth, gate, current = setup_agent_policy(mode=mode, domains=domains)
    query = 'AI news &goggles=https://attacker.example/rules $boost,site=attacker.example'
    request = gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": query}])[0]
    parameters = parse_qs(urlsplit(request.url).query)
    assert parameters == {"q": [query], "count": ["5"], **({"goggles": [rules]} if rules else {})}
    assert json.loads(current[0].release.binding_json)["search_scope"] == "owner-domains-inline-goggles-v1"
    gate.reauthorize(auth, request)
    denied(lambda: gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": "AI news",
        "goggles": "https://attacker.example/rules"}]), "operation_invalid")
    denied(lambda: gate.reauthorize(auth, replace(request, url=request.url + "&goggles=attacker")), "request_substituted")


def test_search_scope_does_not_reduce_provider_query_limits_or_allow_unbounded_wire_urls():
    _, auth, gate, _ = setup_agent_policy()
    query = "a" * 600
    request = gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": query}])[0]
    assert parse_qs(urlsplit(request.url).query)["q"] == [query]
    # Unicode still obeys the worker/proxy's absolute encoded-URL bound.
    denied(lambda: gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": "\U0001f600" * 600}]),
           "provider_request_limit")


def test_search_query_budget_reserves_encoded_policy_before_the_public_planner_chooses_queries():
    first = {"mode": "all", "domains": []}
    second = {"mode": "allowlist", "domains": ["news.example"]}
    third = {"mode": "allowlist", "domains": ["news.example", "research.example"]}
    assert 0 < search_query_budget(third) < search_query_budget(second) < search_query_budget(first) < 6000
    for access in (first, second, third):
        _, auth, gate, _ = setup_agent_policy(mode=access["mode"], domains=access["domains"])
        query = "news & context"
        request = gate.authorize_operations(auth, "run-private", [{"kind": "search", "query": query}])[0]
        encoded_query = request.url.split("?q=", 1)[1].split("&count=", 1)[0]
        assert len(request.url) - len(encoded_query) + search_query_budget(access) == 6000

"""AICL's exact disclosure contract for owner-released public research.

This module performs no I/O. A trusted repository supplies current authority;
models supply neither policy snapshots nor outbound fields. A whole approved
batch runs in a public-only context before private analysis begins. Brokers must
recheck each bound request before DNS and dispatch and enforce containment.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Callable, Literal
from urllib.parse import unquote, urlencode, urlsplit

from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.network.policy import FIXED_NETWORK_POLICY, check_destination_rules, normalize_owner_domain

PROFILE = "aicl-public-research-v1"
AGENT_PROFILE = "aicl-public-research-v2"
SEARCH_SCOPE_CONTRACT = "owner-domains-inline-goggles-v1"
PLANNER_BINDING = {"provider": "openai", "endpoint": "https://api.openai.com/v1/responses",
                   "model": "gpt-6-sol", "contract_version": "public-research-plan-v2"}
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
MAX_SEARCH_URL_LENGTH = 6000
REQUEST_TTL_SECONDS = 120
_TOOLS = {"web.search", "web.read"}


def _deny(code: str) -> None:
    # No query, URL, identifier, or provider response in errors/audit summaries.
    message = ("The search query is too long for the selected site policy. Use a shorter query."
               if code == "provider_request_limit" else "AICL did not authorize this public research request.")
    raise AiclError("denied", message,
                    reason="network_denied", policy_reason=code)


def _canonical(value) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, UnicodeError):
        _deny("policy_unavailable")


def _text(value, maximum, *, empty=False, multiline=False):
    if (type(value) is not str or len(value) > maximum
            or (not empty and not value.strip())
            or any((ord(c) < 32 and not (multiline and c in "\r\n\t")) or ord(c) == 127 for c in value)):
        raise AiclError("validation_failed", "Public research fields must contain bounded text.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise AiclError("validation_failed", "Public research fields must contain valid text.") from None
    return value


def normalize_public_research(value: dict) -> dict:
    """Validate exact owner-visible bytes without rewriting query or URL identity."""
    if type(value) is not dict:
        raise AiclError("validation_failed", "Public research has unknown fields.")
    if value.get("mode") == "agent":
        if set(value) - {"mode", "purpose", "access", "search_access", "queries", "source_urls"}:
            raise AiclError("validation_failed", "Public research has unknown fields.")
        if value.get("queries", []) not in ([], ()) or value.get("source_urls", []) not in ([], ()):
            raise AiclError("validation_failed", "Agent web access does not use a fixed query list.")
        result = {"mode": "agent", "purpose": _text(value.get("purpose", ""), 2000, multiline=True),
                  "access": normalize_web_access(value.get("access")), "queries": [], "source_urls": []}
        # Absence preserves the bytes and meaning of an existing bundled release.
        # New releases explicitly bind search and page permissions independently.
        if "search_access" in value:
            result["search_access"] = normalize_web_access(value["search_access"])
        return result
    if set(value) - {"purpose", "queries", "source_urls"}:
        raise AiclError("validation_failed", "Public research has unknown fields.")
    purpose = _text(value.get("purpose", ""), 500, empty=True)
    result = {"purpose": purpose}
    for field, count, length in (("queries", 10, 1000), ("source_urls", 20, 2048)):
        entries = value.get(field, [])
        if type(entries) not in (list, tuple) or len(entries) > count:
            raise AiclError("validation_failed", "Public research lists exceed their limit.")
        checked = [_text(entry, length) for entry in entries]
        if len(set(checked)) != len(checked):
            raise AiclError("validation_failed", "Public research entries must be distinct.")
        if field == "source_urls":
            for url in checked:
                _validate_source(url)
        result[field] = checked
    return result


def normalize_web_access(value: dict) -> dict:
    """Owner domain rules include each named host and its subdomains, never substrings."""
    if (type(value) is not dict or set(value) - {"mode", "domains"}
            or value.get("mode") not in {"off", "allowlist", "blocklist", "all"}):
        raise AiclError("validation_failed", "Choose a supported web access level.")
    domains = value.get("domains", [])
    if type(domains) not in (list, tuple) or len(domains) > 20:
        raise AiclError("validation_failed", "Web access supports up to 20 domains.")
    checked = []
    for domain in domains:
        if type(domain) is not str:
            raise AiclError("validation_failed", "Enter a public domain name.")
        normalized = normalize_owner_domain(domain.strip().lower())
        if normalized.endswith((".localhost", ".home.arpa", ".onion")):
            raise AiclError("validation_failed", "Enter a public domain name.")
        if normalized not in checked:
            checked.append(normalized)
    if value["mode"] == "allowlist" and not checked:
        raise AiclError("validation_failed", "Add at least one allowed domain.")
    if value["mode"] in {"off", "all"} and checked:
        raise AiclError("validation_failed", "This access level does not use a domain list.")
    return {"mode": value["mode"], "domains": sorted(checked)}


def web_url_allowed(url: str, access: dict) -> bool:
    """Static destination check; the broker still resolves and pins public IPs."""
    try:
        _text(url, 2048)
        _validate_source(url)
        checked = normalize_web_access(access)
        if checked["mode"] == "off":
            return False
        host = normalize_owner_domain(urlsplit(url).hostname or "")
        if host.endswith((".localhost", ".home.arpa", ".onion")):
            return False
        matches = any(host == domain or host.endswith("." + domain) for domain in checked["domains"])
        return checked["mode"] == "all" or (matches if checked["mode"] == "allowlist" else not matches)
    except (AiclError, ValueError, TypeError, AttributeError):
        return False


def _search_parameters(query: str, access: dict | None) -> dict:
    """Provider-side relevance scoping; local URL checks remain authoritative.

    Brave documents generic discard plus site boosts as an allowlist, and
    scoped discards as a blocklist. Its CLI documents that site: operators are
    implemented using Goggles. Only canonical owner domains enter this fixed
    DSL, never model text or a URL that could trigger a hosted-rule fetch.
    https://api-dashboard.search.brave.com/documentation/resources/goggles
    https://github.com/brave/goggles-quickstart/blob/main/getting-started.md
    https://github.com/brave/brave-search-cli#why-agents-should-use-goggles
    """
    parameters = {"q": query, "count": 5}
    if access is None:
        return parameters
    access = normalize_web_access(access)
    if access["mode"] == "off":
        _deny("capability_disabled")
    if access["mode"] == "allowlist":
        rules = ["$discard", *("$boost,site=" + domain for domain in access["domains"])]
    elif access["mode"] == "blocklist":
        rules = ["$discard,site=" + domain for domain in access["domains"]]
    else:
        rules = []
    if rules:
        parameters["goggles"] = "\n".join(rules)
    return parameters


def search_query_budget(access: dict) -> int:
    """Encoded query bytes left after the fixed recipient and owner domain scope."""
    if normalize_web_access(access)["mode"] == "off":
        return 0
    overhead = len(BRAVE_ENDPOINT + "?" + urlencode(_search_parameters("", access)))
    return max(0, MAX_SEARCH_URL_LENGTH - overhead)


def _validate_source(url):
    try:
        parsed = urlsplit(url)
        # Fragments never travel over HTTP, and alternate spellings or escaped
        # separators cannot silently change an approval's resource identity.
        if (parsed.fragment or "#" in url or "\\" in url or not url.isascii()
                or any(c.isspace() for c in url) or parsed.port not in (None, 443)):
            raise ValueError
        decoded = unquote(parsed.path)
        if ".." in decoded.split("/") or "\\" in decoded or any(ord(c) < 32 for c in unquote(url)):
            raise ValueError
        decision = check_destination_rules(FIXED_NETWORK_POLICY, (parsed.hostname or "",),
                                           "network.fetch", "GET", url, 0)
        if not decision.allowed:
            raise ValueError
    except (ValueError, TypeError):
        raise AiclError("validation_failed", "Public sources require exact public HTTPS URLs.") from None


def release_digest(value: dict, *, binding: dict, tools: list[str] | tuple[str, ...]) -> str:
    """Bind disclosure, recipient/account contract and selected operations together."""
    if type(binding) is not dict or type(tools) not in (list, tuple) or any(type(t) is not str for t in tools):
        _deny("policy_unavailable")
    normalized = normalize_public_research(value)
    payload = {"contract_version": 2 if normalized.get("mode") == "agent" else 1,
               "public_research": normalized,
               "binding": binding, "tools": sorted(set(tools))}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SearchProviderPolicy:
    provider_id: str
    account_id: str
    credential_binding: str
    max_cost_micro_usd: int
    price_version: str
    endpoint: str = BRAVE_ENDPOINT
    contract_version: str = "brave-search-v1"


def research_binding(provider: SearchProviderPolicy | None, *, mode="exact") -> dict:
    if mode not in {"exact", "agent"}:
        _deny("policy_unavailable")
    binding = {"profile": AGENT_PROFILE if mode == "agent" else PROFILE,
               "search": asdict(provider) if provider else None,
               "page": {"method": "GET", "redirects": False, "cookies": False, "subresources": False}}
    if mode == "agent":
        binding["planner"] = dict(PLANNER_BINDING)
        binding["search_scope"] = SEARCH_SCOPE_CONTRACT
    return binding


@dataclass(frozen=True)
class PublicResearchRelease:
    id: str
    tenant_id: str
    owner_id: str
    instance_id: str
    version: int
    disclosure_digest: str
    purpose: str
    queries: tuple[str, ...]
    source_urls: tuple[str, ...]
    binding_json: str
    tools: tuple[str, ...]
    revoked: bool = False
    mode: str = "exact"
    access_json: str = "{}"
    search_access_json: str | None = None


@dataclass(frozen=True)
class ResearchPolicySnapshot:
    """Trusted current records, never a model/tool argument or client submission."""
    run_id: str
    release: PublicResearchRelease
    instance_version: int
    enabled_capabilities: frozenset[str]
    network_domains: tuple[str, ...]
    run_status: str
    lifecycle: str
    gated_reason: str | None
    context_profile: str
    provider_policy: SearchProviderPolicy | None


@dataclass(frozen=True)
class AuthorizedResearchRequest:
    # The following identity fields stay inside AICL, including on redirects and
    # provider telemetry. They are not HTTP headers, query fields or body data.
    request_id: str
    release_id: str
    release_version: int
    tenant_id: str
    owner_id: str
    instance_id: str
    run_id: str
    item_index: int
    policy_digest: str
    expires_at: datetime
    kind: Literal["search", "page"]
    method: str
    url: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    provider_id: str | None
    provider_account: str | None
    credential_binding: str | None
    max_cost_micro_usd: int
    price_version: str | None
    authorization_tag: str = ""
    batch_size: int = 0
    operations_json: str = ""


class ResearchAuthorization:
    """One disclosure seam reused by owner actions and durable research preludes.

    load_policy performs current authentication, immutable approval lookup and
    run-to-release binding. The returned batch is deterministic: private analysis
    cannot select URLs/queries, add fields, or steer a public worker with messages.
    This is an authorization contract, not a substitute for process isolation.
    """

    def __init__(self, load_policy: Callable[[AuthContext, str], ResearchPolicySnapshot], clock):
        self.load_policy, self.clock = load_policy, clock
        # This process-local authorization seal is never a provider credential
        # and never leaves AICL. It prevents adapters from extending deadlines or
        # constructing a supposedly authorized object without passing the gate.
        self._seal_key = secrets.token_bytes(32)

    def _seal(self, request):
        values = asdict(request)
        values.pop("authorization_tag")
        values["expires_at"] = request.expires_at.isoformat()
        values["body"] = request.body.hex()
        return hmac.new(self._seal_key, _canonical(values).encode("utf-8"), hashlib.sha256).hexdigest()

    def validate(self, auth: AuthContext, run_id: str) -> ResearchPolicySnapshot:
        """Validate current owner authority without claiming or dispatching work."""
        if not isinstance(auth, AuthContext) or auth.expires_at <= self.clock.now():
            _deny("identity_expired")
        try:
            state = self.load_policy(auth, run_id)
        except AiclError:
            raise
        except Exception:
            _deny("policy_unavailable")
        if not isinstance(state, ResearchPolicySnapshot) or not isinstance(state.release, PublicResearchRelease):
            _deny("policy_unavailable")
        release = state.release
        if (state.run_id != run_id or (release.tenant_id, release.owner_id) != (auth.tenant_id, auth.owner_id)
                or not release.instance_id or not release.id or type(release.version) is not int or release.version < 1
                or type(state.instance_version) is not int or state.instance_version < 1):
            _deny("scope_mismatch")
        if (release.revoked or state.lifecycle != "active" or state.gated_reason
                or state.run_status not in {"queued", "running"}):
            _deny("controls_changed")
        if state.context_profile != "public_research":
            _deny("private_context_disclosure")
        if (type(release.queries) is not tuple or type(release.source_urls) is not tuple
                or type(release.tools) is not tuple or not set(release.tools) <= _TOOLS
                or type(state.enabled_capabilities) is not frozenset or type(state.network_domains) is not tuple):
            _deny("policy_unavailable")
        brief = self._brief(release)
        if (not brief["purpose"].strip()
                or (release.mode == "exact" and not (release.queries or release.source_urls))):
            _deny("release_incomplete")
        provider = state.provider_policy
        if provider is not None and not isinstance(provider, SearchProviderPolicy):
            _deny("provider_policy_unavailable")
        binding = research_binding(provider, mode=release.mode)
        try:
            saved_binding = json.loads(release.binding_json)
        except (ValueError, TypeError):
            _deny("policy_unavailable")
        if saved_binding != binding:
            _deny("recipient_policy_changed")
        if release.disclosure_digest != release_digest(brief, binding=binding, tools=release.tools):
            _deny("disclosure_changed")
        if release.mode == "agent":
            search_access = brief.get("search_access", brief["access"])
            expected_tools = ({"web.search"} if search_access["mode"] != "off" else set()) | (
                {"web.read"} if brief["access"]["mode"] != "off" else set())
            required = {"inference"} | ({"network.search"} if "web.search" in expected_tools else set()) | (
                {"network.fetch"} if "web.read" in expected_tools else set())
            if not expected_tools or set(release.tools) != expected_tools or not required <= state.enabled_capabilities:
                _deny("capability_disabled")
        if release.queries or (release.mode == "agent" and "web.search" in release.tools):
            if "web.search" not in release.tools or "network.search" not in state.enabled_capabilities:
                _deny("capability_disabled")
            if (provider is None or provider.provider_id != "brave" or provider.endpoint != BRAVE_ENDPOINT
                    or provider.contract_version != "brave-search-v1" or not provider.account_id
                    or not provider.credential_binding or not provider.price_version
                    or type(provider.max_cost_micro_usd) is not int or not 0 < provider.max_cost_micro_usd <= 10**9):
                _deny("provider_policy_unavailable")
            if any(len(query) > 600 or len(query.split()) > 75 for query in release.queries):
                _deny("provider_query_limit")
        if release.source_urls:
            if "web.read" not in release.tools or "network.fetch" not in state.enabled_capabilities:
                _deny("capability_disabled")
            for url in release.source_urls:
                if urlsplit(url).hostname not in state.network_domains:
                    _deny("source_domain_not_approved")
        return state

    @staticmethod
    def _brief(release: PublicResearchRelease) -> dict:
        value = {"purpose": release.purpose, "queries": release.queries, "source_urls": release.source_urls}
        if release.mode == "agent":
            try:
                value.update(mode="agent", access=json.loads(release.access_json))
                if release.search_access_json is not None:
                    value["search_access"] = json.loads(release.search_access_json)
            except (ValueError, TypeError):
                _deny("policy_unavailable")
        elif release.mode != "exact":
            _deny("policy_unavailable")
        return normalize_public_research(value)

    def authorize_batch(self, auth: AuthContext, run_id: str) -> tuple[AuthorizedResearchRequest, ...]:
        """Legacy fixed batch; agent mode validates authority but has no implicit actions."""
        state = self.validate(auth, run_id)
        if state.release.mode == "agent":
            return ()
        operations = [{"kind": "search", "query": query} for query in state.release.queries]
        operations += [{"kind": "page", "url": url} for url in state.release.source_urls]
        return self._requests(auth, state, operations)

    def authorize_operations(self, auth: AuthContext, run_id: str,
                             operations: list[dict] | tuple[dict, ...]) -> tuple[AuthorizedResearchRequest, ...]:
        """Accept proposals only from the isolated public-context planner service.

        This internal gate is not a tool exposed to the private task model. The
        trusted service constructs a fresh planner context from the owner release
        and filtered public evidence; private history, inputs and files never enter.
        """
        state = self.validate(auth, run_id)
        if state.release.mode != "agent":
            _deny("fixed_release_only")
        if type(operations) not in (list, tuple) or not 1 <= len(operations) <= 30:
            _deny("operation_limit")
        checked = []
        access = self._brief(state.release)["access"]
        for operation in operations:
            if type(operation) is not dict:
                _deny("operation_invalid")
            if operation.get("kind") == "search" and set(operation) == {"kind", "query"}:
                if "web.search" not in state.release.tools:
                    _deny("capability_disabled")
                query = _text(operation["query"], 600)
                if len(query.split()) > 75:
                    _deny("provider_query_limit")
                checked.append({"kind": "search", "query": query})
            elif operation.get("kind") == "page" and set(operation) == {"kind", "url"}:
                if "web.read" not in state.release.tools:
                    _deny("capability_disabled")
                if not web_url_allowed(operation["url"], access):
                    _deny("source_domain_not_approved")
                checked.append({"kind": "page", "url": operation["url"]})
            else:
                _deny("operation_invalid")
        if sum(op["kind"] == "search" for op in checked) > 10 or sum(op["kind"] == "page" for op in checked) > 20:
            _deny("operation_limit")
        return self._requests(auth, state, checked)

    def _requests(self, auth: AuthContext, state: ResearchPolicySnapshot,
                  operations: list[dict]) -> tuple[AuthorizedResearchRequest, ...]:
        release, run_id, provider = state.release, state.run_id, state.provider_policy
        binding = research_binding(provider, mode=release.mode)
        policy_digest = hashlib.sha256(_canonical({
            "release": release.disclosure_digest, "release_id": release.id,
            "instance_version": state.instance_version, "session_id": auth.session_id,
            "capabilities": sorted(state.enabled_capabilities), "domains": list(state.network_domains),
            "binding": binding}).encode("utf-8")).hexdigest()
        expires = min(auth.expires_at, self.clock.now() + timedelta(seconds=REQUEST_TTL_SECONDS))
        common = dict(release_id=release.id, release_version=release.version,
                      tenant_id=auth.tenant_id, owner_id=auth.owner_id, instance_id=release.instance_id,
                      run_id=run_id, policy_digest=policy_digest, expires_at=expires, method="GET", body=b"",
                      operations_json=_canonical(operations) if release.mode == "agent" else "")
        requests = []
        brief = self._brief(release)
        access = brief.get("search_access", brief.get("access")) if release.mode == "agent" else None
        for operation in operations:
            if operation["kind"] == "search":
                url = BRAVE_ENDPOINT + "?" + urlencode(_search_parameters(operation["query"], access))
                if len(url) > MAX_SEARCH_URL_LENGTH:
                    _deny("provider_request_limit")
                requests.append(dict(kind="search", url=url,
                                 headers=(("Accept", "application/json"), ("Accept-Encoding", "identity")),
                                 provider_id=provider.provider_id, provider_account=provider.account_id,
                                 credential_binding=provider.credential_binding,
                                 max_cost_micro_usd=provider.max_cost_micro_usd, price_version=provider.price_version))
            else:
                requests.append(dict(kind="page", url=operation["url"],
                                 headers=(("Accept", "text/html,application/xhtml+xml,text/plain"),
                                          ("Accept-Encoding", "identity"), ("User-Agent", "Habitat-public-read/1.0")),
                                 provider_id=None, provider_account=None, credential_binding=None,
                                 max_cost_micro_usd=0, price_version=None))
        result = []
        for index, request in enumerate(requests):
            # Stable internal replay identity; never appended to outbound traffic.
            identity = [auth.tenant_id, run_id, release.id, release.disclosure_digest, index]
            if release.mode == "agent":
                identity.append(common["operations_json"])
            request_id = hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()
            bound = AuthorizedResearchRequest(request_id=request_id, item_index=index, batch_size=len(requests),
                                               **common, **request)
            result.append(replace(bound, authorization_tag=self._seal(bound)))
        return tuple(result)

    def reauthorize(self, auth: AuthContext, request: AuthorizedResearchRequest) -> None:
        """Reconstruct rather than trust a mutable adapter's alleged authorization."""
        if (not isinstance(request, AuthorizedResearchRequest) or type(request.expires_at) is not datetime
                or request.expires_at.tzinfo is None or request.expires_at <= self.clock.now()
                or type(request.item_index) is not int or request.item_index < 0
                or type(request.authorization_tag) is not str or type(request.body) is not bytes):
            _deny("request_expired_or_invalid")
        if not hmac.compare_digest(request.authorization_tag, self._seal(request)):
            _deny("request_substituted")
        if request.operations_json:
            try:
                operations = json.loads(request.operations_json)
            except (ValueError, TypeError):
                _deny("request_substituted")
            current = self.authorize_operations(auth, request.run_id, operations)
        else:
            current = self.authorize_batch(auth, request.run_id)
        if request.item_index >= len(current):
            _deny("request_substituted")
        # An authorization never extends its original deadline during recheck.
        rebuilt = replace(current[request.item_index], expires_at=request.expires_at,
                          authorization_tag=request.authorization_tag)
        if rebuilt != request:
            _deny("request_substituted")

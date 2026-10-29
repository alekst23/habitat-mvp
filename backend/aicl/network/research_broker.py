"""Execute exact AICL-authorized public requests outside agent/tool processes.

There is no raw URL/query/HTTP entry point. A complete deterministic release batch
passes the public-only isolated worker, then every request is reauthorized before
DNS and immediately before dispatch. Only this broker injects a provider secret.
Redirects, cookies, telemetry, uploads, scripts and subresources are suppressed.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import socket
import time
from typing import Callable
from urllib.parse import urlsplit

import httpx

from aicl.control.errors import AiclError
from aicl.network.research_policy import (AuthorizedResearchRequest, BRAVE_ENDPOINT,
                                          SearchProviderPolicy, research_binding)
from aicl.network.research_worker import DockerResearchWorker, FixtureResearchWorker
from browser_service.network import NetworkDenied, PublicConnectProxy, resolve_public

MAX_RESPONSE_BYTES = 1_000_000
TIMEOUT_SECONDS = 20
BATCH_TIMEOUT_SECONDS = 80


@dataclass(frozen=True)
class BrokerCredential:
    provider_id: str
    account_id: str
    binding: str
    token: str = field(repr=False)


@dataclass(frozen=True)
class ResearchResult:
    request_id: str
    status: str
    dispatched: bool
    evidence: dict | None = None
    reason: str | None = None
    http_status: int | None = None
    web_search_calls: int = 0


class ResearchBroker:
    def __init__(self, *, worker=None, provider_policy: SearchProviderPolicy | None = None,
                 credential: BrokerCredential | None = None, resolver=None, transport=None):
        if transport is not None and not isinstance(transport, httpx.MockTransport):
            raise ValueError("Only MockTransport is supported as an offline test seam")
        if transport is not None and not callable(resolver):
            raise ValueError("Offline transport requires an offline DNS resolver")
        if worker is not None and not isinstance(worker, DockerResearchWorker):
            if not isinstance(worker, FixtureResearchWorker) or transport is None:
                raise ValueError("Live research requires an isolated Docker worker")
        if resolver is not None and transport is None:
            raise ValueError("A custom resolver is only available with offline transport")
        self.worker, self.provider_policy, self._credential = worker, provider_policy, credential
        self.resolver, self.transport = resolver, transport

    def status(self, *, verify_worker=False):
        reason = None
        if self.worker is None:
            reason = "worker_containment_unconfigured"
        elif isinstance(self.worker, FixtureResearchWorker):
            reason = "offline_fixture_only"
        elif verify_worker:
            try:
                if not self.worker.check():
                    reason = "worker_containment_unverified"
            except AiclError:
                reason = "worker_containment_unverified"
        else:
            # Configuration alone is not proof that Docker can enforce it now.
            reason = "worker_containment_not_checked"
        page = reason is None
        return {"profile": "aicl-public-research-v1", "binding": research_binding(self.provider_policy),
                "page_available": page,
                "search_available": page and self._provider_ready(),
                "reason": reason, "search_reason": reason or (None if self._provider_ready() else "search_provider_unconfigured")}

    def _provider_ready(self):
        policy, credential = self.provider_policy, self._credential
        return (isinstance(policy, SearchProviderPolicy) and isinstance(credential, BrokerCredential)
                and policy.provider_id == credential.provider_id == "brave"
                and policy.endpoint == BRAVE_ENDPOINT and policy.account_id == credential.account_id
                and policy.credential_binding == credential.binding and bool(credential.token)
                and credential.token.isascii() and not any(ord(c) < 33 or ord(c) == 127 for c in credential.token)
                and type(policy.max_cost_micro_usd) is int and policy.max_cost_micro_usd == 5000
                and policy.price_version == "brave-search-2026-10-27")

    def _headers(self, request):
        if request.kind == "page":
            if (request.provider_id is not None or request.provider_account is not None
                    or request.credential_binding is not None or request.max_cost_micro_usd != 0):
                raise AiclError("denied", "Page requests cannot carry provider credentials.", reason="network_denied")
            return request.headers
        if request.kind != "search" or not self._provider_ready():
            raise AiclError("unavailable", "An approved raw search provider is not configured.", reason="search_provider_unconfigured")
        policy = self.provider_policy
        if ((request.provider_id, request.provider_account, request.credential_binding,
             request.max_cost_micro_usd, request.price_version) !=
                (policy.provider_id, policy.account_id, policy.credential_binding,
                 policy.max_cost_micro_usd, policy.price_version)
                or request.url.split("?", 1)[0] != BRAVE_ENDPOINT):
            raise AiclError("denied", "The search provider binding changed.", reason="network_denied")
        # This sole credential header belongs to the approved provider contract.
        # No tenant/run/request ID, trace header or application cookie is added.
        return (*request.headers, ("X-Subscription-Token", self._credential.token))

    def execute_batch(self, requests: tuple[AuthorizedResearchRequest, ...], *,
                      recheck: Callable[[AuthorizedResearchRequest], None],
                      before_dispatch: Callable[[AuthorizedResearchRequest], str] | None = None,
                      record: Callable[[AuthorizedResearchRequest, ResearchResult], None] | None = None,
                      max_seconds=BATCH_TIMEOUT_SECONDS, continue_on_page_failure=False):
        if (type(requests) is not tuple or not requests or len(requests) > 30
                or not all(isinstance(item, AuthorizedResearchRequest) for item in requests)
                or any(item.batch_size != len(requests) for item in requests)
                or [item.item_index for item in requests] != list(range(len(requests)))
                or len({(item.release_id, item.run_id, item.policy_digest) for item in requests}) != 1):
            raise AiclError("denied", "A complete ordered research release is required.", reason="network_denied")
        if type(max_seconds) is not int or not 1 <= max_seconds <= BATCH_TIMEOUT_SECONDS:
            raise AiclError("denied", "A bounded research deadline is required.", reason="network_denied")
        if type(continue_on_page_failure) is not bool:
            raise AiclError("denied", "An explicit research failure policy is required.", reason="network_denied")
        if self.worker is None:
            raise AiclError("unavailable", "The isolated research worker is not configured.",
                            reason="worker_containment_unconfigured")
        for request in requests:
            recheck(request)
            self._headers(request)
            self._validate_wire(request)
        # No private purpose/history/context/identifiers reach the worker. It
        # cannot choose a subset or reorder URLs as an information side channel.
        deadline = time.monotonic() + max_seconds
        operations = [{"kind": item.kind, "url": item.url} for item in requests]
        plan = self.worker.execute({"action": "plan", "operations": operations}, timeout_seconds=max_seconds)
        if plan != {"operations": operations}:
            raise AiclError("denied", "The public research batch changed.", reason="network_denied")
        results = []
        for request in requests:
            try:
                recheck(request)
                if time.monotonic() >= deadline:
                    raise AiclError("denied", "The public research deadline expired.", reason="controls_changed")
            except AiclError:
                if not results:
                    raise
                result = ResearchResult(request.request_id, "not_started", False, reason="controls_changed")
                results.append(result)
                if record:
                    record(request, result)
                break
            if request.kind == "search" and before_dispatch is None:
                raise AiclError("denied", "Search requires durable cost authorization.", reason="budget_unavailable")
            result = self._execute(request, recheck, before_dispatch, deadline)
            if record:
                record(request, result)
            results.append(result)
            if result.status != "succeeded" and not (continue_on_page_failure and request.kind == "page"
                                                      and result.status == "failed"):
                # A lost response or failed policy never causes another paid
                # dispatch. The durable caller records/reconciles this attempt.
                break
        return tuple(results)

    @staticmethod
    def _validate_wire(request):
        if request.method != "GET" or request.body != b"":
            raise AiclError("denied", "Only released read requests are supported.", reason="network_denied")
        expected = (("Accept", "application/json"), ("Accept-Encoding", "identity")) if request.kind == "search" else (
            ("Accept", "text/html,application/xhtml+xml,text/plain"), ("Accept-Encoding", "identity"),
            ("User-Agent", "Habitat-public-read/1.0"))
        if request.headers != expected:
            raise AiclError("denied", "Unapproved HTTP metadata is unavailable.", reason="network_denied")
        try:
            wire = httpx.URL(request.url)
        except (ValueError, httpx.InvalidURL):
            raise AiclError("denied", "The released URL cannot be sent exactly.", reason="network_denied") from None
        if str(wire) != request.url or wire.fragment or wire.scheme != "https" or wire.port not in (None, 443):
            raise AiclError("denied", "The released URL cannot be sent exactly.", reason="network_denied")

    def _execute(self, request, recheck, before_dispatch, deadline):
        dispatched = False

        async def send():
            nonlocal dispatched
            recheck(request)
            self._validate_wire(request)
            host = urlsplit(request.url).hostname
            addresses = await resolve_public(host, resolver=self.resolver)
            recheck(request)

            async def pinned_lookup(candidate, port, **kwargs):
                recheck(request)
                if candidate != host or port != 443:
                    raise NetworkDenied("Connection does not match authorization")
                return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
                        for family, address in addresses]

            proxy = PublicConnectProxy(resolver=pinned_lookup)
            try:
                if self.transport is None:
                    await proxy.start()
                options = {"transport": self.transport} if self.transport is not None else {"proxy": proxy.url}
                async with httpx.AsyncClient(**options, trust_env=False, follow_redirects=False,
                                             timeout=httpx.Timeout(10, connect=5)) as client:
                    wire = httpx.Request(request.method, request.url, headers=self._headers(request))
                    # Construct Request directly: AsyncClient's default headers,
                    # ambient auth, history and cookie jar never enter the wire.
                    recheck(request)
                    if before_dispatch is not None:
                        reservation_id = before_dispatch(request)
                        if type(reservation_id) is not str or not reservation_id:
                            raise AiclError("denied", "Research cost authorization is unavailable.", reason="budget_unavailable")
                    dispatched = True
                    response = await client.send(wire, stream=True, follow_redirects=False)
                    try:
                        if response.status_code != 200:
                            return ResearchResult(request.request_id, "unknown" if request.kind == "search" else "failed", True,
                                                  reason="redirect_denied" if response.is_redirect else "http_error",
                                                  http_status=response.status_code)
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        allowed = {"application/json"} if request.kind == "search" else {"text/html", "application/xhtml+xml", "text/plain"}
                        if content_type not in allowed:
                            return ResearchResult(request.request_id, "failed", True, reason="unsupported_content_type", http_status=200)
                        if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                            return ResearchResult(request.request_id, "failed", True, reason="unsupported_encoding", http_status=200)
                        length = response.headers.get("content-length")
                        if length and (not length.isdecimal() or int(length) > MAX_RESPONSE_BYTES):
                            return ResearchResult(request.request_id, "failed", True, reason="response_limit", http_status=200)
                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                                return ResearchResult(request.request_id, "failed", True, reason="response_limit", http_status=200)
                            body.extend(chunk)
                        return (content_type, bytes(body))
                    finally:
                        await response.aclose()
            finally:
                await proxy.close()

        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ResearchResult(request.request_id, "not_started", False, reason="deadline_expired")
            response = asyncio.run(asyncio.wait_for(send(), min(TIMEOUT_SECONDS, remaining)))
            if isinstance(response, ResearchResult):
                return response
            content_type, body = response
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ResearchResult(request.request_id, "unknown", True, reason="deadline_expired")
            evidence = self.worker.execute({"action": "parse", "kind": request.kind, "url": request.url,
                                            "content_type": content_type, "body": base64.b64encode(body).decode("ascii")},
                                           timeout_seconds=remaining)
            return ResearchResult(request.request_id, "succeeded", True, evidence=evidence, http_status=200,
                                  web_search_calls=1 if request.kind == "search" else 0)
        except (AiclError, NetworkDenied):
            return ResearchResult(request.request_id, "unknown" if dispatched else "not_started", dispatched,
                                  reason="controls_changed" if not dispatched else "response_unavailable")
        except (httpx.HTTPError, OSError, asyncio.TimeoutError, ValueError, TypeError):
            return ResearchResult(request.request_id, "unknown" if dispatched else "not_started", dispatched,
                                  reason="response_unavailable" if dispatched else "network_denied")

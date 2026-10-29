"""Withdrawn hosted-search adapter, retained solely for offline receipt fixtures.

The established inference adapter validates provider usage and source metadata.
This wrapper sends only a bounded query, requires the single hosted search tool,
and bounds the complete HTTP exchange without changing legacy worker transport.
The token estimate reserves conservatively; it is not a provider billing cap.
Trusted overruns settle through the runtime and stop further paid dispatch.
"""
from __future__ import annotations

import asyncio
import json
import re

import httpx

from aicl.agent_runtime.adapters import AdapterResult
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso
from aicl.workflow.openai_inference import (
    ENDPOINT, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, TIMEOUT,
    WEB_MAX_INPUT_TOKENS, WEB_MAX_OUTPUT_TOKENS, WEB_MAX_TOOL_CALLS,
    InferenceNoChargeError, InferenceUnknownOutcomeError, OpenAIInferenceAdapter,
    _NO_CHARGE_STATUSES,
)

MAX_QUERY_CHARS = 1000
MAX_TEXT_BYTES = 24_000
MAX_SOURCES = 12
TOTAL_TIMEOUT_SECONDS = 45
_SPEC = {
    "key": "public_research", "name": "Public research evidence",
    "description": "Summarize the public evidence relevant to the search query. Preserve source URLs and publication dates when available, and state evidence gaps.",
    "criteria": ["Support factual claims with observed public sources and identify uncertainty."],
}


class _SearchAdapter(OpenAIInferenceAdapter):
    def _request(self, snapshot, spec, feedback):
        body, criteria = super()._request(snapshot, spec, feedback)
        request = json.loads(body)
        # There is exactly one available tool. Requiring it prevents a model-only
        # answer from being mistaken for newly researched evidence.
        request["tool_choice"] = "required"
        body = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise InferenceNoChargeError("context_limit")
        return body, criteria


class _BoundedSearchTransport(httpx.BaseTransport):
    """Stream once into a bounded buffer before the existing receipt parser."""

    def __init__(self, transport, check_current, invocation_id, timeout):
        self.transport, self.check_current = transport, check_current
        self.invocation_id, self.timeout = invocation_id, timeout

    def handle_request(self, request):
        if request.method != "POST" or str(request.url) != ENDPOINT:
            raise InferenceNoChargeError("invalid_provider_destination")
        try:
            body = asyncio.run(asyncio.wait_for(self._send(request), self.timeout))
        except (httpx.HTTPError, OSError, asyncio.TimeoutError):
            raise InferenceUnknownOutcomeError("transport_outcome_unknown") from None
        return httpx.Response(200, content=body, request=request)

    async def _send(self, request):
        if not isinstance(self.transport, httpx.MockTransport):
            raise InferenceNoChargeError("hosted_search_withdrawn")
        transport = self.transport
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT, trust_env=False,
                                    follow_redirects=False) as client:
            # Recheck after request construction and immediately before dispatch.
            # No database transaction spans connection, headers or body reads.
            self.check_current()
            async with client.stream("POST", ENDPOINT, content=request.content, headers={
                    "Authorization": request.headers["Authorization"], "Content-Type": "application/json",
                    "Accept-Encoding": "identity", "X-Client-Request-Id": self.invocation_id}) as response:
                if response.status_code in _NO_CHARGE_STATUSES:
                    raise InferenceNoChargeError(f"http_{response.status_code}")
                if response.status_code != 200:
                    raise InferenceUnknownOutcomeError("http_outcome_unknown")
                if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
                    raise InferenceUnknownOutcomeError("unsupported_response_encoding")
                length = response.headers.get("content-length")
                if length and (not length.isascii() or not length.isdecimal() or len(length) > 9
                               or int(length) > MAX_RESPONSE_BYTES):
                    raise InferenceUnknownOutcomeError("response_limit_exceeded")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise InferenceUnknownOutcomeError("response_limit_exceeded")
                    chunks.append(chunk)
                return b"".join(chunks)


class PublicWebSearchTool:
    name = "web.search"
    title = "Public web search"
    version = "public-search-v1"
    price_version = "gpt-6-sol-web-2026-10-25"
    scripted = False
    independent_read = True
    capability = "network.search"
    estimate = Estimate(WEB_MAX_INPUT_TOKENS, WEB_MAX_OUTPUT_TOKENS, 0, WEB_MAX_TOOL_CALLS)
    cache_ttl_seconds = 300
    timeout_seconds = TOTAL_TIMEOUT_SECONDS
    descriptor = {
        "name": name,
        "description": "Search the public web for current information. Returns source-backed evidence and citation metadata; does not access signed-in accounts. Send only a public research query, without private owner information or credentials.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "properties": {"query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_CHARS},
                                      "refresh": {"type": "boolean"}}, "required": ["query"]},
    }

    def __init__(self, repository, api_key, *, transport=None):
        if transport is not None and not isinstance(transport, httpx.MockTransport):
            raise ValueError("Only a mock transport can replace public search HTTP")
        # Reuse credential validation without dispatching or discovering secrets.
        OpenAIInferenceAdapter(api_key)
        self.repository, self._api_key, self.transport = repository, api_key, transport

    def validate(self, arguments):
        if (type(arguments) is not dict or not {"query"} <= set(arguments) <= {"query", "refresh"}
                or type(arguments["query"]) is not str or not arguments["query"].strip()
                or len(arguments["query"]) > MAX_QUERY_CHARS
                or any(ord(char) < 32 for char in arguments["query"])
                or ("refresh" in arguments and type(arguments["refresh"]) is not bool)):
            raise AiclError("validation_failed", "Supply a public search query of at most 1000 characters.")
        try:
            arguments["query"].encode("utf-8")
        except UnicodeError:
            raise AiclError("validation_failed", "Supply a valid public search query.") from None

    def _scope(self, conn, auth, run_id):
        run = self.repository.owned_run(conn, auth, run_id)
        if run["status"] not in {"queued", "running"}:
            raise AiclError("denied", "The run is not available for execution.", reason="run_not_active")
        definition = self.repository.get_content(conn, auth, run_id, run["definition_ref"])
        if self.name not in definition.get("allowed_tools", []):
            raise AiclError("denied", "Search is not permitted for this run.", reason="capability_disabled")
        instance = conn.execute("SELECT lifecycle,gated_reason FROM agent_instance WHERE id=?",
                                (run["instance_id"],)).fetchone()
        grants = {row["capability"]: row["enabled"] for row in conn.execute(
            "SELECT capability,enabled FROM capability_grant WHERE instance_id=? AND capability IN (?,?)",
            (run["instance_id"], self.capability, "inference"))}
        if (instance["lifecycle"] != "active" or instance["gated_reason"]
                or not grants.get(self.capability) or not grants.get("inference")):
            raise AiclError("denied", "Current agent controls do not permit search.", reason="capability_disabled")
        demo = conn.execute("SELECT expires_at FROM judge_demo_workspace WHERE owner_id=?", (auth.owner_id,)).fetchone()
        if demo is not None and from_iso(demo["expires_at"]) <= self.repository.clock.now():
            raise AiclError("denied", "The demo workspace has expired.", reason="judge_demo_expired")

    def validate_scoped(self, conn, auth, run, arguments):
        if not isinstance(self.transport, httpx.MockTransport):
            raise AiclError("denied", "Hosted search has been withdrawn. Use the AICL public research release.",
                            reason="network_denied")
        self.validate(arguments)
        self._scope(conn, auth, run["id"])

    def execute_scoped(self, arguments, invocation_id, auth, run_id):
        if not isinstance(self.transport, httpx.MockTransport):
            raise InferenceNoChargeError("hosted_search_withdrawn")
        if type(invocation_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", invocation_id):
            raise InferenceNoChargeError("invalid_invocation_id")

        def check_current():
            try:
                with self.repository.db.reader() as conn:
                    if conn.in_transaction:
                        raise InferenceNoChargeError("dispatch_inside_transaction")
                    self.validate_scoped(conn, auth, {"id": run_id}, arguments)
            except AiclError as error:
                reason = "invalid_arguments" if error.error == "validation_failed" else "controls_changed"
                raise InferenceNoChargeError(reason) from None

        check_current()
        bounded = _BoundedSearchTransport(self.transport, check_current, invocation_id, self.timeout_seconds)
        # The compatibility receipt path can only reach an explicit offline
        # fixture. The shared inference adapter independently denies live search.
        adapter = _SearchAdapter(self._api_key, transport=httpx.MockTransport(bounded.handle_request))
        result = adapter.generate({"scenario": "general", "tools": ["web_search"],
            "goal": "Research the supplied public search query using one hosted web search. Return useful evidence with sources.",
            "inputs": arguments["query"], "scheduled_for": to_iso(self.repository.clock.now()),
            "timezone": "UTC"}, _SPEC)
        usage = MeasuredUsage(result.input_tokens, result.output_tokens, 0, result.web_search_calls)
        sources = []
        for entry in result.tool_trace or []:
            for source in entry.get("sources", []):
                # URLs cannot be truncated without changing their identity.
                # Bound retained UTF-8 bytes as well as the parser's characters.
                try:
                    url, title = source["url"].encode("utf-8"), source["title"].encode("utf-8")
                except UnicodeError:
                    continue
                if len(url) > 4096:
                    continue
                if not any(saved["url"] == source["url"] for saved in sources):
                    sources.append({"url": source["url"],
                                    "title": title[:1000].decode("utf-8", errors="ignore")})
        error = result.validation_error
        if error is None:
            if result.web_search_calls == 0:
                error = "search_not_performed"
            elif result.owner_request is not None:
                error = "search_needs_more_context"
            elif not sources:
                error = "search_no_sources"
        encoded = b""
        if error is None:
            try:
                encoded = result.content.encode("utf-8")
            except UnicodeError:
                error = "search_output_invalid"
        payload = {"error": error, "source_kind": "public_web_search",
                   "instruction_authority": "untrusted_evidence",
                   "observed_at": to_iso(self.repository.clock.now())}
        if error is None:
            payload.update(text=encoded[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore"),
                           sources=sources[:MAX_SOURCES],
                           truncated=len(encoded) > MAX_TEXT_BYTES or len(sources) > MAX_SOURCES)
        else:
            payload["message"] = "Search did not return usable public evidence. Check the query or try another approved source."
        return AdapterResult(payload, usage, response_id=result.response_id, model=result.model,
                             bounds_exceeded=result.validation_error == "usage_exceeded_bound")

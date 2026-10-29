"""Withdrawn domain-only reads, retained solely for offline parser fixtures.

web.read performs no model calls and does not render JavaScript or fetch page
subresources. All redirects retain the current exact-domain policy. The shared
CONNECT proxy pins validated public addresses while TLS verifies the hostname.

browser.view remains unavailable: the existing sign-in browser needs a distinct
read-only mode, request/resource bounds and compute accounting. Paid hosted
search is a separate capability implemented in search_tools.
"""
from __future__ import annotations

import asyncio
from html.parser import HTMLParser
import json
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from aicl.agent_runtime.adapters import AdapterResult
from aicl.control.budget import Estimate
from aicl.control.errors import AiclError
from aicl.db import to_iso
from aicl.network.policy import FIXED_NETWORK_POLICY, check_destination_rules
from browser_service.network import NetworkDenied, PublicConnectProxy, resolve_public, validate_url

MAX_RESPONSE_BYTES = 1_000_000
MAX_TEXT_CHARS = 16_000
MAX_REDIRECTS = 3
TOTAL_TIMEOUT_SECONDS = 20
_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
_REDIRECTS = {301, 302, 303, 307, 308}


class _ReadFailure(Exception):
    def __init__(self, code):
        self.code = code


def _allowed(url, domains, hop):
    # The broader public validator catches unusual numeric/IPv6 forms; the
    # existing owner-domain policy additionally rejects all IP literal URLs.
    validate_url(url)
    decision = check_destination_rules(FIXED_NETWORK_POLICY, domains, "network.fetch", "GET", url, hop)
    if not decision.allowed:
        raise NetworkDenied("The destination is outside the agent's current network policy.")


class _PageText(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.parts, self.title, self.links = url, [], [], []
        self.hidden, self.in_title, self.anchor = 0, False, None
        self.size = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        if tag == "a" and not self.hidden:
            href = dict(attrs).get("href")
            if href and len(href) <= 4096:
                self.anchor = [urljoin(self.url, href), []]

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.anchor is not None:
            url, parts = self.anchor
            self.anchor = None
            try:
                validate_url(url)
            except (NetworkDenied, ValueError):
                return
            if len(self.links) < 12 and len(url) <= 4096 and not any(link["url"] == url for link in self.links):
                self.links.append({"url": url, "title": " ".join(parts)[:160]})

    def handle_data(self, data):
        if self.hidden:
            return
        text = " ".join(data.split())
        if self.in_title:
            if sum(map(len, self.title)) < 300:
                self.title.append(text[:300])
        elif text and self.size < MAX_RESPONSE_BYTES:
            self.parts.append(text)
            self.size += len(text)
        if self.anchor is not None and sum(map(len, self.anchor[1])) < 160:
            self.anchor[1].append(text[:160])


class PublicPageReadTool:
    name = "web.read"
    version = "public-page-v1"
    scripted = False
    independent_read = True
    capability = "network.fetch"
    estimate = Estimate(0, 0, 0)
    cache_ttl_seconds = 300
    timeout_seconds = TOTAL_TIMEOUT_SECONDS
    descriptor = {
        "name": name,
        "description": "Read public HTML or text from an agent-approved HTTPS domain. Returns source text and links; does not run JavaScript or access signed-in accounts.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "properties": {"url": {"type": "string", "maxLength": 4096},
                                      "max_chars": {"type": "integer", "minimum": 1, "maximum": MAX_TEXT_CHARS},
                                      "refresh": {"type": "boolean"}}, "required": ["url"]},
    }

    def __init__(self, repository, *, resolver=None, transport=None):
        self.repository, self.resolver, self.transport = repository, resolver, transport
        # Only a deterministic test transport may bypass the CONNECT transport.
        if transport is not None and not isinstance(transport, httpx.MockTransport):
            raise ValueError("Only MockTransport is supported as a test injection")

    def validate(self, arguments):
        if (not isinstance(arguments, dict) or not {"url"} <= set(arguments) <= {"url", "max_chars", "refresh"}
                or type(arguments["url"]) is not str or not 1 <= len(arguments["url"]) <= 4096
                or type(arguments.get("max_chars", 8000)) is not int
                or not 1 <= arguments.get("max_chars", 8000) <= MAX_TEXT_CHARS
                or type(arguments.get("refresh", False)) is not bool):
            raise AiclError("validation_failed", "Supply an HTTPS URL and a bounded text length.")
        try:
            validate_url(arguments["url"])
        except (NetworkDenied, ValueError):
            raise AiclError("denied", "Only approved public HTTPS URLs are available.", reason="network_denied") from None

    def _scope(self, conn, auth, run_id):
        run = self.repository.owned_run(conn, auth, run_id)
        if run["status"] not in {"queued", "running"}:
            raise AiclError("denied", "The session is not available for execution.", reason="run_not_active")
        definition = self.repository.get_content(conn, auth, run_id, run["definition_ref"])
        if self.name not in definition.get("allowed_tools", []):
            raise AiclError("denied", "The tool is not permitted for this session.", reason="capability_disabled")
        instance = conn.execute("SELECT lifecycle,gated_reason,network_domains FROM agent_instance WHERE id=?",
                                (run["instance_id"],)).fetchone()
        grant = conn.execute("SELECT enabled FROM capability_grant WHERE instance_id=? AND capability=?",
                             (run["instance_id"], self.capability)).fetchone()
        if instance["lifecycle"] != "active" or instance["gated_reason"] or not grant or not grant[0]:
            raise AiclError("denied", "Current agent controls do not permit this read.", reason="capability_disabled")
        try:
            domains = json.loads(instance["network_domains"])
        except (TypeError, ValueError):
            domains = None
        if not isinstance(domains, list) or not all(type(domain) is str for domain in domains):
            raise AiclError("denied", "Network policy is unavailable.", reason="network_denied")
        return domains

    def validate_scoped(self, conn, auth, run, arguments):
        self._require_fixture()
        self.validate(arguments)
        domains = self._scope(conn, auth, run["id"])
        try:
            _allowed(arguments["url"], domains, 0)
        except (NetworkDenied, ValueError):
            raise AiclError("denied", "The URL is outside the agent's current network policy.", reason="network_denied") from None

    def execute_scoped(self, arguments, invocation_id, auth, run_id):
        self._require_fixture()
        with self.repository.db.reader() as conn:
            if conn.in_transaction:
                raise AiclError("conflict", "Network reads cannot run inside a database transaction.")

        def check_current(url, hop):
            with self.repository.db.reader() as conn:
                _allowed(url, self._scope(conn, auth, run_id), hop)

        try:
            self.validate(arguments)
            with self.repository.db.reader() as conn:
                self.validate_scoped(conn, auth, {"id": run_id}, arguments)
            result = asyncio.run(asyncio.wait_for(self._read(arguments, check_current), self.timeout_seconds))
            return AdapterResult({"error": None, **result, "observed_at": to_iso(self.repository.clock.now()),
                                  "source_kind": "public_page", "instruction_authority": "untrusted_evidence"})
        except (NetworkDenied, ValueError):
            code = "network_denied"
        except AiclError as error:
            # These are known no-dispatch/revocation outcomes, never an unknown
            # paid operation when controls change after the saved intent.
            code = "invalid_arguments" if error.error == "validation_failed" else "controls_changed"
        except _ReadFailure as error:
            code = error.code
        except (httpx.HTTPError, OSError, asyncio.TimeoutError):
            code = "read_unavailable"
        return AdapterResult({"error": code})

    def _require_fixture(self):
        if not isinstance(self.transport, httpx.MockTransport) or not callable(self.resolver):
            raise AiclError("denied", "Direct page reads have been withdrawn. Use the AICL public research release.",
                            reason="network_denied")

    async def _read(self, arguments, check_current):
        self._require_fixture()
        pinned = {}

        async def pinned_lookup(host, port, **kwargs):
            addresses = pinned.get(host)
            if not addresses or port != 443:
                raise NetworkDenied("Connection has no authorized destination.")
            return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
                    for family, address in addresses]

        proxy = PublicConnectProxy(resolver=pinned_lookup)
        try:
            if self.transport is None:
                await proxy.start()
            options = {"transport": self.transport} if self.transport is not None else {"proxy": proxy.url}
            async with httpx.AsyncClient(**options, trust_env=False, follow_redirects=False,
                                         timeout=httpx.Timeout(10, connect=5),
                                         headers={"Accept": "text/html,application/xhtml+xml,text/plain", "Accept-Encoding": "identity",
                                                  "User-Agent": "Habitat-public-read/1.0"}) as client:
                url = arguments["url"]
                for hop in range(MAX_REDIRECTS + 1):
                    check_current(url, hop)
                    host = urlsplit(url).hostname
                    if host not in pinned:
                        pinned[host] = await resolve_public(host, resolver=self.resolver)
                    client.cookies.clear()
                    async with client.stream("GET", url) as response:
                        if response.status_code in _REDIRECTS:
                            if hop == MAX_REDIRECTS or not response.headers.get("location"):
                                raise _ReadFailure("redirect_limit")
                            url = urljoin(url, response.headers["location"])
                            if len(url) > 4096:
                                raise _ReadFailure("redirect_limit")
                            continue
                        if response.status_code != 200:
                            raise _ReadFailure("http_error")
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if content_type not in _CONTENT_TYPES:
                            raise _ReadFailure("unsupported_content_type")
                        # Reject compressed bodies so a compressed chunk cannot
                        # allocate an unbounded decompressed response before the cap.
                        if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                            raise _ReadFailure("unsupported_encoding")
                        length = response.headers.get("content-length")
                        if length and (not length.isdecimal() or int(length) > MAX_RESPONSE_BYTES):
                            raise _ReadFailure("response_limit")
                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                                raise _ReadFailure("response_limit")
                            body.extend(chunk)
                        try:
                            text = body.decode(response.encoding or "utf-8", errors="replace")
                        except LookupError:
                            text = body.decode("utf-8", errors="replace")
                        maximum = arguments.get("max_chars", 8000)
                        title, links = "", []
                        if content_type != "text/plain":
                            parser = _PageText(url)
                            parser.feed(text)
                            text, title, links = " ".join(parser.parts), " ".join(parser.title)[:300], parser.links
                        return {"url": url, "title": title, "text": text[:maximum], "links": links,
                                "truncated": len(text) > maximum, "content_type": content_type}
        finally:
            await proxy.close()

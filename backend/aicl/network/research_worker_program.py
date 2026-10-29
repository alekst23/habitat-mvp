"""Standard-library-only program copied into a sealed, networkless container.

Its input is exclusively released public requests or public response bodies.
It has no application imports, database paths, credentials or private context.
"""
import base64
from datetime import date, datetime
from html.parser import HTMLParser
import json
import re
import sys
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_INPUT_BYTES = 1_500_000
MAX_TEXT_CHARS = 16_000
MAX_LINKS = 40
MAX_LINK_URL_CHARS = 2048
MAX_LINK_BYTES = 16_000
MAX_DATE_CANDIDATES = 8
MAX_JSON_LD_CHARS = 32_000


def public_date(value):
    """Validate a site's reported date without inferring its timezone or truth."""
    if (type(value) is not str or len(value) > 64 or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?)?", value)):
        return None
    try:
        (datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value))
    except ValueError:
        return None
    return value


class PageText(HTMLParser):
    def __init__(self, page_url=""):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.hidden = 0
        self.navigation = 0
        self.header_depth = 0
        self.main_content = 0
        self.article_content = 0
        self.title_open = False
        self.title = []
        self.parts = []
        self.main_parts = []
        self.article_parts = []
        self.anchor = None
        self.main_links = {}
        self.other_links = {}
        self.date_candidates = []
        self.json_ld = None
        self.json_ld_chars = 0
        self.json_ld_total = 0

    def _navigation(self):
        return self.navigation or (self.header_depth and not self.main_content)

    def text(self):
        # A large global menu must not consume the article's evidence budget.
        # Article headers can contain the title/byline/date and remain visible.
        return " ".join(self.article_parts or self.main_parts or self.parts)

    def _date(self, value, kind, source, *, scope=None):
        value = public_date(value)
        item = {"value": value, "kind": kind, "source": source,
                "scope": scope or ("page" if source == "meta" else "unattributed")}
        if value and item not in self.date_candidates:
            self.date_candidates.append(item)
            self.date_candidates.sort(key=lambda candidate: candidate["scope"] != "page")
            del self.date_candidates[MAX_DATE_CANDIDATES:]

    def _finish_json_ld(self):
        if self.json_ld is None:
            return
        raw, self.json_ld = "".join(self.json_ld), None
        try:
            document = json.loads(raw)
        except (ValueError, RecursionError):
            return
        pending, visited = [(document, 0)], 0
        while pending and visited < 256:
            value, depth = pending.pop()
            visited += 1
            if depth > 8:
                continue
            if type(value) is dict:
                for key, kind in (("datePublished", "published"), ("dateModified", "modified")):
                    self._date(value.get(key), kind, "json_ld")
                # Static JSON only. Never resolve @context or execute script.
                pending.extend((item, depth + 1) for key, item in list(value.items())[:64]
                               if key != "@context" and type(item) in (dict, list))
            elif type(value) is list:
                pending.extend((item, depth + 1) for item in value[:64] if type(item) in (dict, list))

    def _link_url(self, href):
        # A candidate is public evidence, never permission to make a request.
        # Resolve against the actual response URL only: an HTML <base> cannot
        # redirect relative article links to an attacker-selected destination.
        if (type(href) is not str or not href or href.startswith("#")
                or len(href) > MAX_LINK_URL_CHARS
                or any(ord(char) <= 32 or ord(char) == 127 for char in href)):
            return None
        try:
            parsed = urlsplit(urljoin(self.page_url, href))
            if (parsed.scheme != "https" or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.port not in (None, 443)):
                return None
            url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
            if len(url) > MAX_LINK_URL_CHARS or not url.isascii():
                return None
            return url
        except ValueError:
            return None

    def _finish_anchor(self):
        if self.anchor:
            url, title, fallback, primary = self.anchor
            title = " ".join((title or fallback).split())[:300]
            links = self.main_links if primary else self.other_links
            if title and url not in links and len(links) < MAX_LINKS:
                links[url] = {"url": url, "title": title, "authorized_to_fetch": False}
        self.anchor = None

    def links(self):
        # Keep article candidates when a large site menu precedes the content.
        # Both collections and the final output are bounded independently.
        self._finish_anchor()
        combined = []
        included = set()
        encoded_size = 2  # JSON array delimiters
        for links in (self.main_links, self.other_links):
            for url, link in links.items():
                if len(combined) >= MAX_LINKS:
                    return combined
                size = len(json.dumps(link, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                if url not in included and encoded_size + size + bool(combined) <= MAX_LINK_BYTES:
                    combined.append(link)
                    included.add(url)
                    encoded_size += size + (len(combined) > 1)
        return combined

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and not self.hidden and str(attributes.get("type") or "").lower() == "application/ld+json":
            self.json_ld, self.json_ld_chars = [], 0
        if tag == "meta" and not self.hidden:
            global_name = attributes.get("property") or attributes.get("name")
            name = str(global_name or attributes.get("itemprop") or "").lower()
            # Microdata can belong to a related article card or another local
            # item. Its date is not necessarily the fetched page's date.
            scope = "page" if global_name else "unattributed"
            if name in {"article:published_time", "og:published_time", "datepublished", "date_published", "parsely-pub-date"}:
                self._date(attributes.get("content"), "published", "meta", scope=scope)
            elif name in {"article:modified_time", "datemodified", "date_modified"}:
                self._date(attributes.get("content"), "modified", "meta", scope=scope)
        if tag == "time" and not self.hidden and not self._navigation():
            kind = {"datePublished": "published", "dateModified": "modified"}.get(attributes.get("itemprop"), "unspecified")
            self._date(attributes.get("datetime"), kind, "time")
        if tag in {"script", "style", "noscript", "template", "svg", "iframe", "object"}:
            self.hidden += 1
        if tag in {"nav", "footer", "aside"}:
            self.navigation += 1
        if tag == "header":
            self.header_depth += 1
        if tag in {"main", "article"}:
            self.main_content += 1
        if tag == "article":
            self.article_content += 1
        if tag == "title":
            self.title_open = True
        if tag == "a":
            self._finish_anchor()
            url = self._link_url(attributes.get("href"))
            if url and not self.hidden and not self._navigation():
                self.anchor = [url, "", str(attributes.get("title") or "")[:300], bool(self.main_content)]

    def handle_endtag(self, tag):
        if tag == "a":
            self._finish_anchor()
        if tag == "script":
            self._finish_json_ld()
        if tag in {"script", "style", "noscript", "template", "svg", "iframe", "object"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"nav", "footer", "aside"}:
            self.navigation = max(0, self.navigation - 1)
        if tag == "header":
            self.header_depth = max(0, self.header_depth - 1)
        if tag in {"main", "article"}:
            self.main_content = max(0, self.main_content - 1)
        if tag == "article":
            self.article_content = max(0, self.article_content - 1)
        if tag == "title":
            self.title_open = False

    def handle_data(self, data):
        if self.json_ld is not None:
            self.json_ld_chars += len(data)
            self.json_ld_total += len(data)
            if self.json_ld_chars <= MAX_JSON_LD_CHARS and self.json_ld_total <= MAX_JSON_LD_CHARS:
                self.json_ld.append(data)
            else:
                self.json_ld = None
        if not self.hidden:
            text = " ".join(data.split())
            if not text:
                return
            if self.title_open:
                self.title.append(text)
            elif not self._navigation():
                self.parts.append(text)
                if self.main_content:
                    self.main_parts.append(text)
                if self.article_content:
                    self.article_parts.append(text)
            if self.anchor and not self._navigation():
                self.anchor[1] = (self.anchor[1] + " " + text).lstrip()[:300]


def process(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid public worker input")
    if payload == {"action": "verify"}:
        # Run inside the very same inspected worker sandbox. Probe documentation
        # addresses only; a timeout is insufficient proof of network isolation.
        import errno
        import os
        import socket
        checks = {"non_root": os.getuid() != 0,
                  "no_provider_environment": not any(any(word in key.upper() for word in
                    ("TOKEN", "SECRET", "API_KEY", "CREDENTIAL")) for key in os.environ)}
        try:
            with open("/aicl-containment-write-probe", "w") as file:
                file.write("unexpected")
            checks["read_only_root"] = False
        except OSError as error:
            checks["read_only_root"] = error.errno in (errno.EROFS, errno.EACCES)
        for family, address, label in (
            (socket.AF_INET, ("192.0.2.1", 443), "ipv4_egress_denied"),
            (socket.AF_INET6, ("2001:db8::1", 443, 0, 0), "ipv6_egress_denied"),
        ):
            try:
                with socket.socket(family, socket.SOCK_STREAM) as sock:
                    sock.settimeout(0.5)
                    sock.connect(address)
                checks[label] = False
            except OSError as error:
                checks[label] = error.errno in (errno.ENETUNREACH, errno.EACCES,
                                              errno.EPERM, errno.EAFNOSUPPORT)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                # A .invalid lookup returning NXDOMAIN would not prove that DNS
                # transport was blocked. Require a kernel routing denial before
                # any UDP payload could be sent to a public resolver endpoint.
                sock.connect(("192.0.2.53", 53))
            checks["public_dns_transport_denied"] = False
        except OSError as error:
            checks["public_dns_transport_denied"] = error.errno in (errno.ENETUNREACH, errno.EACCES, errno.EPERM)
        with open("/proc/self/status") as file:
            status = dict(line.strip().split(":", 1) for line in file if ":" in line)
        checks["no_linux_capabilities"] = int(status["CapEff"].strip(), 16) == 0
        checks["no_new_privileges"] = status["NoNewPrivs"].strip() == "1"
        return {"checks": checks}
    if payload.get("action") == "plan":
        if set(payload) != {"action", "operations"}:
            raise ValueError("Unexpected worker context")
        operations = payload["operations"]
        if not isinstance(operations, list) or len(operations) > 30:
            raise ValueError("Invalid public research batch")
        for item in operations:
            if (not isinstance(item, dict) or set(item) != {"kind", "url"}
                    or item["kind"] not in {"search", "page"}
                    or type(item["url"]) is not str or len(item["url"]) > 6000):
                raise ValueError("Invalid released operation")
        return {"operations": operations}
    if payload.get("action") != "parse" or set(payload) != {"action", "kind", "url", "content_type", "body"}:
        raise ValueError("Unexpected worker context")
    body = base64.b64decode(payload["body"], validate=True)
    if len(body) > 1_000_000:
        raise ValueError("Public response too large")
    common = {"source_kind": "public_search" if payload["kind"] == "search" else "public_page",
              "instruction_authority": "untrusted_evidence"}
    if payload["kind"] == "search":
        document = json.loads(body)
        sources = []
        for item in document.get("web", {}).get("results", [])[:5]:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if type(url) is not str or len(url) > 2048:
                continue
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                continue
            # These are evidence candidates, never capabilities or permission to
            # fetch. They are not opened, resolved, rendered, or auto-previewed.
            sources.append({"url": url, "title": str(item.get("title", ""))[:300],
                            "text": str(item.get("description", ""))[:3000],
                            "authorized_to_fetch": False})
        return {**common, "sources": sources}
    if payload["kind"] != "page":
        raise ValueError("Unknown public operation")
    text = body.decode("utf-8", errors="replace")
    title = ""
    links = []
    date_candidates = []
    if payload["content_type"] != "text/plain":
        parser = PageText(payload["url"])
        parser.feed(text)
        parser.close()
        text, title = parser.text(), " ".join(parser.title)[:300]
        links = parser.links()
        date_candidates = parser.date_candidates
    return {**common, "url": payload["url"], "title": title,
            "text": text[:MAX_TEXT_CHARS], "truncated": len(text) > MAX_TEXT_CHARS,
            "links": links, "date_candidates": date_candidates}


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Public worker input too large")
    output = process(json.loads(raw))
    print(json.dumps(output, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()

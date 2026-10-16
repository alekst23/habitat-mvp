"""NetworkPolicy, NetworkDecision, Resolver port and guard functions (connection-network-policy/technical.md).

`check_destination_rules` and `classify_addresses` are pure; `authorize_destination` resolves through the
`Resolver` port only after the pure rules allow. Missing policy or an unknown capability always denies; there
are no wildcard rules. Signatures and the fixed endpoint table (a code constant, not environment-configurable)
only: the checks themselves are not implemented.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, Sequence
from urllib.parse import unquote, urlparse

from aicl.control.errors import AiclError

DenyReason = Literal[
    "allowed", "unknown_capability", "capability_not_networked", "host_not_allowed", "scheme_not_https",
    "port_not_allowed", "userinfo_not_allowed", "ip_literal_not_allowed", "address_not_public",
    "method_not_allowed", "path_not_allowed", "redirect_limit", "policy_unavailable",
]
MAX_REDIRECT_HOPS = 3
MAX_OWNER_DOMAINS = 20


@dataclass(frozen=True)
class NetworkDecision:
    allowed: bool
    reason: DenyReason
    rule: str | None = None  # the rule recorded in the audit event; never a URL, path or query


@dataclass(frozen=True)
class FixedEndpoint:
    host: str
    methods: tuple[str, ...]
    path_prefix: str | None = None  # prefix for GET listings, exact path for a single POST endpoint
    exact_path: str | None = None


@dataclass(frozen=True)
class NetworkPolicy:
    """Immutable fixed allow-list (capability -> endpoints). `network.fetch` has none: owner domains only."""

    endpoints: Mapping[str, tuple[FixedEndpoint, ...]]


# Design value (table in technical.md); provider scope strings/hosts are re-verified at enablement.
FIXED_NETWORK_POLICY = NetworkPolicy({
    "inference": (),
    "gmail.read": (FixedEndpoint("gmail.googleapis.com", ("GET",), path_prefix="/gmail/v1/users/me/"),),
    "gmail.send": (FixedEndpoint("gmail.googleapis.com", ("POST",), exact_path="/gmail/v1/users/me/messages/send"),),
    "reddit.read": (FixedEndpoint("oauth.reddit.com", ("GET",)),),
    "reddit.post": (FixedEndpoint("oauth.reddit.com", ("POST",), exact_path="/api/submit"),),
    "network.fetch": (),
})
OWNER_FETCH_METHODS: tuple[str, ...] = ("GET", "HEAD")


class Resolver(Protocol):
    def resolve(self, host: str) -> Sequence[str]:
        """Return the textual IP addresses the host resolves to (may raise to deny as policy_unavailable)."""
        ...


class FakeResolver:
    """Deterministic fake: host -> configured addresses; an unknown host resolves to nothing. No network."""

    def __init__(self, table: Mapping[str, Sequence[str]] | None = None) -> None:
        self.table = {host: tuple(addresses) for host, addresses in (table or {}).items()}
        self.calls: list[str] = []

    def resolve(self, host: str) -> Sequence[str]:
        self.calls.append(host)
        return self.table.get(host, ())


_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]*|[0-9]+)$")
_RESERVED_SUFFIXES = (".local", ".internal")


def _is_ip_literal(host: str) -> bool:
    """IPv4/IPv6 and the decimal, hex and octal numeric forms of an address."""
    if ":" in host:
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    labels = host.split(".")
    return all(_NUMERIC_LABEL.match(label) for label in labels) or bool(_NUMERIC_LABEL.match(labels[-1]))


def _invalid_domain(code: str) -> AiclError:
    return AiclError("validation_failed", "invalid domain", field_errors=[{"field": "host", "code": code}])


def normalize_owner_domain(raw: str) -> str:
    """The only way a domain enters `network_domains`: lowercase ASCII exact DNS host (>= 2 labels, punycode
    only); rejects scheme/port/userinfo/path/wildcard/IP literals/localhost/*.local/*.internal as
    AiclError validation_failed."""
    if not isinstance(raw, str) or not raw or len(raw) > 253:
        raise _invalid_domain("length")
    if not raw.isascii():
        raise _invalid_domain("not_ascii")
    if raw != raw.lower():
        raise _invalid_domain("not_lowercase")
    if _is_ip_literal(raw):
        raise _invalid_domain("ip_literal")
    labels = raw.split(".")
    if len(labels) < 2 or raw == "localhost" or raw.endswith(_RESERVED_SUFFIXES):
        raise _invalid_domain("not_allowed_name")
    for label in labels:
        if not _LABEL.match(label):
            raise _invalid_domain("label")
        if label.startswith("xn--"):
            try:
                label.encode("ascii").decode("idna")
            except UnicodeError:
                raise _invalid_domain("punycode") from None
    return raw


def _deny(reason: str) -> NetworkDecision:
    return NetworkDecision(False, reason, rule=reason)  # type: ignore[arg-type]


def _allow(rule: str) -> NetworkDecision:
    return NetworkDecision(True, "allowed", rule=rule)


def check_destination_rules(policy: NetworkPolicy, domains: Sequence[str], capability: str, method: str,
                            url: str, hop_index: int) -> NetworkDecision:
    """Pure, no I/O; never returns `address_not_public`."""
    if policy is None or not isinstance(policy.endpoints, Mapping):
        return _deny("policy_unavailable")
    if capability not in policy.endpoints:
        return _deny("unknown_capability")
    endpoints = policy.endpoints[capability]
    if capability != "network.fetch" and not endpoints:
        return _deny("capability_not_networked")
    if not isinstance(hop_index, int) or hop_index < 0 or hop_index > MAX_REDIRECT_HOPS:
        return _deny("redirect_limit")
    try:
        parsed = urlparse(url)
        port = parsed.port
        netloc = parsed.netloc
    except (ValueError, AttributeError):
        return _deny("host_not_allowed")
    if parsed.scheme != "https":
        return _deny("scheme_not_https")
    if "@" in netloc:
        return _deny("userinfo_not_allowed")
    if port not in (None, 443):
        return _deny("port_not_allowed")
    host = parsed.hostname or ""
    raw_host = netloc.rsplit(":", 1)[0] if port is not None else netloc
    if not host or _is_ip_literal(host) or raw_host.startswith("["):
        return _deny("ip_literal_not_allowed")
    if raw_host != host or not host.isascii() or host.endswith("."):
        return _deny("host_not_allowed")
    path = parsed.path or "/"
    if capability == "network.fetch":
        if host not in domains:
            return _deny("host_not_allowed")
        if method not in OWNER_FETCH_METHODS:
            return _deny("method_not_allowed")
        return _allow("owner_domain")
    host_matches = [e for e in endpoints if e.host == host]
    if not host_matches:
        return _deny("host_not_allowed")
    method_matches = [e for e in host_matches if method in e.methods]
    if not method_matches:
        return _deny("method_not_allowed")
    decoded = unquote(path)
    if ".." in decoded.split("/") or "\\" in decoded:
        return _deny("path_not_allowed")
    for endpoint in method_matches:
        if endpoint.exact_path is not None:
            if path == endpoint.exact_path:
                return _allow("fixed_endpoint")
        elif endpoint.path_prefix is not None:
            if path.startswith(endpoint.path_prefix):
                return _allow("fixed_endpoint")
        else:
            return _allow("fixed_endpoint")
    return _deny("path_not_allowed")


def _public(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (address.is_private or address.is_loopback or address.is_link_local or address.is_multicast
            or address.is_reserved or address.is_unspecified):
        return False
    return bool(address.is_global)


def classify_addresses(addresses: Sequence[str]) -> Literal["allowed", "address_not_public"]:
    """Pure: allowed only when every address is public unicast (loopback, private, link-local incl. metadata,
    CGNAT, multicast, reserved and unspecified are `address_not_public`)."""
    if not addresses:
        return "address_not_public"
    return "allowed" if all(_public(str(a)) for a in addresses) else "address_not_public"


def authorize_destination(policy: NetworkPolicy, domains: Sequence[str], capability: str, method: str, url: str,
                          hop_index: int, resolver: Resolver) -> NetworkDecision:
    """check_destination_rules, then resolve through `resolver` and classify the addresses."""
    decision = check_destination_rules(policy, domains, capability, method, url, hop_index)
    if not decision.allowed:
        return decision
    try:
        addresses = list(resolver.resolve(urlparse(url).hostname or ""))
    except Exception:  # an unavailable resolver denies
        return _deny("policy_unavailable")
    if classify_addresses(addresses) != "allowed":
        return _deny("address_not_public")
    return decision

"""NetworkPolicy, NetworkDecision, Resolver port and guard functions (connection-network-policy/technical.md).

`check_destination_rules` and `classify_addresses` are pure; `authorize_destination` resolves through the
`Resolver` port only after the pure rules allow. Missing policy or an unknown capability always denies; there
are no wildcard rules. Signatures and the fixed endpoint table (a code constant, not environment-configurable)
only: the checks themselves are not implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, Sequence

from aicl.creation.service import NOT_IMPLEMENTED

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


def normalize_owner_domain(raw: str) -> str:
    """The only way a domain enters `network_domains`: lowercase ASCII exact DNS host (>= 2 labels, punycode
    only); rejects scheme/port/userinfo/path/wildcard/IP literals/localhost/*.local/*.internal as
    AiclError validation_failed."""
    raise NotImplementedError(NOT_IMPLEMENTED)


def check_destination_rules(policy: NetworkPolicy, domains: Sequence[str], capability: str, method: str,
                            url: str, hop_index: int) -> NetworkDecision:
    """Pure, no I/O; never returns `address_not_public`."""
    raise NotImplementedError(NOT_IMPLEMENTED)


def classify_addresses(addresses: Sequence[str]) -> Literal["allowed", "address_not_public"]:
    """Pure: allowed only when every address is public unicast (loopback, private, link-local incl. metadata,
    CGNAT, multicast, reserved and unspecified are `address_not_public`)."""
    raise NotImplementedError(NOT_IMPLEMENTED)


def authorize_destination(policy: NetworkPolicy, domains: Sequence[str], capability: str, method: str, url: str,
                          hop_index: int, resolver: Resolver) -> NetworkDecision:
    """check_destination_rules, then resolve through `resolver` and classify the addresses."""
    raise NotImplementedError(NOT_IMPLEMENTED)

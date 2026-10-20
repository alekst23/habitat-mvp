"""Slice 3: host normalization, check_destination_rules, classify_addresses, authorize_destination (F2-S4/S5/S8)."""

from __future__ import annotations

import pytest

from aicl.control.errors import AiclError
from aicl.network.policy import (
    FIXED_NETWORK_POLICY as P, FakeResolver, authorize_destination, check_destination_rules,
    classify_addresses, normalize_owner_domain,
)

DOMAINS = ("example.com",)


def rules(capability, method, url, hop=0, domains=DOMAINS):
    return check_destination_rules(P, domains, capability, method, url, hop)


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/network/policy.py:normalize_owner_domain")
def test_normalize_owner_domain_accepts_only_lowercase_exact_dns_hosts():
    assert normalize_owner_domain("example.com") == "example.com"
    assert normalize_owner_domain("xn--bcher-kva.example") == "xn--bcher-kva.example"
    bad = ["Example.com", "example.com.", "*.example.com", "https://example.com", "example.com:443",
           "example.com/path", "user@example.com", "localhost", "intranet", "a.local", "a.internal",
           "127.0.0.1", "0x7f.1", "2130706433", "[::1]", "::1", "bücher.example", "-a.example.com",
           "a-.example.com", "a..example.com", ("a" * 64) + ".com", ("a." * 130) + "com", "", "exa mple.com"]
    for raw in bad:
        with pytest.raises(AiclError) as err:
            normalize_owner_domain(raw)
        assert err.value.error == "validation_failed", raw


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/network/policy.py:check_destination_rules")
def test_check_destination_rules_allows_only_fixed_endpoints_and_owner_hosts():
    ok = [("gmail.read", "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages", 0, ()),
          ("gmail.send", "POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", 0, ()),
          ("reddit.read", "GET", "https://oauth.reddit.com/r/x/new", 0, ()),
          ("reddit.post", "POST", "https://oauth.reddit.com/api/submit", 0, ()),
          ("network.fetch", "GET", "https://example.com/a?b=1", 0, DOMAINS),
          ("network.fetch", "HEAD", "https://example.com:443/", 3, DOMAINS)]
    for cap, method, url, hop, domains in ok:
        decision = rules(cap, method, url, hop, domains)
        assert decision.allowed and decision.reason == "allowed", (cap, url)

    denied = [  # (capability, method, url, hop, expected reason)
        ("network.fetch", "GET", "https://other.example.org/", 0, "host_not_allowed"),
        ("network.fetch", "GET", "https://sub.example.com/", 0, "host_not_allowed"),  # no wildcard / suffix match
        ("network.fetch", "GET", "http://example.com/", 0, "scheme_not_https"),
        ("network.fetch", "GET", "ftp://example.com/", 0, "scheme_not_https"),
        ("network.fetch", "GET", "https://example.com:8443/", 0, "port_not_allowed"),
        ("network.fetch", "GET", "https://user:pw@example.com/", 0, "userinfo_not_allowed"),
        ("network.fetch", "GET", "https://127.0.0.1/", 0, "ip_literal_not_allowed"),
        ("network.fetch", "GET", "https://[::1]/", 0, "ip_literal_not_allowed"),
        ("network.fetch", "GET", "https://2130706433/", 0, "ip_literal_not_allowed"),
        ("network.fetch", "POST", "https://example.com/", 0, "method_not_allowed"),
        ("network.fetch", "GET", "https://example.com/", 4, "redirect_limit"),
        ("gmail.send", "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", 0, "method_not_allowed"),
        ("gmail.send", "POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send/x", 0, "path_not_allowed"),
        ("gmail.read", "GET", "https://gmail.googleapis.com/other", 0, "path_not_allowed"),
        ("gmail.read", "GET", "https://oauth2.googleapis.com/token", 0, "host_not_allowed"),  # OAuth endpoints never usable
        ("reddit.post", "POST", "https://oauth.reddit.com/api/other", 0, "path_not_allowed"),
        ("inference", "GET", "https://example.com/", 0, "capability_not_networked"),
        ("nope", "GET", "https://example.com/", 0, "unknown_capability"),
    ]
    for cap, method, url, hop, reason in denied:
        decision = rules(cap, method, url, hop)
        assert not decision.allowed and decision.reason == reason, (cap, url, decision)
        assert decision.rule and "example.com/" not in (decision.rule or "")  # a rule name, never a URL
    assert not check_destination_rules(P, (), "network.fetch", "GET", "https://example.com/", 0).allowed  # no domains
    # the pure function never resolves, so it can never say address_not_public
    assert rules("network.fetch", "GET", "https://example.com/").reason != "address_not_public"


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/network/policy.py:classify_addresses")
def test_classify_addresses_requires_every_address_to_be_public_unicast():
    assert classify_addresses(["93.184.216.34"]) == "allowed"
    assert classify_addresses(["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]) == "allowed"
    for bad in ["127.0.0.1", "10.0.0.1", "172.16.5.4", "192.168.1.1", "169.254.169.254", "100.64.0.1", "224.0.0.1",
                "240.0.0.1", "0.0.0.0", "::1", "fe80::1", "fc00::1", "fd12::1", "ff02::1", "::", "::ffff:127.0.0.1",
                "not-an-ip"]:
        assert classify_addresses([bad]) == "address_not_public", bad
        assert classify_addresses(["93.184.216.34", bad]) == "address_not_public", bad  # one bad address denies
    assert classify_addresses([]) == "address_not_public"  # nothing resolved => deny


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/network/policy.py:authorize_destination")
def test_authorize_destination_resolves_only_after_rules_allow_and_reauthorizes_each_hop():
    public = FakeResolver({"example.com": ["93.184.216.34"], "rebind.example.com": ["10.0.0.5", "93.184.216.34"],
                           "gmail.googleapis.com": ["142.250.0.1"]})

    def auth(url, hop=0, domains=("example.com", "rebind.example.com"), resolver=public, cap="network.fetch", method="GET"):
        return authorize_destination(P, domains, cap, method, url, hop, resolver)

    assert auth("https://example.com/x").allowed and public.calls == ["example.com"]
    assert auth("https://gmail.googleapis.com/gmail/v1/users/me/labels", cap="gmail.read").allowed
    before = list(public.calls)
    for url in ("http://example.com/", "https://evil.example.org/", "https://127.0.0.1/"):
        assert not auth(url).allowed
    assert public.calls == before  # rule denials never reach the resolver
    private = auth("https://rebind.example.com/")
    assert not private.allowed and private.reason == "address_not_public"
    unresolved = auth("https://example.com/", resolver=FakeResolver())  # resolves to nothing
    assert not unresolved.allowed and unresolved.reason == "address_not_public"

    class Broken:
        def resolve(self, host):
            raise OSError("dns down")

    broken = auth("https://example.com/", resolver=Broken())
    assert not broken.allowed and broken.reason == "policy_unavailable"
    assert auth("https://example.com/", hop=3).allowed and auth("https://example.com/", hop=4).reason == "redirect_limit"
    hop_resolver = FakeResolver({"example.com": ["93.184.216.34"]})  # redirect hop to a metadata host is re-authorized
    metadata = auth("https://169.254.169.254/latest", hop=1, resolver=hop_resolver)
    assert not metadata.allowed and metadata.reason == "ip_literal_not_allowed"

"""Pure domain rules: lifecycle table, cost rounding, price-table validation, digest, fixed doubles."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from aicl.control.auth import AuthContext, FixedAuthProvider
from aicl.control.confirmation import payload_digest
from aicl.control.csrf import FixedCsrfVerifier
from aicl.control.errors import AiclError
from aicl.control.instances import next_lifecycle
from aicl.control.price_table import PriceTableVersion, Rate, cost_micro_usd, parse_price_table

EXAMPLE = json.loads((__import__("pathlib").Path(__file__).resolve().parents[3]
                      / "backend/aicl/price_table.example.json").read_text())
STATES = ("draft", "active", "paused", "archived")
ACTIONS = ("activate", "pause", "resume", "archive")
# Independent literal of the technical.md lifecycle table (F1-S7).
TABLE = {("draft", "activate"): "active", ("draft", "archive"): "archived",
         ("active", "pause"): "paused", ("active", "archive"): "archived",
         ("paused", "resume"): "active", ("paused", "archive"): "archived"}


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/instances.py:next_lifecycle")
def test_lifecycle_accepts_only_listed_transitions_and_archived_is_terminal():
    for state in STATES:
        for action in ACTIONS:
            if (state, action) in TABLE:
                assert next_lifecycle(state, action) == TABLE[(state, action)]
            else:
                with pytest.raises(AiclError) as err:
                    next_lifecycle(state, action)
                assert err.value.error == "invalid_transition"
                assert err.value.extra["from"] == state and err.value.extra["action"] == action


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/price_table.py:cost_micro_usd")
def test_cost_is_integer_micro_usd_rounded_up_and_missing_meter_is_unavailable():
    version = PriceTableVersion("v", datetime(2026, 1, 1, tzinfo=timezone.utc),
                                (Rate("inference.input_tokens", 1000, 1), Rate("compute.minutes", 1, 5000)), "0" * 64)
    assert [cost_micro_usd(version, "inference.input_tokens", n) for n in (0, 1, 1000, 1001)] == [0, 1, 1, 2]
    assert cost_micro_usd(version, "compute.minutes", 3) == 15000
    with pytest.raises(AiclError) as err:
        cost_micro_usd(version, "inference.output_tokens", 1)
    assert err.value.error == "unavailable"


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/price_table.py:parse_price_table")
def test_price_table_schema_is_validated_and_hash_is_canonical():
    raw = json.dumps(EXAMPLE).encode()
    parsed = parse_price_table(raw)
    assert parsed.version == "2026-10-01" and len(parsed.rates) == 3 and len(parsed.sha256) == 64
    reordered = json.dumps({k: EXAMPLE[k] for k in reversed(list(EXAMPLE))}, indent=3).encode()
    assert parse_price_table(reordered).sha256 == parsed.sha256

    def mutated(**changes):
        return json.dumps({**EXAMPLE, **changes}).encode()

    def rate(index, **changes):
        rates = [dict(r) for r in EXAMPLE["rates"]]
        rates[index].update(changes)
        return mutated(rates=rates)

    invalid = [
        b"not json",
        rate(0, micro_usd=1.5),                       # no floats
        rate(0, unit_size=0),                         # positive unit size
        rate(0, micro_usd=-1),                        # nonnegative price
        mutated(rates=EXAMPLE["rates"][:2]),          # a meter is missing
        mutated(rates=EXAMPLE["rates"] + EXAMPLE["rates"][:1]),  # a meter appears twice
        mutated(version="bad version!"),              # version pattern
        mutated(effective_from="2026-10-01T00:00:00"),  # not a UTC timestamp
    ]
    for payload in invalid:
        with pytest.raises(AiclError) as err:
            parse_price_table(payload)
        assert err.value.error == "validation_failed"


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/confirmation.py:payload_digest")
def test_payload_digest_is_canonical_sha256_bound_to_instance_capability_and_payload():
    payload = {"to": "a@example.com", "body": "hi", "n": 1}
    expected = hashlib.sha256(json.dumps({"instance_id": "i1", "capability": "gmail.send", "payload": payload},
                                         sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert payload_digest("i1", "gmail.send", payload) == expected
    assert payload_digest("i1", "gmail.send", {"n": 1, "body": "hi", "to": "a@example.com"}) == expected
    assert len({expected, payload_digest("i2", "gmail.send", payload),
                payload_digest("i1", "reddit.post", payload),
                payload_digest("i1", "gmail.send", {**payload, "body": "changed"})}) == 4


def _context(session_id: str, expires_at: datetime) -> AuthContext:
    return AuthContext(owner_id="o1", tenant_id="o1", session_id=session_id, expires_at=expires_at)


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/auth.py:FixedAuthProvider")
def test_fixed_auth_provider_resolves_only_configured_unexpired_fixture_cookies():
    future = datetime.now(timezone.utc) + timedelta(days=1)
    valid, expired = _context("s-valid", future), _context("s-old", datetime(2000, 1, 1, tzinfo=timezone.utc))
    provider = FixedAuthProvider({"cookie-valid": valid, "cookie-old": expired})
    assert provider.resolve({"aicl_session": "cookie-valid"}) == valid
    assert provider.resolve({"aicl_session": "cookie-old"}) is None
    assert provider.resolve({"aicl_session": "unknown"}) is None
    assert provider.resolve({}) is None


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/csrf.py:FixedCsrfVerifier")
def test_fixed_csrf_verifier_accepts_its_token_only_for_fixture_sessions_and_own_origin():
    base = "http://127.0.0.1:4173"
    verifier = FixedCsrfVerifier("fixed-token", frozenset({"s-fixture"}), base)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    fixture, other = _context("s-fixture", future), _context("s-real", future)
    assert verifier.token_for("s-fixture") == "fixed-token"
    assert verifier.verify(fixture, "fixed-token", None) is True
    assert verifier.verify(fixture, "fixed-token", base) is True
    assert verifier.verify(fixture, "fixed-token", "http://evil.example") is False
    assert verifier.verify(fixture, "wrong", None) is False
    assert verifier.verify(fixture, None, None) is False
    assert verifier.verify(other, "fixed-token", None) is False

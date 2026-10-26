"""Hosted tool calls share the bounded inference budget and exact settlement."""
from datetime import timedelta
import json

import pytest

from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.control.instances import Limits
from aicl.control.price_table import cost_micro_usd, effective_version, load_version, parse_price_table
from support import EXAMPLE_PRICE_TABLE


WEB_PRICE = "gpt-6-sol-web-2026-10-25"


def test_web_calls_reserve_settle_and_replay_exact_counts_in_inference_budget(build_env):
    env = build_env()
    env.clock.advance(timedelta(days=11))
    _, inst = env.new_instance()
    estimate = Estimate(100, 50, 0, web_search_calls=3)
    with env.db.transaction() as conn:
        hold = env.budget.reserve(conn, inst.id, "hosted-search", estimate, price_table_version=WEB_PRICE)
        assert hold.inference_micro_usd == 30_700 and hold.compute_micro_usd == 0
        assert conn.execute("SELECT est_web_search_calls FROM budget_hold WHERE id=?", (hold.id,)).fetchone()[0] == 3
        assert env.budget.reserve(conn, inst.id, "hosted-search", estimate, price_table_version=WEB_PRICE) == hold
        with pytest.raises(AiclError) as changed:
            env.budget.reserve(conn, inst.id, "hosted-search", Estimate(100, 50, 0, 2), price_table_version=WEB_PRICE)
        assert changed.value.error == "conflict"
        usage = env.budget.settle(conn, hold.id, MeasuredUsage(70, 30, 0, web_search_calls=2))
        assert usage.inference_micro_usd == 20_440 and usage.web_search_calls == 2
        assert env.budget.settle(conn, hold.id, MeasuredUsage(70, 30, 0, 2)) == usage
        with pytest.raises(AiclError) as changed:
            env.budget.settle(conn, hold.id, MeasuredUsage(70, 30, 0, 1))
        assert changed.value.error == "conflict"
    amounts = env.budget.read_budget(inst.id).windows["inference"]["day"]
    assert amounts.settled == 20_440 and amounts.held == 0


def test_unpriced_nonzero_tool_calls_fail_closed_and_legacy_zero_usage_stays_valid(build_env):
    env = build_env()
    _, inst = env.new_instance()
    with env.db.transaction() as conn:
        with pytest.raises(AiclError) as denied:
            env.budget.reserve(conn, inst.id, "unpriced", Estimate(1, 1, 0, 1))
        assert denied.value.error == "denied" and denied.value.extra["reason"] == "price_unavailable"
        assert conn.execute("SELECT COUNT(*) FROM budget_hold").fetchone()[0] == 0
        legacy = env.budget.reserve(conn, inst.id, "legacy", Estimate(10, 10, 0))
        assert legacy.inference_micro_usd == 40
        with pytest.raises(AiclError) as unpriced:
            env.budget.settle(conn, legacy.id, MeasuredUsage(10, 10, 0, 1))
        assert unpriced.value.error == "unavailable"
        assert conn.execute("SELECT state FROM budget_hold WHERE id=?", (legacy.id,)).fetchone()[0] == "held"
        usage = env.budget.settle(conn, legacy.id, MeasuredUsage(10, 10, 0))
        assert usage.web_search_calls == 0 and usage.inference_micro_usd == 40


def test_tool_fees_cannot_exceed_limits_or_accept_invalid_counts_on_replay(build_env):
    env = build_env()
    env.clock.advance(timedelta(days=11))
    _, inst = env.new_instance(limits=Limits(10_000, 10_000, 1_000_000, 1_000_000))
    with env.db.transaction() as conn:
        with pytest.raises(AiclError) as denied:
            env.budget.reserve(conn, inst.id, "over-limit", Estimate(1, 0, 0, 1), price_table_version=WEB_PRICE)
        assert denied.value.extra["reason"] == "budget_exhausted"
        hold = env.budget.reserve(conn, inst.id, "zero-calls", Estimate(0, 0, 0), price_table_version=WEB_PRICE)
        for value in (False, -1, 1.5):
            with pytest.raises(AiclError) as invalid:
                env.budget.reserve(conn, inst.id, "zero-calls", Estimate(0, 0, 0, value), price_table_version=WEB_PRICE)
            assert invalid.value.error == "validation_failed"
            with pytest.raises(AiclError) as invalid:
                env.budget.settle(conn, hold.id, MeasuredUsage(0, 0, 0, value))
            assert invalid.value.error == "validation_failed"
        assert conn.execute("SELECT state FROM budget_hold WHERE id=?", (hold.id,)).fetchone()[0] == "held"


def test_optional_tool_meter_preserves_legacy_hashes_and_new_pinned_price(build_env):
    legacy_data = json.loads(EXAMPLE_PRICE_TABLE.read_text())
    legacy = parse_price_table(EXAMPLE_PRICE_TABLE.read_bytes())
    env = build_env()
    env.clock.advance(timedelta(days=11))
    with env.db.reader() as conn:
        assert load_version(conn, legacy.version).sha256 == legacy.sha256
        assert effective_version(conn, env.clock.now()).version == legacy.version
        pinned = load_version(conn, WEB_PRICE)
    assert cost_micro_usd(legacy, "inference.web_search_calls", 0) == 0
    with pytest.raises(AiclError):
        cost_micro_usd(legacy, "inference.web_search_calls", 1)
    data = {"version": WEB_PRICE, "effective_from": "2026-10-25T00:00:00Z",
            "rates": [{"meter": rate.meter, "unit_size": rate.unit_size, "micro_usd": rate.micro_usd} for rate in pinned.rates]}
    assert parse_price_table(json.dumps(data).encode()).sha256 == pinned.sha256
    assert cost_micro_usd(pinned, "inference.web_search_calls", 3) == 30_000
    assert cost_micro_usd(pinned, "compute.minutes", 5) == 0
    legacy_data["rates"].append({"meter": "inference.web_search_calls", "unit_size": 1, "micro_usd": 10_000})
    assert len(parse_price_table(json.dumps(legacy_data).encode()).rates) == 4
    legacy_data["rates"] = [r for r in legacy_data["rates"] if r["meter"] != "compute.minutes"]
    with pytest.raises(AiclError):
        parse_price_table(json.dumps(legacy_data).encode())

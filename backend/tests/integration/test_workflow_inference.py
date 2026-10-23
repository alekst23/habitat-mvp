"""Live-inference orchestration with a deterministic adapter; no network/keys."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest

from aicl.control.price_table import effective_version
from aicl.control.errors import AiclError
from aicl.workflow.inference_service import MAX_COST, PRICE_VERSION
from aicl.workflow.openai_inference import InferenceResult, InferenceNoChargeError, InferenceUnknownOutcomeError
from aicl.workflow.service import MockWorkflowService
from aicl.work.gate import SqliteHoldReconciler
from test_pocketplan_workflow import prepared, tick, pay, campaign


class Adapter:
    def __init__(self, db, error=None, invalid=False):
        self.db, self.error, self.invalid, self.calls = db, error, invalid, []

    def generate(self, snapshot, spec, feedback=""):
        assert getattr(self.db._local, "conn", None) is None
        self.calls.append((snapshot, spec, feedback))
        if self.error:
            raise self.error
        return InferenceResult("A real model response to " + snapshot["goal"],
            [{"criterion": c, "passed": True, "reason": "The supplied criterion is covered."} for c in spec["criteria"]],
            100, 50, "resp_" + str(len(self.calls)), "gpt-6-sol", "invalid_output" if self.invalid else None)


def live(build_env, *, cap=1_000_000, error=None, invalid=False):
    env, _, commerce, auth, inst, ops = prepared(build_env)
    env.clock.advance(timedelta(days=8))  # Real pricing date; saved demo time is independent.
    adapter = Adapter(env.db, error, invalid)
    wf = MockWorkflowService(env.db, env.clock, commerce=commerce, inference=adapter, inference_max_spend_micro_usd=cap)
    return env, wf, commerce, auth, inst, ops, adapter


def rows(env, table):
    with env.db.reader() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM " + table)]


def test_live_plan_is_charged_once_and_links_to_exact_fixture_purchase(build_env):
    env, wf, commerce, auth, inst, _, adapter = live(build_env)
    due = wf.config(auth, inst.id)["next_due"]
    view = wf.advance(auth, inst.id, due)
    assert len(adapter.calls) == 1
    plan = next(d for d in view["deliverables"] if d["spec_key"] == "campaign_plan")
    assert plan["inference"] == {"provider": "openai", "model": "gpt-6-sol", "response_id": "resp_1",
        "input_tokens": 100, "output_tokens": 50, "cost_micro_usd": 700,
        "validation_method": "model_self_assessment_and_structural_checks", "validation_error": None}
    assert all("self-assessment" in c["reason"] for c in plan["criteria"])
    creative = next(d for d in view["deliverables"] if d["spec_key"] == "ad_creative")
    assert creative["inference"] is None
    purchase, = view["purchases"]
    assert purchase["state"] == "awaiting_approval"
    assert {s["name"] for s in purchase["source_work"]} == {"Campaign plan", "Ad creative"}
    for item in purchase["quote"]["campaign"]["creative"]:
        assert item["headline"] in creative["content"]
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - 700
    assert len(rows(env, "budget_usage")) == 1
    assert rows(env, "budget_usage")[0]["price_table_version"] == PRICE_VERSION
    with env.db.reader() as conn:
        assert effective_version(conn, env.clock.now()).version != PRICE_VERSION
    restarted = MockWorkflowService(env.db, env.clock, commerce=commerce, inference=adapter)
    assert restarted.advance(auth, inst.id, due)["occurrence"]["replayed"]
    assert len(adapter.calls) == 1 and len(rows(env, "budget_usage")) == 1
    # A paid quote must not make replay of its earlier occurrence report ads.
    pay(wf, commerce, auth, purchase["id"])
    assert campaign(restarted.advance(auth, inst.id, due))["days_reported"] == 0


def test_live_report_uses_frozen_metrics_and_deterministic_arithmetic(build_env):
    _, wf, commerce, auth, inst, _, adapter = live(build_env)
    view = tick(wf, auth, inst.id)
    pay(wf, commerce, auth, view["purchases"][0]["id"])
    reported = tick(wf, auth, inst.id)
    assert len(adapter.calls) == 2
    report = next(d for d in reported["deliverables"] if "day 1 report" in d["name"])
    assert adapter.calls[-1][1]["ad_report"]["clicks"] == 30
    assert "CPC = $10.00 / 30 clicks = $0.33" in report["content"]
    assert "CPI = $10.00 / 6 installs = $1.67" in report["content"]
    expansion = next(p for p in reported["purchases"] if p["amount_minor"] == 1500)
    assert any(s["name"] == report["name"] for s in expansion["source_work"])


def test_known_usage_invalid_output_is_charged_and_cannot_request_purchase(build_env):
    env, wf, commerce, auth, inst, _, adapter = live(build_env, invalid=True)
    view = tick(wf, auth, inst.id)
    plan = next(d for d in view["deliverables"] if d["spec_key"] == "campaign_plan")
    assert plan["state"] == "needs_work" and not any(c["passed"] for c in plan["criteria"])
    assert plan["inference"]["validation_error"] == "invalid_output"
    assert not view["purchases"] and commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 4_999_300
    adapter.invalid = False
    second = tick(wf, auth, inst.id)
    assert len(adapter.calls) == 2 and len(second["purchases"]) == 1
    assert len(rows(env, "budget_usage")) == 2


def test_unknown_outcome_survives_restart_and_fake_reconciler_cannot_release_it(build_env):
    env, wf, commerce, auth, inst, _, adapter = live(build_env, error=InferenceUnknownOutcomeError("timeout"))
    view = tick(wf, auth, inst.id)
    assert not view["purchases"] and len(adapter.calls) == 1
    assert rows(env, "budget_hold")[0]["state"] == "unknown"
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - MAX_COST
    env.clock.advance(timedelta(seconds=901))
    class NeverLookup:
        def lookup(self, hold_id):
            raise AssertionError("Live inference cannot be looked up in the fake executor")
    SqliteHoldReconciler(env.db, env.clock, env.budget, NeverLookup()).run_once()
    assert rows(env, "budget_hold")[0]["state"] == "unknown"
    restarted = MockWorkflowService(env.db, env.clock, commerce=commerce, inference=adapter)
    restarted.overview(auth, inst.id)
    tick(restarted, auth, inst.id)
    assert len(adapter.calls) == 1 and not rows(env, "budget_usage")


@pytest.mark.parametrize("reason", ["provider_401", "provider_404"])
def test_proven_no_charge_rejection_only_retries_on_later_tick(build_env, reason):
    env, wf, commerce, auth, inst, _, adapter = live(build_env, error=InferenceNoChargeError(reason))
    due = wf.config(auth, inst.id)["next_due"]
    view = wf.advance(auth, inst.id, due)
    assert not view["purchases"]
    plan = next(r for r in view["runs"] if r["spec_key"] == "campaign_plan")
    assert plan["state"] == "inference_failed" and "not accepted" in plan["blocked_reason"]
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000
    assert rows(env, "budget_hold")[0]["state"] == "released"
    adapter.error = None
    wf.advance(auth, inst.id, due)
    assert len(adapter.calls) == 1
    assert len(tick(wf, auth, inst.id)["purchases"]) == 1
    assert len(adapter.calls) == 2
    assert [a["state"] for a in rows(env, "workflow_inference_attempt")] == ["released", "settled"]


@pytest.mark.parametrize("guard", ["server_cap", "daily_budget", "credit"])
def test_preflight_guards_deny_before_any_provider_call(build_env, guard):
    env, wf, commerce, auth, inst, _, adapter = live(build_env, cap=MAX_COST - 1 if guard == "server_cap" else 1_000_000)
    with env.db.transaction() as conn:
        if guard == "daily_budget":
            conn.execute("UPDATE agent_instance SET inference_daily_micro_usd=1 WHERE id=?", (inst.id,))
        elif guard == "credit":
            # Existing paid usage can exhaust credits; append-only ledger remains intact.
            from aicl.control.budget import Estimate, MeasuredUsage
            hold = commerce.budget.reserve(conn, inst.id, "prior-credit-use", Estimate(0, 0, 0))
            commerce.budget.settle(conn, hold.id, MeasuredUsage(0, 0, 0))
            conn.execute("INSERT INTO mock_commerce_ledger(id,instance_id,kind,delta_micro_usd,reference,hold_id,created_at) VALUES ('prior',?,'inference_usage',-4999999,'inference:prior',?,'2026-10-14T12:00:00.000000Z')", (inst.id, hold.id))
    view = tick(wf, auth, inst.id)
    assert adapter.calls == [] and not view["purchases"]
    assert next(r for r in view["runs"] if r["spec_key"] == "campaign_plan")["state"] == "inference_blocked"
    assert rows(env, "workflow_inference_attempt")[0]["state"] == "blocked"


def test_concurrent_replay_and_pause_do_not_hold_database_lock_or_lose_real_usage(build_env):
    env, wf, commerce, auth, inst, ops, adapter = live(build_env)
    entered, release = Event(), Event()
    generate = adapter.generate
    def delayed(snapshot, spec, feedback):
        entered.set()
        assert release.wait(5)
        return generate(snapshot, spec, feedback)
    adapter.generate = delayed
    due = wf.config(auth, inst.id)["next_due"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(wf.advance, auth, inst.id, due)
        assert entered.wait(5)
        replay = wf.advance(auth, inst.id, due)
        assert not replay["purchases"]
        assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - MAX_COST
        current = env.instances.get(auth, inst.id)
        ops.set_lifecycle(auth, inst.id, current.version, "pause")
        release.set()
        view = future.result(timeout=5)
    assert len(adapter.calls) == 1 and len(rows(env, "budget_usage")) == 1
    assert not view["purchases"]
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 4_999_300


def test_claimed_but_interrupted_call_is_not_resent_after_restart(build_env):
    env, wf, commerce, auth, inst, _, adapter = live(build_env)
    wf.inference.drain = lambda *args: 0
    view = tick(wf, auth, inst.id)
    attempt, = rows(env, "workflow_inference_attempt")
    assert attempt["state"] == "pending"
    assert wf.inference._claim(auth, attempt["id"]) is not None
    # Model call may have happened before a process crash; no usage is known.
    restarted = MockWorkflowService(env.db, env.clock, commerce=commerce, inference=adapter)
    env.clock.advance(timedelta(seconds=121))
    projected = restarted.overview(auth, inst.id)
    job = next(r for r in projected["runs"] if r["spec_key"] == "campaign_plan")
    assert job["state"] == "inference_unknown" and "not be sent again" in job["blocked_reason"]
    assert job["inference_attempt"]["reserved_micro_usd"] == MAX_COST
    restarted.advance(auth, inst.id, view["occurrence"]["scheduled_for"])
    tick(restarted, auth, inst.id)
    assert adapter.calls == []
    assert rows(env, "budget_hold")[0]["state"] == "held"
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - MAX_COST
    assert not rows(env, "budget_usage")


def test_lifetime_real_cap_is_not_replenished_by_payment_topups(build_env):
    env, wf, commerce, auth, inst, _, adapter = live(build_env, cap=MAX_COST)
    initial = tick(wf, auth, inst.id)
    pay(wf, commerce, auth, initial["purchases"][0]["id"])
    order = commerce.create_topup(auth, inst.id, 500, "extra-demo-funds")
    commerce.select_payment_buyer(auth, order["id"], "demo-buyer")
    commerce.checkout(auth, order["id"], "complete")
    view = tick(wf, auth, inst.id)
    assert len(adapter.calls) == 1  # $0.0007 spent leaves less than next $0.052 bound.
    report = next(r for r in view["runs"] if "day 1 report" in r["deliverable_name"])
    assert report["state"] == "inference_blocked" and "ceiling" in report["blocked_reason"]
    assert sum(a["cost_micro_usd"] or 0 for a in rows(env, "workflow_inference_attempt")) == 700


def test_overrun_usage_is_settled_then_stops_all_later_dispatch(build_env):
    env, wf, commerce, auth, inst, _, adapter = live(build_env)
    def overrun(snapshot, spec, feedback):
        adapter.calls.append((snapshot, spec, feedback))
        return InferenceResult("", [], 17000, 2100, "resp_overrun", "gpt-6-sol", "usage_exceeded_bound")
    adapter.generate = overrun
    view = tick(wf, auth, inst.id)
    assert not view["purchases"]
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - 55000
    assert rows(env, "budget_usage")[0]["inference_micro_usd"] == 55000
    tick(wf, auth, inst.id)
    assert len(adapter.calls) == 1


def test_pinned_model_price_cannot_be_used_before_its_effective_date(build_env):
    from aicl.control.budget import Estimate
    env = build_env()
    _, inst = env.new_instance(capabilities=("inference",))
    with env.db.transaction() as conn:
        with pytest.raises(AiclError) as caught:
            env.budget.reserve(conn, inst.id, "future-model", Estimate(16000, 2000, 0), price_table_version=PRICE_VERSION)
        assert caught.value.extra["reason"] == "price_unavailable"

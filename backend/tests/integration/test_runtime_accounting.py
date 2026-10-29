"""Runtime and legacy admission share reservations without repeating charges."""
from datetime import timedelta

import pytest

from aicl.agent_runtime.accounting import RuntimeAccounting, platform_spend
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.work.gate import SqliteHoldReconciler
from aicl.work.models import ExecutorOutcome
from test_mock_commerce import ready
from test_pocketplan_workflow import tick
from test_workflow_inference import MAX_COST, live, rows


def reserve(env, auth, inst, operation="operation-1", estimate=Estimate(100, 100, 0), **options):
    accounting = RuntimeAccounting(env.db, env.clock, **options)
    with env.db.transaction() as conn:
        hold = accounting.reserve(conn, auth, inst.id, operation, estimate, 1_000_000, 0)
    return accounting, hold


def test_startup_reconciler_cannot_release_runtime_unknown_or_stale_hold(build_env):
    env, _, auth, inst, _ = ready(build_env)
    accounting, first = reserve(env, auth, inst)
    _, second = reserve(env, auth, inst, "operation-2")
    with env.db.transaction() as conn:
        accounting.mark_unknown(conn, first.id)
    env.clock.advance(timedelta(seconds=901))
    class LegacyExecutor:
        def __init__(self):
            self.lookups = []

        def lookup(self, hold_id):
            self.lookups.append(hold_id)
            return ExecutorOutcome("not_started")

    executor = LegacyExecutor()
    SqliteHoldReconciler(env.db, env.clock, env.budget, executor).run_once()
    assert executor.lookups == []
    assert {r["id"]: r["state"] for r in rows(env, "budget_hold")} == {first.id: "unknown", second.id: "held"}


def test_credit_reservation_unknown_settlement_and_replay_count_once(build_env):
    env, commerce, auth, inst, _ = ready(build_env)
    accounting, hold = reserve(env, auth, inst)
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - 400
    with env.db.transaction() as conn:
        assert accounting.reserve(conn, auth, inst.id, "operation-1", Estimate(100, 100, 0), 1_000_000, 400).id == hold.id
        accounting.mark_unknown(conn, hold.id)
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - 400
    with env.db.transaction() as conn:
        usage = accounting.settle(conn, hold.id, MeasuredUsage(20, 10, 0))
        assert accounting.settle(conn, hold.id, MeasuredUsage(20, 10, 0)) == usage
        assert platform_spend(conn, "inference") == 50
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - 50
    assert len(rows(env, "budget_usage")) == 1
    assert sum(r["event_type"] == "budget.settled" for r in rows(env, "audit_event")) == 1
    with pytest.raises(AiclError) as caught:
        with env.db.transaction() as conn:
            accounting.settle(conn, hold.id, MeasuredUsage(21, 10, 0))
    assert caught.value.error == "conflict"


def test_runtime_holds_and_usage_reduce_legacy_platform_allowance(build_env):
    env, workflow, _, auth, inst, _, adapter = live(build_env, cap=MAX_COST + 399)
    accounting, hold = reserve(env, auth, inst)
    tick(workflow, auth, inst.id)
    assert adapter.calls == []
    assert rows(env, "workflow_inference_attempt")[-1]["validation_error"] == "inference_spend_ceiling"
    with env.db.transaction() as conn:
        accounting.settle(conn, hold.id, MeasuredUsage(100, 100, 0))
    tick(workflow, auth, inst.id)
    assert adapter.calls == []  # Settlement cannot restore spent platform credit.


def test_legacy_usage_and_render_hold_reduce_runtime_platform_allowance(build_env):
    from aicl.render.service import MAX_COMPUTE_COST, RenderExecution
    env, workflow, _, auth, inst, _, _ = live(build_env)
    tick(workflow, auth, inst.id)
    # The earlier inference used 700 microUSD. Render reserves its own compute.
    env.clock.advance(timedelta(days=1))
    execution = RenderExecution(workflow)
    execution.dispatch()
    with env.db.reader() as conn:
        assert platform_spend(conn, "inference") == 700
        assert platform_spend(conn, "compute") == MAX_COMPUTE_COST
    with pytest.raises(AiclError) as caught:
        reserve(env, auth, inst, platform_limit_micro_usd=700 + MAX_COMPUTE_COST + 399)
    assert caught.value.extra["reason"] == "platform_spend_ceiling"


def test_runtime_compute_hold_and_usage_reduce_render_allowance(build_env):
    from aicl.render.service import MAX_COMPUTE_COST, RenderExecution
    env, workflow, _, auth, inst, _, _ = live(build_env)
    accounting, hold = reserve(env, auth, inst, estimate=Estimate(0, 0, 1))
    workflow.render_max_spend_micro_usd = MAX_COMPUTE_COST + 4_999
    execution = RenderExecution(workflow)
    config = workflow.config(auth, inst.id)
    for settled in (False, True):
        if settled:
            with env.db.transaction() as conn:
                accounting.settle(conn, hold.id, MeasuredUsage(0, 0, 1))
        with pytest.raises(AiclError) as caught:
            with env.db.transaction() as conn:
                execution._enqueue(conn, auth, config, config["next_due"])
        assert caught.value.extra["reason"] == "render_spend_ceiling"
    assert not rows(env, "render_dispatch")


def test_shared_credit_blocks_legacy_while_runtime_reserves_remaining_balance(build_env):
    env, workflow, commerce, auth, inst, _, adapter = live(build_env)
    # Legacy could afford its 52,000 bound until runtime reserves 400 of it.
    with env.db.transaction() as conn:
        prior = commerce.budget.reserve(conn, inst.id, "prior-credit", Estimate(0, 0, 0))
        commerce.budget.settle(conn, prior.id, MeasuredUsage(0, 0, 0))
        conn.execute("INSERT INTO mock_commerce_ledger "
                     "(id,instance_id,kind,delta_micro_usd,reference,hold_id,created_at) "
                     "VALUES ('prior-credit',?,'inference_usage',-4947700,'inference:prior-credit',?,?)",
                     (inst.id, prior.id, prior.created_at.isoformat()))
    accounting, hold = reserve(env, auth, inst)
    tick(workflow, auth, inst.id)
    assert not adapter.calls
    assert rows(env, "workflow_inference_attempt")[-1]["validation_error"] == "credit_insufficient"
    with env.db.transaction() as conn:
        accounting.release(conn, hold.id)
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 52_300
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == 1


def test_runtime_denies_scope_changed_controls_and_overruns_without_hiding_usage(build_env):
    env, commerce, auth, inst, ops = ready(build_env)
    other, _ = env.new_instance(capabilities=("inference",))
    with pytest.raises(AiclError) as caught:
        reserve(env, other, inst)
    assert caught.value.error == "not_found"
    accounting, hold = reserve(env, auth, inst)
    with env.db.transaction() as conn:
        accounting.settle(conn, hold.id, MeasuredUsage(200, 100, 0))
    assert commerce.dashboard(auth, inst.id)["balance_micro_usd"] == 5_000_000 - 500
    with pytest.raises(AiclError) as caught:
        reserve(env, auth, inst, "operation-2")
    assert caught.value.extra["reason"] == "reconciliation_pending"
    ops.set_lifecycle(auth, inst.id, env.instances.get(auth, inst.id).version, "pause")
    with pytest.raises(AiclError) as caught:
        reserve(env, auth, inst, "operation-3")
    assert caught.value.extra["reason"] == "instance_not_active"


def test_unrelated_fake_work_does_not_consume_tracked_provider_allowance(build_env):
    from test_work_gate import active, build_gate, req
    env, workflow, _, auth, inst, _, adapter = live(build_env, cap=MAX_COST + 400)
    fake_auth, fake_inst, _ = active(env, caps=("inference",))
    gate, _ = build_gate(env)
    assert gate.authorize_and_dispatch(fake_auth, req(fake_inst, 1,
        estimate=Estimate(100_000, 1_000, 2),
        payload={"sim": {"input_tokens": 100_000, "output_tokens": 1_000, "compute_minutes": 2}})).outcome == "succeeded"
    assert gate.authorize_and_dispatch(fake_auth, req(fake_inst, 2,
        estimate=Estimate(100, 100, 1), payload={"sim": {"outcome": "unknown"}})).outcome == "unknown"
    with env.db.reader() as conn:
        assert platform_spend(conn, "inference") == platform_spend(conn, "compute") == 0
    reserve(env, auth, inst, platform_limit_micro_usd=400)
    tick(workflow, auth, inst.id)
    assert len(adapter.calls) == 1
    with env.db.reader() as conn:
        assert platform_spend(conn, "inference") == 400 + 700
        assert platform_spend(conn, "compute") == 0


@pytest.mark.parametrize("outcome", ["unknown", "submission_unknown", "overrun"])
def test_render_unresolved_outcome_blocks_new_runtime_across_instances(build_env, outcome):
    from aicl.render.service import RenderExecution
    from test_work_gate import active
    env, workflow, commerce, _, _, _, _ = live(build_env)
    dispatch, = RenderExecution(workflow).dispatch()["dispatches"]
    if outcome == "submission_unknown":
        RenderExecution(workflow).uncertain(dispatch["id"])
    with env.db.transaction() as conn:
        hold_id = conn.execute("SELECT hold_id FROM render_dispatch WHERE id=?", (dispatch["id"],)).fetchone()[0]
        if outcome == "unknown":
            commerce.budget.mark_unknown(conn, hold_id)
        elif outcome == "overrun":
            # Preserve a verified actual charge even if it exceeds the bound.
            commerce.budget.settle(conn, hold_id, MeasuredUsage(0, 0, 7))
    auth, inst, _ = active(env, caps=("inference",))
    with pytest.raises(AiclError) as caught:
        reserve(env, auth, inst, estimate=Estimate(0, 0, 0))
    assert caught.value.extra["reason"] == "reconciliation_pending"

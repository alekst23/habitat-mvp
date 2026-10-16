"""BudgetPort and price table on real SQLite (F1-S3/S4/S5/S10/S11/S12)."""

from __future__ import annotations

import sqlite3
import threading
from datetime import timedelta

import pytest

from aicl.control.audit import AuditEvent
from aicl.control.budget import Estimate, MeasuredUsage, NoUsage
from aicl.control.errors import AiclError
from aicl.control.instances import Limits
from aicl.control.price_table import cost_micro_usd, effective_version, import_price_table
from support import EXAMPLE_PRICE_TABLE
from support import Abort, work_id

# 1 compute minute costs 5000 micro-USD with the example table.
ONE = Estimate(0, 0, 1)
MEASURED_TWO = MeasuredUsage(0, 0, 2)


def denied_reason(call) -> str:
    with pytest.raises(AiclError) as err:
        call()
    assert err.value.error == "denied"
    return err.value.extra["reason"]


def reserve(env, inst, n, estimate=ONE):
    with env.db.transaction() as conn:
        return env.budget.reserve(conn, inst.id, work_id(n), estimate)


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/budget.py:SqliteBudgetPort")
def test_reserve_checks_four_windows_atomically_and_is_idempotent(build_env):
    env = build_env()
    # compute daily limit fits exactly 3 minutes; monthly would fit 100.
    auth, inst = env.new_instance(limits=Limits(1_000_000, 1_000_000, 15_000, 500_000))
    zero_auth, zero_inst = env.new_instance(limits=Limits())  # default zero limits
    assert denied_reason(lambda: reserve(env, zero_inst, 1, Estimate(0, 0, 0))) == "budget_exhausted"

    # monthly window binds on its own: settled usage of an earlier day leaves daily room but not monthly room
    month_auth, month_inst = env.new_instance(limits=Limits(1_000_000, 1_000_000, 10_000, 12_000))
    with env.db.transaction() as conn:
        env.budget.settle(conn, reserve(env, month_inst, 1, Estimate(0, 0, 2)).id, MeasuredUsage(0, 0, 2))
    env.clock.advance(timedelta(days=1))
    assert denied_reason(lambda: reserve(env, month_inst, 2, ONE)) == "budget_exhausted"  # 10000 + 5000 > 12000
    env.clock.advance(timedelta(days=-1))

    first = reserve(env, inst, 1)
    assert first.state == "held" and first.compute_micro_usd == 5000 and first.price_table_version == "2026-10-01"
    assert (first.window_day, first.window_month) == ("2026-10-14", "2026-10")
    assert reserve(env, inst, 1).id == first.id  # same key returns the original hold
    with pytest.raises(AiclError) as err:  # same key, different estimate
        reserve(env, inst, 1, Estimate(0, 0, 2))
    assert err.value.error == "conflict"

    results, barrier = [], threading.Barrier(2)

    def contend(n):
        barrier.wait()
        try:
            results.append(("hold", reserve(env, inst, n, Estimate(0, 0, 2)).id))
        except AiclError as exc:
            results.append((exc.error, exc.extra.get("reason")))

    threads = [threading.Thread(target=contend, args=(n,)) for n in (10, 11)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    # 5000 held + 10000 fits the 15000 daily limit exactly once; the second 10000 cannot also fit.
    assert sorted(kind for kind, _ in results) == ["denied", "hold"]
    assert ("denied", "budget_exhausted") in results

    view = env.budget.read_budget(inst.id)
    compute_day = view.windows["compute"]["day"]
    assert compute_day.limit == 15_000 and compute_day.held == 15_000 and compute_day.available == 0
    assert view.windows["inference"]["day"].limit == 1_000_000


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/budget.py:SqliteBudgetPort")
def test_reserve_and_audit_in_one_unit_of_work_roll_back_together(build_env):
    env = build_env()
    auth, inst = env.new_instance()
    with pytest.raises(Abort):
        with env.db.transaction() as conn:
            env.budget.reserve(conn, inst.id, work_id(1), ONE)
            env.audit.append(conn, AuditEvent("budget.reserved", "gate", "committed", auth.tenant_id,
                                              auth.owner_id, inst.id, details={"hold_id": "h"}))
            raise Abort()
    assert env.budget.read_budget(inst.id).windows["compute"]["day"].held == 0
    assert env.audit.list_for_instance(auth, inst.id) == []


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/budget.py:SqliteBudgetPort")
def test_settle_unknown_release_reconcile_and_blocking_rules(build_env):
    env = build_env(hold_stale_seconds=900)
    auth, inst = env.new_instance(limits=Limits(1_000_000, 1_000_000, 100_000, 100_000))

    # settle: cost from the hold's price version; idempotent; different usage conflicts; hold released.
    hold = reserve(env, inst, 1, Estimate(1000, 1000, 2))
    assert hold.inference_micro_usd == 4000 and hold.compute_micro_usd == 10000
    with env.db.transaction() as conn:
        usage = env.budget.settle(conn, hold.id, MeasuredUsage(1000, 0, 1))
        again = env.budget.settle(conn, hold.id, MeasuredUsage(1000, 0, 1))
    assert again == usage and (usage.inference_micro_usd, usage.compute_micro_usd) == (1000, 5000)
    assert usage.price_table_version == "2026-10-01"
    with pytest.raises(AiclError) as err:
        with env.db.transaction() as conn:
            env.budget.settle(conn, hold.id, MeasuredUsage(1000, 0, 2))
    assert err.value.error == "conflict"
    day = env.budget.read_budget(inst.id).windows["compute"]["day"]
    assert (day.settled, day.held) == (5000, 0)

    # over-measured settlement is recorded in full, never truncated.
    over = reserve(env, inst, 2, ONE)
    with env.db.transaction() as conn:
        assert env.budget.settle(conn, over.id, MEASURED_TWO).compute_micro_usd == 10000
    assert env.budget.read_budget(inst.id).windows["compute"]["day"].settled == 15000

    # release from held; a late settle of a released hold is a conflict that is never silently dropped.
    freed = reserve(env, inst, 3, ONE)
    with env.db.transaction() as conn:
        assert env.budget.release(conn, freed.id).state == "released"
        assert env.budget.release(conn, freed.id).state == "released"
    with pytest.raises(AiclError) as err:
        with env.db.transaction() as conn:
            env.budget.settle(conn, freed.id, MeasuredUsage(0, 0, 1))
    assert err.value.error == "conflict"
    late = [e for e in env.audit.list_for_instance(auth, inst.id) if e.event_type == "budget.late_settlement"]
    assert len(late) == 1

    # young held counts against limits but does not block; unknown blocks and keeps its full amount.
    young = reserve(env, inst, 4, ONE)
    h5 = reserve(env, inst, 5, ONE)
    assert h5.state == "held"
    with env.db.transaction() as conn:
        assert env.budget.mark_unknown(conn, young.id).state == "unknown"
        assert env.budget.mark_unknown(conn, young.id).state == "unknown"
    assert denied_reason(lambda: reserve(env, inst, 6, ONE)) == "reconciliation_pending"
    view = env.budget.read_budget(inst.id)
    assert view.blocking_hold_count == 1 and view.windows["compute"]["day"].held == 10000
    with env.db.transaction() as conn:  # reconcile with no usage releases it
        assert env.budget.reconcile(conn, young.id, NoUsage()).state == "released"
    h7 = reserve(env, inst, 7, ONE)
    assert h7.state == "held"

    # a stale held hold blocks too (measured from created_at with the clock); an unknown hold is later
    # reconciled with measured usage, and a stale held hold can be released directly.
    env.clock.advance(timedelta(seconds=901))
    assert denied_reason(lambda: reserve(env, inst, 8, ONE)) == "reconciliation_pending"
    assert env.budget.read_budget(inst.id).blocking_hold_count == 2  # holds 5 and 7, both stale
    with env.db.transaction() as conn:
        env.budget.mark_unknown(conn, h5.id)
        settled = env.budget.reconcile(conn, h5.id, MEASURED_TWO)
        env.budget.release(conn, h7.id)
    assert settled.compute_micro_usd == 10000
    assert env.budget.read_budget(inst.id).blocking_hold_count == 0
    assert reserve(env, inst, 8, ONE).state == "held"


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/price_table.py:import_price_table")
def test_price_table_import_is_insert_only_immutable_and_use_time_unavailable_denies(build_env, tmp_path):
    env = build_env()
    auth, inst = env.new_instance(limits=Limits(1_000_000, 1_000_000, 1_000_000, 1_000_000))
    with env.db.transaction() as conn:
        again = import_price_table(conn, EXAMPLE_PRICE_TABLE)  # identical re-import is accepted
        assert effective_version(conn, env.clock.now()).version == again.version == "2026-10-01"
        assert effective_version(conn, env.clock.now() - timedelta(days=365)) is None
        assert cost_micro_usd(again, "compute.minutes", 1) == 5000
    changed = tmp_path / "changed.json"
    changed.write_text(EXAMPLE_PRICE_TABLE.read_text().replace('"micro_usd": 5000', '"micro_usd": 5001'))
    with pytest.raises((AiclError, ValueError)):
        with env.db.transaction() as conn:
            import_price_table(conn, changed)  # same version, different hash is a startup failure

    # triggers reject UPDATE and DELETE on both price tables
    with env.db.transaction() as conn:
        for table in ("price_table_version", "price_rate"):
            for sql in (f"UPDATE {table} SET rowid = rowid", f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.DatabaseError):
                    conn.execute(sql)

    # no version effective at use time denies with price_unavailable (never a default price)
    env.clock.set(env.clock.now().replace(year=2020))
    assert denied_reason(lambda: reserve(env, inst, 1)) == "price_unavailable"

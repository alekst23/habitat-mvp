"""Slice 4: WorkRequestRecord, outcomes, late settle, reconciler, O-1 audit atomicity, routes, startup."""

from __future__ import annotations

from datetime import timedelta

import pytest

import seams
from aicl.app import FIXTURE_CSRF_TOKEN, create_app
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.control.instances import Limits
from aicl.settings import Settings
from aicl.work.models import ExecutorOutcome, StillUnknown, WorkRequest
from aicl.work.ports import FakeWorkExecutor
from support import STARTUP_FAILURES, Abort, work_id

GENEROUS = Limits(1_000_000, 10_000_000, 1_000_000, 10_000_000)
EST = Estimate(0, 0, 2)  # reserves 10000 micro-USD of compute


def setup(build_env, executor=None, limits=GENEROUS, **env_kwargs):
    env = build_env(**env_kwargs)
    ex = executor or FakeWorkExecutor()
    gate = seams.work_gate(env, ex, None)
    ops = seams.instance_operations(env)
    auth, inst = env.new_instance(limits=limits, capabilities=("inference",))
    ops.set_lifecycle(auth, inst.id, 1, "activate")
    return env, ex, gate, auth, inst


def request(inst, n, sim=None, estimate=EST, payload_extra=None):
    payload = {"sim": sim or {}, **(payload_extra or {})}
    return WorkRequest(instance_id=inst.id, work_id=work_id(n), capability="inference", payload=payload,
                       estimate=estimate)


def record(env, inst, n):
    with env.db.reader() as conn:
        (table,) = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%work_request%'")]
        return conn.execute(f"SELECT * FROM {table} WHERE work_id = ?", (work_id(n),)).fetchone()


def day(env, inst):
    return env.budget.read_budget(inst.id).windows["compute"]["day"]


def types(env, auth, inst):
    return [e.event_type for e in reversed(env.audit.list_for_instance(auth, inst.id))]


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:WorkAuthorization")
def test_work_request_record_replay_conflict_and_outcome_updates(build_env):
    env, ex, gate, auth, inst = setup(build_env)
    done = gate.authorize_and_dispatch(auth, request(inst, 1, {"compute_minutes": 1}))
    assert done.outcome == "succeeded" and done.hold_state == "settled" and done.usage.compute_micro_usd == 5000
    assert record(env, inst, 1)["outcome"] == "succeeded" and record(env, inst, 1)["tenant_id"] == auth.tenant_id
    replay = gate.authorize_and_dispatch(auth, request(inst, 1, {"compute_minutes": 1}))
    assert replay == done and len(ex.started) == 1 and day(env, inst).settled == 5000  # no second dispatch or charge
    with pytest.raises(AiclError) as e:  # same work_id, different digest
        gate.authorize_and_dispatch(auth, request(inst, 1, {"compute_minutes": 2}))
    assert e.value.error == "conflict"
    assert day(env, inst).settled == 5000 and len(ex.started) == 1

    failed = gate.authorize_and_dispatch(auth, request(inst, 2, {"outcome": "failed", "compute_minutes": 2}))
    assert failed.outcome == "failed" and failed.usage.compute_micro_usd == 10000 and record(env, inst, 2)["outcome"] == "failed"
    nostart = gate.authorize_and_dispatch(auth, request(inst, 3, {"outcome": "not_started"}))
    assert nostart.hold_state == "released" and record(env, inst, 3)["outcome"] == "released"
    assert day(env, inst).held == 0
    unknown = gate.authorize_and_dispatch(auth, request(inst, 4, {"outcome": "unknown"}))
    assert unknown.outcome == "unknown" and unknown.hold_state == "unknown" and record(env, inst, 4)["outcome"] == "unknown"
    assert day(env, inst).held == 10000  # an unknown outcome keeps its full reservation
    blocked = gate.authorize_and_dispatch(auth, request(inst, 5))
    assert blocked.outcome == "denied" and blocked.denial_reason == "reconciliation_pending"

    class Boom(FakeWorkExecutor):
        def execute(self, work):
            raise TimeoutError("executor timeout")

    env2, _, gate2, auth2, inst2 = setup(build_env, Boom())  # exception or timeout => unknown, hold retained
    result = gate2.authorize_and_dispatch(auth2, request(inst2, 1))
    assert result.outcome == "unknown" and day(env2, inst2).held == 10000


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:BudgetAuditRecorder")
def test_over_measured_usage_is_recorded_in_full_gates_next_dispatch_and_audits_budget_events(build_env):
    env, ex, gate, auth, inst = setup(build_env, limits=Limits(1_000_000, 1_000_000, 20_000, 20_000))
    over = gate.authorize_and_dispatch(auth, request(inst, 1, {"compute_minutes": 5}))  # estimate 2, measured 5
    assert over.outcome == "succeeded" and over.usage.compute_micro_usd == 25000 and day(env, inst).settled == 25000
    assert {"budget.reserved", "work.dispatched", "budget.settled", "budget.overrun"} <= set(types(env, auth, inst))
    events = env.audit.list_for_instance(auth, inst.id)
    reserved = [e for e in events if e.event_type == "budget.reserved"][0]
    assert reserved.details["micro_usd"] == 10000 and reserved.details["price_table_version"] == "2026-10-01"
    assert reserved.seq < [e for e in events if e.event_type == "budget.settled"][0].seq
    nxt = gate.authorize_and_dispatch(auth, request(inst, 2))  # window now exceeds its limit: gated at the next dispatch
    assert nxt.denial_reason == "budget_exhausted"
    assert env.instances.get(auth, inst.id).gated_reason == "budget_exhausted"
    ops = seams.instance_operations(env)
    with pytest.raises(AiclError) as e:  # a rollover never clears; the control still denies
        env.clock.advance(timedelta(days=40))
        ops.resolve_gate(auth, inst.id, env.instances.get(auth, inst.id).version)
    assert e.value.error == "denied" and e.value.extra["reason"] == "gate_unresolved"


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:BudgetAuditRecorder")
def test_budget_audit_rows_are_written_in_the_same_unit_of_work_and_roll_back_with_it(build_env):
    env = build_env()
    recorder = seams.budget_audit_recorder(env)
    auth, inst = env.new_instance(limits=GENEROUS)
    count = lambda: len(env.audit.list_for_instance(auth, inst.id))

    with pytest.raises(Abort):  # a rolled-back reservation leaves neither hold nor budget.reserved row
        with env.db.transaction() as conn:
            hold = env.budget.reserve(conn, inst.id, work_id(1), EST)
            recorder.reserved(conn, auth, hold)
            assert count() == 0 and conn.execute("SELECT count(*) FROM audit_event WHERE event_type = 'budget.reserved'").fetchone()[0] == 1
            raise Abort()
    assert count() == 0 and day(env, inst).held == 0

    with env.db.transaction() as conn:
        hold = env.budget.reserve(conn, inst.id, work_id(2), EST)
        recorder.reserved(conn, auth, hold)
    with pytest.raises(Abort):  # a rolled-back settlement leaves no usage and no settled/overrun row
        with env.db.transaction() as conn:
            usage = env.budget.settle(conn, hold.id, MeasuredUsage(0, 0, 5))
            recorder.settled(conn, auth, hold, usage)
            recorder.overrun(conn, auth, hold, usage)
            raise Abort()
    assert [e.event_type for e in env.audit.list_for_instance(auth, inst.id)] == ["budget.reserved"]
    assert day(env, inst).held == 10000 and day(env, inst).settled == 0

    with env.db.transaction() as conn:  # committed together: unknown, then reconciled
        env.budget.mark_unknown(conn, hold.id)
        recorder.unknown(conn, auth, hold)
        usage = env.budget.reconcile(conn, hold.id, MeasuredUsage(0, 0, 1))
        recorder.reconciled(conn, auth, hold, usage)
    assert [e.event_type for e in reversed(env.audit.list_for_instance(auth, inst.id))] == \
        ["budget.reserved", "budget.unknown", "budget.reconciled"]
    assert all(set(e.details) <= {"hold_id", "micro_usd", "price_table_version"} for e in env.audit.list_for_instance(auth, inst.id))


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:HoldReconciler")
def test_reconciler_run_once_settles_releases_and_leaves_still_unknown_blocking(build_env):
    env, ex, gate, auth, inst = setup(build_env, hold_stale_seconds=900)
    rec = seams.hold_reconciler(env, ex)
    gate.authorize_and_dispatch(auth, request(inst, 1, {"outcome": "unknown"}))  # executor stored an unknown outcome
    ex.outcomes[work_id(1)] = ExecutorOutcome("succeeded", MeasuredUsage(0, 0, 1))  # later known
    rec.run_once()
    assert record(env, inst, 1)["outcome"] == "succeeded" and day(env, inst).settled == 5000 and day(env, inst).held == 0
    assert "budget.reconciled" in types(env, auth, inst)

    gate.authorize_and_dispatch(auth, request(inst, 2, {"outcome": "unknown"}))
    ex.outcomes.pop(work_id(2))
    ex.started.add(work_id(2))  # started, no recorded result => still_unknown: hold stays and keeps blocking
    assert isinstance(ex.lookup(work_id(2)), StillUnknown)
    rec.run_once()
    assert env.budget.read_budget(inst.id).blocking_hold_count == 1 and day(env, inst).held == 10000
    assert gate.authorize_and_dispatch(auth, request(inst, 3)).denial_reason == "reconciliation_pending"
    ex.started.discard(work_id(2))  # the executor now reports not_started: release the unknown hold with no usage
    rec.run_once()
    assert env.budget.read_budget(inst.id).blocking_hold_count == 0 and day(env, inst).held == 0

    with env.db.transaction() as conn:  # crash between reserve and execute: stale held hold, work_id never seen
        env.budget.reserve(conn, inst.id, work_id(9), EST)
    env.clock.advance(timedelta(seconds=899))
    rec.run_once()
    assert day(env, inst).held == 10000  # not stale yet
    env.clock.advance(timedelta(seconds=2))
    assert gate.authorize_and_dispatch(auth, request(inst, 10)).denial_reason == "reconciliation_pending"
    rec.run_once()
    assert day(env, inst).held == 0 and env.budget.read_budget(inst.id).blocking_hold_count == 0
    ex2 = FakeWorkExecutor()
    with env.db.transaction() as conn:  # stale held whose work did start and finished: reconcile with measured usage
        env.budget.reserve(conn, inst.id, work_id(11), EST)
    ex2.started.add(work_id(11))
    ex2.outcomes[work_id(11)] = ExecutorOutcome("succeeded", MeasuredUsage(0, 0, 2))
    env.clock.advance(timedelta(seconds=901))
    seams.hold_reconciler(env, ex2).run_once()
    assert day(env, inst).settled == 5000 + 10000 and day(env, inst).held == 0


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:HoldReconciler")
def test_late_settle_of_a_released_hold_is_conflict_with_audit_and_reconciler_exception_is_audited(build_env):
    env, ex, gate, auth, inst = setup(build_env)
    with env.db.transaction() as conn:
        hold = env.budget.reserve(conn, inst.id, work_id(1), EST)
    rec = seams.hold_reconciler(env, ex)
    env.clock.advance(timedelta(seconds=901))
    rec.run_once()  # never seen => released
    with pytest.raises(AiclError) as e:
        with env.db.transaction() as conn:
            env.budget.settle(conn, hold.id, MeasuredUsage(0, 0, 1))  # the original run finishes late
    assert e.value.error == "conflict"
    assert types(env, auth, inst).count("budget.late_settlement") == 1 and day(env, inst).settled == 0

    class Broken(FakeWorkExecutor):
        def lookup(self, work_id):
            raise RuntimeError("lookup down")

    with env.db.transaction() as conn:
        env.budget.reserve(conn, inst.id, work_id(2), EST)
    env.clock.advance(timedelta(seconds=901))
    seams.hold_reconciler(env, Broken()).run_once()  # must not raise; holds keep blocking
    assert env.budget.read_budget(inst.id).blocking_hold_count >= 1
    assert gate.authorize_and_dispatch(auth, request(inst, 3)).denial_reason == "reconciliation_pending"


@pytest.fixture
def started_app(base_env, tmp_path):
    from fastapi.testclient import TestClient
    settings = Settings.from_env({**base_env, "AICL_ENVIRONMENT": "test", "AICL_TEST_MODE": "1",
                                  "AICL_DATABASE_URL": f"sqlite:///{tmp_path / 'routes.db'}"})
    return settings, TestClient


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:WorkAuthorization")
def test_work_request_and_confirm_routes_require_session_csrf_and_return_gated_denials(started_app):
    settings, TestClient = started_app
    app = create_app(settings)
    headers = {"x-csrf-token": FIXTURE_CSRF_TOKEN, "origin": settings.public_base_url}
    with TestClient(app) as a, TestClient(app) as b, TestClient(app) as anon:
        a.post("/__test__/seed-session", json={"fixture": "owner-a"})
        b.post("/__test__/seed-session", json={"fixture": "owner-b"})
        made = a.post("/app-tools/create_instance", headers=headers, json={
            "idempotency_key": "wiz_" + "e" * 32, "template_id": "default", "name": "N", "instructions": "",
            "enabled_capabilities": ["gmail.send"]}).json()["instance"]
        url = f"/instances/{made['id']}/work-requests"
        body = {"work_id": "work_" + "f" * 32, "capability": "gmail.send", "payload": {"to": "x@example.com"},
                "estimate": {"inference_input_tokens": 0, "inference_output_tokens": 0, "compute_minutes": 1}}
        assert anon.post(url, json=body, headers=headers).status_code == 401
        assert a.post(url, json=body).status_code == 403  # no CSRF token
        assert b.post(url, json=body, headers=headers).status_code == 404  # another tenant
        denied = a.post(url, json=body, headers=headers)  # draft instance => gated/denied
        assert denied.status_code == 403 and denied.json()["reason"] == "instance_not_active"
        assert "x@example.com" not in denied.text
        assert a.post("/pending-actions/00000000-0000-4000-8000-000000000000/confirm", headers=headers).status_code == 404
        assert anon.post("/pending-actions/x/confirm", headers=headers).status_code == 401
        assert a.post("/pending-actions/x/confirm").status_code == 403  # CSRF required


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/settings.py:Settings")
def test_startup_rejects_non_fake_modes_and_registers_e11_2_hooks_in_order(base_env, tmp_path):
    for name in ("AICL_PROVIDER_MODE", "AICL_EXECUTOR_MODE"):
        with pytest.raises(STARTUP_FAILURES) as err:
            create_app(Settings.from_env({**base_env, name: "real"}))
        assert "real" not in str(err.value) or "enablement" in str(err.value) or "fake" in str(err.value)
    from aicl import hooks, ports, routes
    assert "secret_store" in ports.REQUIRED_PORTS and "work_executor" in ports.REQUIRED_PORTS
    assert len(routes.ROUTE_FACTORIES) >= 1 and len(hooks.STARTUP_HOOKS) == 2  # sweeper first, then reconciler
    names = [getattr(h, "__name__", type(h).__name__).lower() for h in hooks.STARTUP_HOOKS]
    assert "sweep" in names[0] and "reconcil" in names[1], names

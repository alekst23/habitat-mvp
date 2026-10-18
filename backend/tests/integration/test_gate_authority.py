"""Dispatch honors durable gates and owner changes committed before reservation."""
from datetime import timedelta

import pytest

import seams
from aicl.control.budget import Estimate
from aicl.control.instances import Limits
from aicl.network.policy import FakeResolver
from aicl.work.models import WorkRequest
from aicl.work.ports import FakeWorkExecutor
from support import work_id


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:WorkAuthorization")
def test_budget_rollover_does_not_clear_persisted_gate(build_env):
    env = build_env()
    ops = seams.instance_operations(env)
    auth, instance = env.new_instance(limits=Limits(1000, 1000, 5000, 5000), capabilities=("inference",))
    ops.set_lifecycle(auth, instance.id, 1, "activate")
    executor = FakeWorkExecutor(db=env.db)
    gate = seams.work_gate(env, executor, FakeResolver({}))

    def request(n):
        return WorkRequest(instance_id=instance.id, work_id=work_id(n), capability="inference", payload={}, estimate=Estimate(0, 0, 1))

    assert gate.authorize_and_dispatch(auth, request(701)).outcome == "succeeded"
    assert gate.authorize_and_dispatch(auth, request(702)).denial_reason == "budget_exhausted"
    env.clock.advance(timedelta(days=40))
    assert gate.authorize_and_dispatch(auth, request(703)).denial_reason == "budget_exhausted"
    assert len(executor.started) == 1
    current = env.instances.get(auth, instance.id)
    ops.set_limits(auth, instance.id, current.version, Limits(1000, 1000, 10000, 10000))
    assert gate.authorize_and_dispatch(auth, request(703)).outcome == "succeeded"


@pytest.mark.ac("E11-2.AC1", code="backend/aicl/work/gate.py:WorkAuthorization")
@pytest.mark.parametrize("change,reason", [("pause", "instance_not_active"),
                                          ("capability", "capability_disabled"),
                                          ("limits", "check_unavailable")])
def test_owner_change_between_checks_and_reservation_prevents_dispatch(build_env, change, reason):
    env = build_env()
    ops = seams.instance_operations(env)
    auth, instance = env.new_instance(capabilities=("inference",))
    ops.set_lifecycle(auth, instance.id, 1, "activate")
    executor = FakeWorkExecutor(db=env.db)
    gate = seams.work_gate(env, executor, FakeResolver({}))
    original = gate._check_network

    def change_after_checks(checked, request):
        destination = original(checked, request)
        if change == "pause":
            ops.set_lifecycle(auth, instance.id, checked.version, "pause")
        elif change == "capability":
            ops.set_capability(auth, instance.id, checked.version, "inference", False)
        else:
            ops.set_limits(auth, instance.id, checked.version, Limits())
        return destination

    gate._check_network = change_after_checks
    request = WorkRequest(instance_id=instance.id, work_id=work_id(704), capability="inference", payload={}, estimate=Estimate(0, 0, 1))
    result = gate.authorize_and_dispatch(auth, request)
    assert result.outcome == "denied" and result.denial_reason == reason
    assert not executor.started
    with env.db.reader() as conn:
        assert conn.execute("SELECT count(*) FROM budget_hold").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM work_request_record").fetchone()[0] == 0

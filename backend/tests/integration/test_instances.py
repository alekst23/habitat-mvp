"""Instance and grant repositories on real SQLite: tenant isolation and persisted gate state."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from aicl.control.auth import AuthContext
from aicl.control.errors import AiclError
from aicl.control.instances import CATALOG_CAPABILITIES, GateContext, Limits
from support import Abort


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/instances.py:SqliteInstanceRepository")
def test_repository_is_tenant_isolated_defaults_to_zero_limits_and_rolls_back_with_its_transaction(build_env):
    env = build_env()
    auth, inst = env.new_instance(limits=Limits(), capabilities=("gmail.send",))
    stranger = AuthContext("00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000001", "s",
                           datetime(2100, 1, 1, tzinfo=timezone.utc))

    got = env.instances.get(auth, inst.id)
    assert got.lifecycle == "draft" and got.version == 1 and got.limits == Limits(0, 0, 0, 0)
    assert got.gated_reason is None and got.tenant_id == auth.tenant_id and got.owner_id == auth.owner_id
    grants = {g.capability: g.enabled for g in env.instances.get_grants(auth, inst.id)}
    assert set(grants) == set(CATALOG_CAPABILITIES) and [c for c, on in grants.items() if on] == ["gmail.send"]

    # Another tenant's instance is indistinguishable from a missing one, for reads and for writes.
    missing = "11111111-1111-4111-8111-111111111111"
    for call in (lambda: env.instances.get(stranger, inst.id), lambda: env.instances.get(auth, missing),
                 lambda: env.instances.get_grants(stranger, inst.id)):
        with pytest.raises(AiclError) as err:
            call()
        assert err.value.error == "not_found"
    for write in (lambda c: env.instances.set_gated(c, stranger, inst.id, "capability_disabled", GateContext()),
                  lambda c: env.instances.clear_gated(c, stranger, inst.id)):
        with pytest.raises(AiclError) as err:
            with env.db.transaction() as conn:
                write(conn)
        assert err.value.error == "not_found"

    # A rolled-back unit of work leaves no instance.
    ghost_id = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(Abort):
        with env.db.transaction() as conn:
            env.instances.insert_draft(conn, auth, replace(inst, id=ghost_id), ())
            raise Abort()
    with pytest.raises(AiclError) as err:
        env.instances.get(auth, ghost_id)
    assert err.value.error == "not_found"


@pytest.mark.ac("E11-1.AC1", code="backend/aicl/control/instances.py:SqliteInstanceRepository")
def test_gate_state_persists_across_daily_and_monthly_rollover_until_cleared(build_env):
    env = build_env(start=datetime(2026, 10, 30, 23, 0, tzinfo=timezone.utc))
    auth, inst = env.new_instance()
    context = GateContext(capabilities=("gmail.send",), host_hash12=None)
    with env.db.transaction() as conn:
        gated = env.instances.set_gated(conn, auth, inst.id, "capability_disabled", context)
    assert gated.gated_reason == "capability_disabled" and gated.gate_context == context

    for delta in (timedelta(hours=2), timedelta(days=32)):  # next UTC day, then next month
        env.clock.advance(delta)
        persisted = env.instances.get(auth, inst.id)
        assert persisted.gated_reason == "capability_disabled" and persisted.gate_context == context

    with env.db.transaction() as conn:
        cleared = env.instances.clear_gated(conn, auth, inst.id)
    assert cleared.gated_reason is None and cleared.gate_context is None
    assert env.instances.get(auth, inst.id).gated_reason is None

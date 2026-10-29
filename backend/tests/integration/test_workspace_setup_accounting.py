"""Setup costs stay scoped and auditable when waived or charged at activation."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import sqlite3
import uuid

import pytest

from aicl.agent_workspace.assistant import WorkspaceAssistantService
from aicl.agent_workspace.service import WorkspaceService
from aicl.chat.assistant_meter import AssistantMeter, RESERVATION, allowance
from aicl.chat.assistant_service import AssistantService
from aicl.control.errors import AiclError
from aicl.db import to_iso
from test_workspace_execution import setup


def attempt(ctx, auth, workspace_id, *, input_tokens=100, output_tokens=40, outcome="settled"):
    state = WorkspaceService(ctx).view(auth, workspace_id)
    turn, _ = AssistantService(ctx)._claim(auth, state["session_id"], str(uuid.uuid4()), "A setup edit")
    meter = AssistantMeter(ctx, auth, turn)
    identity = meter.reserve()
    if outcome == "settled":
        meter.settle(identity, "response_" + identity, "gpt-6-sol", input_tokens, output_tokens)
    elif outcome == "unknown":
        meter.fail(identity, no_charge=False, reason="provider_unknown")
    if outcome != "held":
        with ctx.db.transaction() as conn:
            conn.execute("UPDATE assistant_turn SET state=? WHERE id=?", ("completed" if outcome == "settled" else "unknown", turn))
    return identity


def test_workspace_usage_is_scoped_while_operator_allowance_remains_global(build_env, base_env):
    _, ctx, auth, _, identity, _, _ = setup(build_env, base_env)
    other = WorkspaceService(ctx).open(auth)
    attempt(ctx, auth, identity)
    attempt(ctx, auth, other["id"], input_tokens=200, output_tokens=60)
    state = WorkspaceService(ctx).view(auth, identity)
    displayed = WorkspaceAssistantService(ctx, identity).view(auth, state["session_id"])["usage"]
    assert displayed["spent_micro_usd"] == 600
    assert displayed["scope"] == "workspace" and displayed["workspace_id"] == identity
    assert displayed["pending_micro_usd"] == 600 and displayed["held_micro_usd"] == 0
    assert "cap_micro_usd" not in displayed
    assert allowance(ctx.db, ctx.settings.assistant_max_spend_micro_usd)["spent_micro_usd"] == 1600


def test_waiver_preserves_provider_history_and_new_cost_charges_once(build_env, base_env):
    from aicl.agent_workspace.setup_accounting import WorkspaceSetupAccounting, balance_cost
    env, ctx, auth, inst, identity, _, _ = setup(build_env, base_env)
    accounting = WorkspaceSetupAccounting(ctx)
    old_attempt = attempt(ctx, auth, identity)
    with env.db.reader() as conn:
        original = dict(conn.execute("SELECT * FROM assistant_inference_attempt WHERE id=?", (old_attempt,)).fetchone())
    waived = accounting.waive(auth, identity, "reset-setup", "owner_requested_reset")
    assert waived["spent_micro_usd"] == waived["pending_micro_usd"] == 0
    assert waived["waived_micro_usd"] == 600
    new_attempt = attempt(ctx, auth, identity, input_tokens=200, output_tokens=60)
    assert accounting.waive(auth, identity, "reset-setup", "owner_requested_reset")["pending_micro_usd"] == 1000
    with pytest.raises(AiclError, match="conflict"):
        accounting.waive(auth, identity, "reset-setup", "different_reason")
    with env.db.transaction() as conn:
        before = conn.total_changes
        assert balance_cost(conn, inst.id) == 1000
        assert accounting.view(auth, identity)["pending_micro_usd"] == 1000
        assert conn.total_changes == before
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: WorkspaceSetupAccounting(ctx).charge(auth, identity), range(3)))
    assert all(item["charged_micro_usd"] == 1000 and item["pending_micro_usd"] == 0 for item in results)
    assert accounting.waive(auth, identity, "reset-after-charge", "owner_requested_reset")["charged_micro_usd"] == 1000
    with env.db.reader() as conn:
        assert balance_cost(conn, inst.id) == 1000
        assert dict(conn.execute("SELECT * FROM assistant_inference_attempt WHERE id=?", (old_attempt,)).fetchone()) == original
        assert conn.execute("SELECT COUNT(*) FROM workspace_setup_charge WHERE attempt_id=?", (new_attempt,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM workspace_setup_waiver WHERE attempt_id=?", (old_attempt,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM audit_event WHERE json_extract(details,'$.action')='workspace_setup_waived'").fetchone()[0] == 2
    assert allowance(env.db, ctx.settings.assistant_max_spend_micro_usd)["spent_micro_usd"] == 1600
    for statement, values in (
        ("DELETE FROM workspace_setup_charge WHERE attempt_id=?", (new_attempt,)),
        ("UPDATE workspace_setup_waiver SET cost_micro_usd=0 WHERE attempt_id=?", (old_attempt,)),
        ("INSERT INTO workspace_setup_charge SELECT ?,workspace_id,?,cost_micro_usd,created_at FROM workspace_setup_waiver WHERE attempt_id=?",
         (old_attempt, inst.id, old_attempt)),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            with env.db.transaction() as conn:
                conn.execute(statement, values)


def test_unknown_and_inflight_setup_keep_holds_and_block_activation(build_env, base_env):
    from aicl.agent_workspace.setup_accounting import WorkspaceSetupAccounting, balance_cost
    env, ctx, auth, inst, identity, _, _ = setup(build_env, base_env)
    accounting = WorkspaceSetupAccounting(ctx)
    attempt(ctx, auth, identity)
    pending = attempt(ctx, auth, identity, outcome="held")
    accounting.waive(auth, identity, "waive-known-only", "owner_requested_reset")
    assert accounting.view(auth, identity)["held_micro_usd"] == RESERVATION
    with pytest.raises(AiclError) as caught:
        accounting.charge(auth, identity)
    assert caught.value.extra["reason"] == "setup_in_progress"
    with env.db.transaction() as conn:
        conn.execute("UPDATE assistant_turn SET state='unknown' WHERE id=(SELECT turn_id FROM assistant_inference_attempt WHERE id=?)", (pending,))
        conn.execute("UPDATE assistant_inference_attempt SET state='unknown' WHERE id=?", (pending,))
    with pytest.raises(AiclError) as caught:
        accounting.charge(auth, identity)
    assert caught.value.extra["reason"] == "setup_unresolved"
    with env.db.reader() as conn:
        assert balance_cost(conn, inst.id) == RESERVATION
        assert conn.execute("SELECT state FROM assistant_inference_attempt WHERE id=?", (pending,)).fetchone()[0] == "unknown"
        assert conn.execute("SELECT COUNT(*) FROM workspace_setup_charge").fetchone()[0] == 0
    operator = allowance(env.db, ctx.settings.assistant_max_spend_micro_usd)
    assert operator["spent_micro_usd"] == 600 and operator["held_micro_usd"] == RESERVATION and operator["unknown"]
    foreign = replace(auth, owner_id=str(uuid.uuid4()))
    for action in (lambda: accounting.view(foreign, identity), lambda: accounting.charge(foreign, identity),
                   lambda: accounting.waive(foreign, identity, "foreign", "owner_requested_reset")):
        with pytest.raises(AiclError, match="not_found"):
            action()


def test_setup_cannot_charge_unfunded_and_charge_rolls_back_with_activation(build_env, base_env):
    from aicl.agent_workspace.setup_accounting import WorkspaceSetupAccounting
    env, ctx, auth, inst, identity, _, _ = setup(build_env, base_env, funded=False)
    accounting = WorkspaceSetupAccounting(ctx)
    attempt(ctx, auth, identity)
    with pytest.raises(AiclError) as caught:
        accounting.charge(auth, identity)
    assert caught.value.extra["reason"] == "credit_insufficient"
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM workspace_setup_charge").fetchone()[0] == 0
    commerce = ctx.agent_runtime.accounting.commerce
    order = commerce.create_topup(auth, inst.id, 500, "fund-setup")
    commerce.select_payment_buyer(auth, order["id"], "demo-buyer")
    commerce.checkout(auth, order["id"], "complete")
    with pytest.raises(RuntimeError, match="activation failed"):
        with env.db.transaction():
            assert accounting.charge(auth, identity)["charged_micro_usd"] == 600
            raise RuntimeError("activation failed")
    assert accounting.view(auth, identity)["pending_micro_usd"] == 600
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM workspace_setup_charge").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM audit_event WHERE json_extract(details,'$.action')='workspace_setup_charged'").fetchone()[0] == 0


def legacy_proposal(conn, auth, session_id, instance_id, now):
    conn.execute("INSERT INTO assistant_proposal(id,session_id,tenant_id,owner_id,version,kind,data_json,state,instance_id,created_at,updated_at) "
                 "VALUES (?,?,?,?,1,'create','{}','committed',?,?,?)",
                 (str(uuid.uuid4()), session_id, auth.tenant_id, auth.owner_id, instance_id, now, now))


def legacy_setup(build_env, base_env, *, ambiguous):
    env, ctx, auth, inst, identity, _, _ = setup(build_env, base_env)
    core = WorkspaceService(ctx)
    session = core.view(auth, identity)["session_id"]
    attempt(ctx, auth, identity)
    attempt(ctx, auth, identity, input_tokens=200, output_tokens=60)
    with env.db.transaction() as conn:
        other = env.instances.insert_draft(conn, auth, replace(inst, id=str(uuid.uuid4()), name="Another agent"), ())
        legacy_proposal(conn, auth, session, inst.id, to_iso(env.clock.now()))
        if ambiguous:
            legacy_proposal(conn, auth, session, other.id, to_iso(env.clock.now()))
        # Model a conversation saved by the old creator, before workspaces existed.
        conn.execute("DELETE FROM agent_workspace WHERE id=?", (identity,))
    env.clock.set(env.clock.now() + timedelta(minutes=1))
    return env, ctx, auth, inst, other, session


def test_ambiguous_legacy_session_costs_stay_global_and_new_agent_edits_are_scoped(build_env, base_env):
    from aicl.agent_workspace.setup_accounting import WorkspaceSetupAccounting
    env, ctx, auth, first_instance, second_instance, session = legacy_setup(build_env, base_env, ambiguous=True)
    core, accounting = WorkspaceService(ctx), WorkspaceSetupAccounting(ctx)
    first = core.open(auth, instance_id=first_instance.id)
    second = core.open(auth, instance_id=second_instance.id)
    assert first["session_id"] == session and second["session_id"] != session
    assert accounting.view(auth, first["id"])["spent_micro_usd"] == 0
    assert accounting.view(auth, second["id"])["spent_micro_usd"] == 0
    assert len(WorkspaceAssistantService(ctx, first["id"]).view(auth, session)["messages"]) == 2
    attempt(ctx, auth, first["id"], input_tokens=300, output_tokens=60)
    attempt(ctx, auth, second["id"], input_tokens=50, output_tokens=30)
    assert accounting.view(auth, first["id"])["spent_micro_usd"] == 1200
    assert accounting.view(auth, second["id"])["spent_micro_usd"] == 400
    assert accounting.charge(auth, first["id"])["charged_micro_usd"] == 1200
    assert allowance(env.db, ctx.settings.assistant_max_spend_micro_usd)["spent_micro_usd"] == 3200
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assistant_inference_attempt").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM assistant_message WHERE session_id=?", (session,)).fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM workspace_setup_charge").fetchone()[0] == 1


@pytest.mark.parametrize("receipt", ["charge", "waive"])
def test_later_legacy_ambiguity_never_unassigns_existing_charge_or_waiver(build_env, base_env, receipt):
    from aicl.agent_workspace.setup_accounting import WorkspaceSetupAccounting, balance_cost
    env, ctx, auth, instance, other, session = legacy_setup(build_env, base_env, ambiguous=False)
    state = WorkspaceService(ctx).open(auth, instance_id=instance.id)
    accounting = WorkspaceSetupAccounting(ctx)
    assert accounting.view(auth, state["id"])["pending_micro_usd"] == 1600
    before = (accounting.charge(auth, state["id"]) if receipt == "charge" else
              accounting.waive(auth, state["id"], "known-legacy-reset", "owner_requested_reset"))
    with env.db.transaction() as conn:
        legacy_proposal(conn, auth, session, other.id, to_iso(env.clock.now()))
    assert accounting.view(auth, state["id"]) == before
    with env.db.reader() as conn:
        assert balance_cost(conn, instance.id) == (1600 if receipt == "charge" else 0)
    assert allowance(env.db, ctx.settings.assistant_max_spend_micro_usd)["spent_micro_usd"] == 1600

"""Setup usage is funded once before workspace activation and execution."""
import uuid

import pytest

from aicl.agent_workspace.execution import WorkspaceExecution
from aicl.agent_runtime.worker import LocalRuntimeWorker
from aicl.agent_runtime.adapters import ScriptedModel
from aicl.agent_runtime.chat_service import RuntimeChatService
from aicl.chat.assistant_meter import allowance
from aicl.control.budget import Estimate
from aicl.control.errors import AiclError
from aicl.creation.operations import SqliteInstanceOperations
from aicl.db import to_iso
from test_workspace_execution import complete, setup


def record_setup(env, auth, workspace_id, *, cost=600_000, state="settled"):
    turn_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = to_iso(env.clock.now())
    with env.db.transaction() as conn:
        session_id = conn.execute("SELECT session_id FROM agent_workspace WHERE id=?", (workspace_id,)).fetchone()[0]
        conn.execute("INSERT INTO assistant_turn(id,session_id,request_id,user_text,state,created_at,updated_at) "
                     "VALUES (?,?,?,?,?,?,?)", (turn_id, session_id, turn_id, "Configure this agent", "running" if state == "held" else "completed", now, now))
        conn.execute("INSERT INTO assistant_inference_attempt(id,turn_id,tenant_id,owner_id,state,reserved_micro_usd,"
                     "cost_micro_usd,price_version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (attempt_id, turn_id, auth.tenant_id, auth.owner_id, state, cost,
                      cost if state == "settled" else None, "setup-test", now, now))
    return attempt_id


def set_lifecycle(env, instance_id, value):
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET lifecycle=? WHERE id=?", (value, instance_id))


@pytest.mark.parametrize("action", ["start", "schedule", "activate", "resume"])
def test_funded_activation_charges_setup_once_and_preserves_run_credit(build_env, base_env, action):
    env, ctx, auth, instance, workspace_id, model, _ = setup(build_env, base_env)
    service = WorkspaceExecution(ctx)
    set_lifecycle(env, instance.id, "paused" if action == "resume" else "draft")
    record_setup(env, auth, workspace_id)
    before = service.view(auth, workspace_id)["readiness"]
    assert before["setup"]["pending_micro_usd"] == 600_000
    assert before["balance_micro_usd"] == 4_400_000
    assert before["credit_before_setup_micro_usd"] == 5_000_000
    assert before["activation_required_micro_usd"] == 600_400
    if action == "start":
        run = service.start(auth, workspace_id, "launch")
        assert service.start(auth, workspace_id, "launch")["id"] == run["id"]
    elif action == "schedule":
        service.schedule(auth, workspace_id, True, 1)
        service.schedule(auth, workspace_id, True, 2)
    else:
        service.lifecycle(auth, workspace_id, action, 1)
    after = service.view(auth, workspace_id)["readiness"]
    assert after["setup"]["charged_micro_usd"] == 600_000
    assert after["setup"]["pending_micro_usd"] == 0
    assert after["balance_micro_usd"] == before["balance_micro_usd"]
    assert after["activation_required_micro_usd"] == 400
    assert model.calls == []
    with env.db.reader() as conn:
        assert conn.execute("SELECT lifecycle FROM agent_instance WHERE id=?", (instance.id,)).fetchone()[0] == "active"
        assert conn.execute("SELECT SUM(delta_micro_usd) FROM mock_commerce_ledger WHERE instance_id=?", (instance.id,)).fetchone()[0] == 5_000_000
        assert conn.execute("SELECT state,cost_micro_usd FROM assistant_inference_attempt").fetchone()[:] == ("settled", 600_000)


@pytest.mark.parametrize("action", ["start", "schedule", "activate", "resume"])
def test_activation_requires_credit_remaining_after_setup(build_env, base_env, action):
    env, ctx, auth, instance, workspace_id, model, _ = setup(build_env, base_env)
    service = WorkspaceExecution(ctx)
    lifecycle = "paused" if action == "resume" else "draft"
    set_lifecycle(env, instance.id, lifecycle)
    record_setup(env, auth, workspace_id, cost=4_999_800)
    with pytest.raises(AiclError) as caught:
        if action == "start":
            service.start(auth, workspace_id, "unfunded")
        elif action == "schedule":
            service.schedule(auth, workspace_id, True, 1)
        else:
            service.lifecycle(auth, workspace_id, action, 1)
    assert caught.value.extra["reason"] == "credit_insufficient"
    state = service.view(auth, workspace_id)
    assert state["readiness"]["balance_micro_usd"] == 200
    assert state["readiness"]["setup"]["charged_micro_usd"] == 0
    assert state["history"] == [] and not state["schedule"]["enabled"] and model.calls == []
    with env.db.reader() as conn:
        assert conn.execute("SELECT lifecycle FROM agent_instance WHERE id=?", (instance.id,)).fetchone()[0] == lifecycle


@pytest.mark.parametrize(("attempt_state", "reason"), [("unknown", "setup_unresolved"), ("held", "setup_in_progress")])
def test_unknown_or_busy_setup_blocks_activation_despite_funded_balance(build_env, base_env, attempt_state, reason):
    env, ctx, auth, instance, workspace_id, model, _ = setup(build_env, base_env)
    set_lifecycle(env, instance.id, "draft")
    record_setup(env, auth, workspace_id, state=attempt_state)
    service = WorkspaceExecution(ctx)
    state = service.view(auth, workspace_id)
    assert reason in {item["reason"] for item in state["readiness"]["blockers"]}
    for operation in (lambda: service.start(auth, workspace_id, "blocked"),
                      lambda: service.schedule(auth, workspace_id, True, 1),
                      lambda: service.lifecycle(auth, workspace_id, "activate", 1)):
        with pytest.raises(AiclError) as caught:
            operation()
        assert caught.value.extra["reason"] == reason
    assert service.view(auth, workspace_id)["readiness"]["setup"]["charged_micro_usd"] == 0
    assert model.calls == []


def test_existing_run_continue_charges_new_setup_once_without_replacing_run(build_env, base_env):
    env, ctx, auth, instance, workspace_id, model, _ = setup(build_env, base_env)
    service = WorkspaceExecution(ctx)
    run = service.start(auth, workspace_id, "launch")
    service.control(auth, workspace_id, run["id"], "pause")
    record_setup(env, auth, workspace_id, cost=600_000)
    service.control(auth, workspace_id, run["id"], "resume")
    record_setup(env, auth, workspace_id, cost=700_000)
    # Retrying the old start is not fresh authorization to charge later edits.
    assert service.start(auth, workspace_id, "launch")["id"] == run["id"]
    assert service.view(auth, workspace_id)["readiness"]["setup"]["pending_micro_usd"] == 700_000
    service.control(auth, workspace_id, run["id"], "advance")
    service.control(auth, workspace_id, run["id"], "resume")
    state = service.view(auth, workspace_id)
    assert state["run"]["id"] == run["id"] and len(state["history"]) == 1
    assert state["readiness"]["setup"]["charged_micro_usd"] == 1_300_000
    assert state["readiness"]["setup"]["pending_micro_usd"] == 0
    assert state["readiness"]["balance_micro_usd"] == 3_700_000 and model.calls == []


@pytest.mark.parametrize("action", ["activate", "resume"])
def test_legacy_lifecycle_cannot_bypass_setup_charge_or_unknown_usage(build_env, base_env, action):
    env, ctx, auth, instance, workspace_id, _, _ = setup(build_env, base_env)
    set_lifecycle(env, instance.id, "draft" if action == "activate" else "paused")
    record_setup(env, auth, workspace_id)
    operations = SqliteInstanceOperations(env.db, env.clock)
    with env.db.reader() as conn:
        version = conn.execute("SELECT version FROM agent_instance WHERE id=?", (instance.id,)).fetchone()[0]
    activated = operations.set_lifecycle(auth, instance.id, version, action)
    paused = operations.set_lifecycle(auth, instance.id, activated.instance.version, "pause")
    resumed = operations.set_lifecycle(auth, instance.id, paused.instance.version, "resume")
    state = WorkspaceExecution(ctx).view(auth, workspace_id)
    assert state["readiness"]["setup"]["charged_micro_usd"] == 600_000
    assert state["readiness"]["balance_micro_usd"] == 4_400_000
    paused = operations.set_lifecycle(auth, instance.id, resumed.instance.version, "pause")
    record_setup(env, auth, workspace_id, state="unknown")
    with pytest.raises(AiclError) as caught:
        operations.set_lifecycle(auth, instance.id, paused.instance.version, "resume")
    assert caught.value.extra["reason"] == "setup_unresolved"
    with env.db.reader() as conn:
        assert conn.execute("SELECT lifecycle FROM agent_instance WHERE id=?", (instance.id,)).fetchone()[0] == "paused"
        assert conn.execute("SELECT COUNT(*) FROM workspace_setup_charge WHERE workspace_id=?", (workspace_id,)).fetchone()[0] == 1


def test_worker_cannot_dispatch_through_unknown_setup_and_cancel_remains_available(build_env, base_env):
    env, ctx, auth, _, workspace_id, model, _ = setup(build_env, base_env)
    service = WorkspaceExecution(ctx)
    run = service.start(auth, workspace_id, "launch")
    record_setup(env, auth, workspace_id, state="unknown")
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    state = service.view(auth, workspace_id)
    assert state["run"]["reason"] == "setup_unresolved" and not state["run"]["can_resume"]
    assert not state["run"]["can_advance"] and model.calls == []
    assert service.control(auth, workspace_id, run["id"], "cancel")["status"] == "cancelled"
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_runtime_hold").fetchone()[0] == 0
        assert conn.execute("SELECT state FROM assistant_inference_attempt").fetchone()[0] == "unknown"


def test_setup_charge_preserves_runtime_hold_and_operator_cost(build_env, base_env):
    env, ctx, auth, instance, workspace_id, _, _ = setup(build_env, base_env)
    service = WorkspaceExecution(ctx)
    run = service.start(auth, workspace_id, "launch")
    record_setup(env, auth, workspace_id)
    accounting = ctx.agent_runtime.accounting
    with env.db.transaction() as conn:
        accounting.reserve(conn, auth, instance.id, "setup-preserve-hold", Estimate(100, 100, 0), 1_000_000, 0)
        hold_before = dict(conn.execute("SELECT * FROM budget_hold WHERE work_id='runtime:setup-preserve-hold'").fetchone())
        assert accounting.commerce._balance(conn, instance.id) == 4_399_600
    operator_before = allowance(env.db, 10_000_000)
    service.control(auth, workspace_id, run["id"], "advance")
    assert allowance(env.db, 10_000_000) == operator_before
    with env.db.reader() as conn:
        assert dict(conn.execute("SELECT * FROM budget_hold WHERE id=?", (hold_before["id"],)).fetchone()) == hold_before
        assert accounting.commerce._balance(conn, instance.id) == 4_399_600
        assert conn.execute("SELECT COUNT(*) FROM workspace_setup_charge WHERE workspace_id=?", (workspace_id,)).fetchone()[0] == 1


@pytest.mark.parametrize("control", ["advance", "resume"])
def test_admitted_run_continues_during_normal_management_reply(build_env, base_env, control):
    env, ctx, auth, _, workspace_id, model, _ = setup(build_env, base_env)
    service = WorkspaceExecution(ctx)
    run = service.start(auth, workspace_id, "launch")
    if control == "resume":
        service.control(auth, workspace_id, run["id"], "pause")
    attempt = record_setup(env, auth, workspace_id, state="held")
    state = service.view(auth, workspace_id)
    assert state["readiness"]["setup"]["busy"] and state["readiness"]["ready"]
    service.control(auth, workspace_id, run["id"], control)
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    assert service.view(auth, workspace_id)["run"]["status"] == "completed" and len(model.calls) == 1
    with env.db.reader() as conn:
        assert conn.execute("SELECT state FROM assistant_inference_attempt WHERE id=?", (attempt,)).fetchone()[0] == "held"
        assert conn.execute("SELECT COUNT(*) FROM workspace_setup_charge WHERE workspace_id=?", (workspace_id,)).fetchone()[0] == 0


def test_management_hold_still_reduces_credit_for_admitted_run(build_env, base_env):
    env, ctx, auth, _, workspace_id, model, _ = setup(build_env, base_env)
    service = WorkspaceExecution(ctx)
    service.start(auth, workspace_id, "launch")
    record_setup(env, auth, workspace_id, cost=4_999_800, state="held")
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    assert service.view(auth, workspace_id)["run"]["reason"] == "credit_insufficient" and model.calls == []


def test_owner_answer_accepts_busy_setup_then_fresh_continuation_charges_settled_usage(build_env, base_env):
    env, ctx, auth, _, workspace_id, _, _ = setup(build_env, base_env)
    model = ScriptedModel([{"schema_version": 1, "control": {"next": "wait_owner", "question": "Which audience?",
                                                            "options": ["Engineering", "General"]}}, complete])
    model.estimate = Estimate(100, 100, 0)
    ctx.agent_runtime.model = model
    service = WorkspaceExecution(ctx)
    run = service.start(auth, workspace_id, "launch")
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    question = service.view(auth, workspace_id)["run"]["question"]["id"]
    attempt = record_setup(env, auth, workspace_id, state="held")
    assert service.message(auth, workspace_id, run["id"], "answer", "Engineering", question)["status"] == "queued"
    with env.db.transaction() as conn:
        conn.execute("UPDATE assistant_inference_attempt SET state='settled',cost_micro_usd=600000 WHERE id=?", (attempt,))
        conn.execute("UPDATE assistant_turn SET state='completed' WHERE id=(SELECT turn_id FROM assistant_inference_attempt WHERE id=?)", (attempt,))
    # A replay accepts the old answer but does not authorize a later setup debit.
    service.message(auth, workspace_id, run["id"], "answer", "Engineering", question)
    assert service.view(auth, workspace_id)["readiness"]["setup"]["pending_micro_usd"] == 600_000
    service.message(auth, workspace_id, run["id"], "context", "Keep the explanation brief.")
    assert service.view(auth, workspace_id)["readiness"]["setup"]["charged_micro_usd"] == 600_000
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    assert service.view(auth, workspace_id)["run"]["status"] == "completed"


def test_owner_answer_records_known_setup_charge_before_continuing(build_env, base_env):
    env, ctx, auth, _, workspace_id, _, _ = setup(build_env, base_env)
    model = ScriptedModel([{"schema_version": 1, "control": {"next": "wait_owner", "question": "Which audience?",
                                                            "options": ["Engineering", "General"]}}])
    model.estimate = Estimate(100, 100, 0)
    ctx.agent_runtime.model = model
    service = WorkspaceExecution(ctx)
    run = service.start(auth, workspace_id, "launch")
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    question = service.view(auth, workspace_id)["run"]["question"]["id"]
    record_setup(env, auth, workspace_id)
    assert service.message(auth, workspace_id, run["id"], "answer", "Engineering", question)["status"] == "queued"
    assert service.view(auth, workspace_id)["readiness"]["setup"]["charged_micro_usd"] == 600_000


def test_legacy_new_run_still_waits_for_busy_setup(build_env, base_env):
    env, ctx, auth, instance, workspace_id, model, _ = setup(build_env, base_env)
    record_setup(env, auth, workspace_id, state="held")
    with env.db.reader() as conn:
        session = conn.execute("SELECT session_id FROM agent_workspace WHERE id=?", (workspace_id,)).fetchone()[0]
    with pytest.raises(AiclError) as caught:
        RuntimeChatService(ctx).start(auth, session, instance.id, "legacy-new", [])
    assert caught.value.extra["reason"] == "setup_in_progress"
    assert WorkspaceExecution(ctx).view(auth, workspace_id)["history"] == [] and model.calls == []

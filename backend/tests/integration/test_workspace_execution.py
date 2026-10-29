"""The workspace admits manual and scheduled work through one durable runtime."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest

from aicl.agent_runtime.adapters import ScriptedModel, ScriptedTool, ToolRegistry
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.agent_runtime.worker import LocalRuntimeWorker
from aicl.agent_workspace.execution import WorkspaceExecution, next_due
from aicl.agent_workspace.service import WorkspaceService
from aicl.control.budget import Estimate
from aicl.control.errors import AiclError
from aicl.db import from_iso, to_iso
from aicl.creation.operations import SqliteInstanceOperations
from test_runtime_chat import setup as chat_setup, spend_fixture_credit


def complete(_context):
    return {"schema_version": 1,
            "output": {"artifacts": [{"local_ref": "explanation", "content": "A queue preserves order."}]},
            "control": {"next": "complete", "artifact_refs": ["explanation"], "criterion_assessments": [
                {"requirement_id": "explanation", "status": "met", "explanation": "Explains ordering"}]}}


def setup(build_env, base_env, *, funded=True):
    env, ctx, _, _, _, auth, inst, session, _ = chat_setup(build_env, base_env, funded=funded)
    model = ScriptedModel([complete, complete, complete])
    model.estimate = Estimate(100, 100, 0)
    tool = ScriptedTool("fixture.read", {"page": "Public evidence"})
    tool.capability = "network.fetch"
    tool.descriptor = {"name": "fixture.read", "description": "Read an approved public page"}
    ctx.agent_runtime = AgentRuntime(env.db, env.clock, model, ToolRegistry([tool]))
    identity = str(uuid.uuid4())
    draft = {"name": "Queue report", "goal": "Explain the supplied design", "inputs": "One queue preserves order.",
             "deliverables": [{"key": "explanation", "name": "Explanation", "description": "Explain the design",
                               "criteria": ["Explain ordering"]}], "tools": ["fixture.read"],
             "network_domains": ["example.org"], "web_access": None, "public_research": {"purpose": "", "queries": [], "source_urls": []}, "limits": {"inference_daily_micro_usd": 1_000_000,
             "inference_monthly_micro_usd": 10_000_000, "compute_daily_micro_usd": 1_000_000,
             "compute_monthly_micro_usd": 10_000_000}, "cadence": "daily", "timezone": "America/New_York",
             "time_of_day": "09:00"}
    with env.db.transaction() as conn:
        conn.execute("UPDATE capability_grant SET enabled=1 WHERE instance_id=? AND capability='network.fetch'", (inst.id,))
        conn.execute("UPDATE agent_instance SET network_domains='[\"example.org\"]' WHERE id=?", (inst.id,))
        version = conn.execute("SELECT version FROM agent_instance WHERE id=?", (inst.id,)).fetchone()[0]
        workflow_version = conn.execute("SELECT version FROM mock_workflow_config WHERE instance_id=?", (inst.id,)).fetchone()[0]
        conn.execute("INSERT INTO agent_workspace "
                     "(id,tenant_id,owner_id,session_id,instance_id,version,draft_json,published_json,"
                     "source_instance_version,source_workflow_version,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?,?,?,?)",
                     (identity, auth.tenant_id, auth.owner_id, session, inst.id, json.dumps(draft), json.dumps(draft),
                      version, workflow_version, to_iso(env.clock.now()), to_iso(env.clock.now())))
    return env, ctx, auth, inst, identity, model, draft


def test_manual_scheduled_definition_and_restarted_worker_are_identical(build_env, base_env):
    env, ctx, auth, inst, identity, model, draft = setup(build_env, base_env)
    service = WorkspaceExecution(ctx)
    with env.db.transaction() as conn:
        before = conn.total_changes
        state = service.view(auth, identity)
        assert state["readiness"]["ready"]
        assert conn.total_changes == before and model.calls == []
    first = service.start(auth, identity, "first")
    assert service.start(auth, identity, "first")["id"] == first["id"]
    with pytest.raises(AiclError, match="conflict"):
        service.start(auth, identity, "second")
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    assert service.view(auth, identity)["run"]["status"] == "completed"
    with env.db.reader() as conn:
        version = conn.execute("SELECT version FROM agent_workspace WHERE id=?", (identity,)).fetchone()[0]
    schedule = service.schedule(auth, identity, True, version)
    env.clock.set(from_iso(schedule["next_due"]))
    restarted = AgentRuntime(env.db, env.clock, model, ctx.agent_runtime.tools)
    assert LocalRuntimeWorker(restarted).tick() == 1
    assert LocalRuntimeWorker(restarted).tick() == 0
    state = service.view(auth, identity)
    assert len(state["history"]) == 2 and state["run"]["status"] == "completed"
    assert model.calls[0]["definition"] == model.calls[1]["definition"]
    assert model.calls[0]["definition"]["allowed_tools"] == ["fixture.read"]
    assert "One queue preserves order." in model.calls[1]["definition"]["objective"]
    assert from_iso(state["schedule"]["next_due"]) > env.clock.now()
    assert service.start(auth, identity, "another-manual")["id"] != first["id"]


def test_unfunded_start_and_due_remain_recoverable_without_dispatch(build_env, base_env):
    env, ctx, auth, inst, identity, model, _ = setup(build_env, base_env, funded=False)
    service = WorkspaceExecution(ctx)
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_instance SET lifecycle='draft' WHERE id=?", (inst.id,))
    assert service.view(auth, identity)["readiness"]["required_micro_usd"] == 400
    with pytest.raises(AiclError) as caught:
        service.start(auth, identity, "unfunded")
    assert caught.value.extra["reason"] == "credit_insufficient"
    with env.db.reader() as conn:
        assert conn.execute("SELECT lifecycle FROM agent_instance WHERE id=?", (inst.id,)).fetchone()[0] == "draft"
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0
    commerce = ctx.agent_runtime.accounting.commerce
    order = commerce.create_topup(auth, inst.id, 500, "fund-workspace")
    commerce.select_payment_buyer(auth, order["id"], "demo-buyer")
    commerce.checkout(auth, order["id"], "complete")
    schedule = service.schedule(auth, identity, True, 1)
    due = schedule["next_due"]
    spend_fixture_credit(env, inst.id, 5_000_000)
    env.clock.set(from_iso(due))
    worker = LocalRuntimeWorker(ctx.agent_runtime)
    assert worker.tick() == worker.tick() == 0 and model.calls == []
    state = service.view(auth, identity)
    assert state["schedule"]["next_due"] == due
    assert "credit" in state["schedule"]["last_outcome"].lower()
    assert state["history"] == []
    order = commerce.create_topup(auth, inst.id, 500, "fund-recovery")
    commerce.select_payment_buyer(auth, order["id"], "demo-buyer")
    commerce.checkout(auth, order["id"], "complete")
    assert worker.tick() == 1 and worker.tick() == 0
    assert len(service.view(auth, identity)["history"]) == 1


def test_missing_inference_grant_still_blocks_work_until_settings_are_reapplied(build_env, base_env):
    env, ctx, auth, inst, identity, model, _ = setup(build_env, base_env)
    core, execution = WorkspaceService(ctx), WorkspaceExecution(ctx)
    state = core.view(auth, identity)
    # Fault injection: intrinsic inference still needs its canonical AICL grant.
    with env.db.transaction() as conn:
        conn.execute("UPDATE capability_grant SET enabled=0 WHERE instance_id=? AND capability='inference'", (inst.id,))
    readiness = execution.view(auth, identity)["readiness"]
    assert not readiness["ready"]
    assert {"reason": "capability_disabled", "message":
            "Agent processing is unavailable. Reapply this agent’s settings before continuing."} in readiness["blockers"]
    for operation in (lambda: execution.start(auth, identity, "disabled-start"),
                      lambda: execution.schedule(auth, identity, True, state["version"])):
        with pytest.raises(AiclError) as caught:
            operation()
        assert caught.value.extra["reason"] == "capability_disabled"
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM agent_runtime_hold").fetchone()[0] == 0
    assert model.calls == []

    assert not execution.view(auth, identity)["readiness"]["ready"]
    state = core.apply(auth, identity, state["version"])
    assert execution.view(auth, identity)["can_start"]
    assert execution.start(auth, identity, "enabled-start")["status"] == "queued"


def test_current_inference_grant_is_checked_for_resume_and_queued_dispatch(build_env, base_env):
    env, ctx, auth, inst, identity, model, _ = setup(build_env, base_env)
    core, execution = WorkspaceService(ctx), WorkspaceExecution(ctx)
    run = execution.start(auth, identity, "existing-run")
    execution.control(auth, identity, run["id"], "pause")
    state = core.view(auth, identity)
    # Simulate loss of the required AICL grant after the run was queued.
    with env.db.transaction() as conn:
        conn.execute("UPDATE capability_grant SET enabled=0 WHERE instance_id=? AND capability='inference'", (inst.id,))
    assert not execution.view(auth, identity)["run"]["can_resume"]
    with pytest.raises(AiclError) as caught:
        execution.control(auth, identity, run["id"], "resume")
    assert caught.value.extra["reason"] == "capability_disabled"

    # Even a stale queue item that reaches the worker rechecks current control.
    ctx.agent_runtime.resume(auth, run["id"])
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    assert execution.view(auth, identity)["run"]["status"] == "blocked"
    assert model.calls == []
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_runtime_hold").fetchone()[0] == 0


@pytest.mark.parametrize("inference_enabled", [True, False])
def test_readiness_normalizes_legacy_permission_after_reverted_edit(build_env, base_env, inference_enabled):
    env, ctx, auth, inst, identity, model, draft = setup(build_env, base_env)
    legacy = {**draft, "inference_enabled": inference_enabled}
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_workspace SET draft_json=?,published_json=? WHERE id=?",
                     (json.dumps(legacy), json.dumps(legacy), identity))
    core = WorkspaceService(ctx)
    state = core.view(auth, identity)
    state = core.update_draft(auth, identity, state["version"], {"name": "Temporary name"})
    state = core.update_draft(auth, identity, state["version"], {"name": legacy["name"]})
    assert not state["dirty"]
    assert "inference_enabled" not in state["draft"]
    core.apply(auth, identity, state["version"])
    with env.db.reader() as conn:
        row = conn.execute("SELECT draft_json,published_json FROM agent_workspace WHERE id=?", (identity,)).fetchone()
        assert "inference_enabled" not in json.loads(row["draft_json"])
        assert "inference_enabled" in json.loads(row["published_json"])
    readiness = WorkspaceExecution(ctx).view(auth, identity)["readiness"]
    assert not any(item["reason"] == "unapplied_changes" for item in readiness["blockers"])
    assert readiness["ready"]
    assert model.calls == []


def test_dirty_scope_and_paused_runs_cannot_be_bypassed_by_scheduling(build_env, base_env):
    env, ctx, auth, inst, identity, model, draft = setup(build_env, base_env)
    service = WorkspaceExecution(ctx)
    foreign = replace(auth, owner_id=str(uuid.uuid4()))
    for operation in (lambda: service.view(foreign, identity), lambda: service.start(foreign, identity, "foreign"),
                      lambda: service.schedule(foreign, identity, True, 1)):
        with pytest.raises(AiclError, match="not_found"):
            operation()
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_workspace SET draft_json=? WHERE id=?", (json.dumps({**draft, "goal": "Changed"}), identity))
    with pytest.raises(AiclError) as caught:
        service.start(auth, identity, "dirty")
    assert caught.value.extra["reason"] == "unapplied_changes"
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_workspace SET draft_json=published_json WHERE id=?", (identity,))
    schedule = service.schedule(auth, identity, True, 1)
    run = service.start(auth, identity, "manual")
    service.control(auth, identity, run["id"], "pause")
    env.clock.set(from_iso(schedule["next_due"]) + timedelta(days=4))
    worker = LocalRuntimeWorker(ctx.agent_runtime)
    assert worker.tick() == 0 and model.calls == []
    state = service.view(auth, identity)
    assert state["run"]["status"] == "paused" and state["schedule"]["next_due"] == schedule["next_due"]
    service.control(auth, identity, run["id"], "resume")
    assert worker.tick() == 1
    # One overdue occurrence is retained, rather than enqueueing four missed runs.
    assert worker.tick() == 1 and worker.tick() == 0
    assert len(service.view(auth, identity)["history"]) == 2


def test_daily_timezone_and_hourly_dst_boundaries():
    config = {"cadence": "daily", "timezone": "America/New_York", "time_of_day": "09:00"}
    assert next_due(config, datetime(2026, 10, 31, 13, tzinfo=timezone.utc)) == "2026-11-01T14:00:00.000000Z"
    spring = {**config, "time_of_day": "02:30"}
    # Nonexistent local times roll forward by the DST gap; they never run twice.
    assert next_due(spring, datetime(2026, 3, 8, 6, tzinfo=timezone.utc)) == "2026-03-08T07:30:00.000000Z"
    assert next_due({**config, "cadence": "hourly"}, datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)) == "2026-11-01T06:00:00.000000Z"


def test_competing_schedule_ticks_admit_one_run(build_env, base_env):
    env, ctx, auth, _, identity, model, _ = setup(build_env, base_env)
    service = WorkspaceExecution(ctx)
    schedule = service.schedule(auth, identity, True, 1)
    env.clock.set(from_iso(schedule["next_due"]))
    with ThreadPoolExecutor(max_workers=3) as pool:
        admitted = list(pool.map(lambda i: WorkspaceExecution(ctx).admit_due(worker_id=f"worker-{i}"), range(3)))
    assert sum(admitted) == 1
    assert len(service.view(auth, identity)["history"]) == 1 and model.calls == []
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1


def test_imported_blocked_chat_run_recovers_without_applying_new_draft(build_env, base_env):
    env, ctx, _, chat, _, auth, inst, session, model = chat_setup(build_env, base_env)
    model.estimate = Estimate(100, 100, 0)
    run = chat.start(auth, session, inst.id, "legacy", [])
    spend_fixture_credit(env, inst.id, 5_000_000)
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    core = WorkspaceService(ctx)
    imported = core.open(auth, instance_id=inst.id)
    service = WorkspaceExecution(ctx)
    with env.db.transaction() as conn:
        before = conn.total_changes
        state = service.view(auth, imported["id"])
        assert state["run"]["id"] == run["id"] and state["run"]["reason"] == "credit_insufficient"
        assert not state["run"]["can_resume"] and conn.total_changes == before
    assert imported["dirty"] and imported["published"] is None
    commerce = ctx.agent_runtime.accounting.commerce
    order = commerce.create_topup(auth, inst.id, 500, "legacy-recovery")
    commerce.select_payment_buyer(auth, order["id"], "demo-buyer")
    commerce.checkout(auth, order["id"], "complete")
    assert service.control(auth, imported["id"], run["id"], "resume")["status"] == "queued"
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    state = service.view(auth, imported["id"])
    assert state["run"]["status"] == "waiting_owner"
    service.message(auth, imported["id"], run["id"], "answer", "Engineering", state["run"]["question"]["id"])
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    assert service.view(auth, imported["id"])["run"]["status"] == "completed"


def test_paused_instance_import_resumes_explicitly_without_source_conflict(build_env, base_env):
    env, ctx, _, _, _, auth, inst, _, model = chat_setup(build_env, base_env)
    with env.db.reader() as conn:
        version = conn.execute("SELECT version FROM agent_instance WHERE id=?", (inst.id,)).fetchone()[0]
    SqliteInstanceOperations(env.db, env.clock).set_lifecycle(auth, inst.id, version, "pause")
    core = WorkspaceService(ctx)
    imported = core.open(auth, instance_id=inst.id)
    published = core.apply(auth, imported["id"], imported["version"])
    service = WorkspaceExecution(ctx)
    with pytest.raises(AiclError) as caught:
        service.start(auth, imported["id"], "paused")
    assert caught.value.extra["reason"] == "instance_not_active"
    resumed = service.lifecycle(auth, imported["id"], "resume", published["version"])
    state = core.view(auth, imported["id"])
    assert state["lifecycle"] == "active" and not state["external_conflict"]
    assert state["draft"] == state["published"] == published["published"] and model.calls == []
    run = service.start(auth, imported["id"], "started")
    assert service.control(auth, imported["id"], run["id"], "resume")["id"] == run["id"]
    service.lifecycle(auth, imported["id"], "pause", resumed["version"])
    assert service.view(auth, imported["id"])["run"]["status"] == "queued"
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1 and model.calls == []
    assert service.view(auth, imported["id"])["run"]["reason"] == "instance_not_active"

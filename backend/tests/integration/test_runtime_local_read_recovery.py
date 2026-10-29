"""Explicit recovery of a proven local read never replays remote research."""
from dataclasses import replace
from datetime import timedelta
import uuid

import pytest

from aicl.agent_workspace.execution import WorkspaceExecution
from aicl.agent_workspace.service import WorkspaceService
from aicl.control.budget import Estimate
from aicl.control.errors import AiclError
from aicl.db import to_iso
from test_agent_runtime_session import envelope
from test_runtime_research_prelude import setup


def interrupted_local_read(build_env):
    def request_read(context):
        return envelope(actions=[{"name": "artifact.read", "arguments": {
            "ref": context["observations"][0]["ref"], "source_index": 0,
            "public_preview": True, "field": "text"}}])

    env, auth, instance, runtime, model, _, original, outbound, _, ctx = setup(
        build_env, sources=(), responses=[request_read, envelope(
            control={"next": "wait_owner", "question": "Use the saved search results?", "options": []})])
    workspace = WorkspaceService(ctx).open(auth, instance_id=instance.id)
    with env.db.transaction() as conn:
        conn.execute("INSERT INTO agent_workspace_run(workspace_id,run_id,created_at) VALUES (?,?,?)",
                     (workspace["id"], original["id"], to_iso(env.clock.now())))
    runtime.advance_slice(auth, original["id"], max_operations=2)

    def crash(stage, dispatch):
        if stage == "after_dispatch_intent":
            assert dispatch["tool_name"] == "artifact.read"
            raise RuntimeError("lost local read receipt")

    with pytest.raises(RuntimeError):
        runtime.advance_slice(auth, original["id"], fault=crash)
    env.clock.advance(timedelta(seconds=31))
    blocked = runtime.advance_slice(auth, original["id"])
    assert blocked["reason"] == "unknown_outcome"
    with env.db.reader() as conn:
        step = dict(conn.execute("SELECT * FROM agent_step WHERE run_id=? AND state='unknown'", (original["id"],)).fetchone())
    return env, auth, instance, runtime, model, outbound, workspace, WorkspaceExecution(ctx), blocked, step


def snapshot(env, runtime, auth, run_id):
    with env.db.reader() as conn:
        return {"run": runtime.read(auth, run_id),
                "steps": [dict(row) for row in conn.execute("SELECT * FROM agent_step WHERE run_id=?", (run_id,))],
                "holds": [dict(row) for row in conn.execute("SELECT * FROM budget_hold")],
                "usage": [dict(row) for row in conn.execute("SELECT * FROM budget_usage")]}


@pytest.mark.parametrize("funding_blocked", [False, True])
def test_continue_reconciles_original_local_read_once_without_repeating_research(build_env, funding_blocked):
    env, auth, _, runtime, model, outbound, workspace, execution, blocked, step = interrupted_local_read(build_env)
    if funding_blocked:
        runtime.model.estimate = Estimate(100, 100, 0)
        runtime.accounting.platform_limit_micro_usd = 5_001  # Research already spent 5,000; the next model maximum is 400.
    before = snapshot(env, runtime, auth, blocked["id"])
    with env.db.reader() as conn:
        writes = conn.total_changes
        projection = execution.view(auth, workspace["id"])["run"]
        assert projection["local_read_recovery_available"] and projection["can_resume"]
        assert conn.total_changes == writes
    assert len(model.calls) == len(outbound) == 1
    result = execution.control(auth, workspace["id"], blocked["id"], "resume", expected_run_version=blocked["version"])
    assert result["status"] == ("blocked" if funding_blocked else "queued")
    assert result["action_count"] == blocked["action_count"]
    assert result["decision_count"] == blocked["decision_count"]
    with env.db.reader() as conn:
        restored = dict(conn.execute("SELECT * FROM agent_step WHERE id=?", (step["id"],)).fetchone())
        assert restored["state"] == "applied" and restored["hold_id"] == step["hold_id"]
        assert restored["input_ref"] == step["input_ref"]
        receipt = runtime.repo.get_content(conn, auth, blocked["id"], restored["output_ref"])
        assert receipt["error"] == "public_page_text_required" and receipt["text"] == ""
        assert conn.execute("SELECT state FROM budget_hold WHERE id=?", (step["hold_id"],)).fetchone()[0] == "settled"
        usage = conn.execute("SELECT * FROM budget_usage WHERE hold_id=?", (step["hold_id"],)).fetchone()
        assert usage["inference_micro_usd"] == usage["compute_micro_usd"] == usage["web_search_calls"] == 0
        assert conn.execute("SELECT COUNT(*) FROM budget_hold").fetchone()[0] == len(before["holds"])
        for prior in before["steps"]:
            if prior["id"] != step["id"]:
                assert dict(conn.execute("SELECT * FROM agent_step WHERE id=?", (prior["id"],)).fetchone()) == prior
        events = runtime.repo.events(conn, auth, blocked["id"])
        assert len([event for event in events if event["kind"] == "local_read_reconciled"]) == 1
    assert len(model.calls) == len(outbound) == 1
    if funding_blocked:
        assert result["reason"] == "platform_spend_ceiling"
        assert runtime.advance_slice(auth, blocked["id"])["status"] == "blocked"
        with env.db.reader() as conn:
            assert conn.execute("SELECT 1 FROM agent_wakeup WHERE run_id=?", (blocked["id"],)).fetchone() is None
    else:
        # A repeated owner command cannot repeat the saved read or its charge.
        execution.control(auth, workspace["id"], blocked["id"], "resume", expected_run_version=blocked["version"])
        assert runtime.advance_slice(auth, blocked["id"])["status"] == "waiting_owner"
        assert len(model.calls) == 2 and len(outbound) == 1
        observed = [item["result"] for item in model.calls[-1]["observations"] if item["tool"] == "artifact.read"]
        assert observed[0]["error"] == "public_page_text_required"


@pytest.mark.parametrize("denial", ["stale", "foreign", "grant", "release", "version", "nonzero", "remote", "lease"])
def test_recovery_denials_preserve_unknown_hold_and_do_not_read_or_dispatch(build_env, denial):
    env, auth, instance, runtime, model, outbound, workspace, execution, blocked, step = interrupted_local_read(build_env)
    caller, version = auth, blocked["version"]
    with env.db.transaction() as conn:
        if denial == "stale":
            version -= 1
        elif denial == "foreign":
            caller = replace(auth, owner_id=str(uuid.uuid4()))
        elif denial == "grant":
            conn.execute("UPDATE capability_grant SET enabled=0 WHERE instance_id=? AND capability='inference'", (instance.id,))
        elif denial == "release":
            conn.execute("UPDATE workspace_public_research_release SET revoked_at=?", (to_iso(env.clock.now()),))
        elif denial == "version":
            conn.execute("UPDATE agent_step SET tool_version='artifact-unknown' WHERE id=?", (step["id"],))
        elif denial == "nonzero":
            conn.execute("UPDATE budget_hold SET est_web_search_calls=1 WHERE id=?", (step["hold_id"],))
        elif denial == "remote":
            conn.execute("UPDATE agent_step SET tool_name='model',kind='decision' WHERE id=?", (step["id"],))
        elif denial == "lease":
            conn.execute("UPDATE agent_run SET lease_owner='other-worker',lease_until=? WHERE id=?",
                         (to_iso(env.clock.now() + timedelta(seconds=30)), blocked["id"]))
    before = snapshot(env, runtime, auth, blocked["id"])
    with pytest.raises(AiclError):
        execution.control(caller, workspace["id"], blocked["id"], "resume", expected_run_version=version)
    assert snapshot(env, runtime, auth, blocked["id"]) == before
    assert len(model.calls) == len(outbound) == 1


def test_reconciliation_api_preserves_blocked_state_until_explicit_resume(build_env):
    env, auth, _, runtime, model, outbound, _, _, blocked, _ = interrupted_local_read(build_env)
    restored = runtime.reconcile_local_artifact_read(auth, blocked["id"], blocked["version"])
    assert restored["status"] == "blocked" and restored["reason"] is None
    with env.db.reader() as conn:
        assert conn.execute("SELECT 1 FROM agent_wakeup WHERE run_id=?", (blocked["id"],)).fetchone() is None
    assert len(model.calls) == len(outbound) == 1

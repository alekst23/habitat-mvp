"""A work log is an owner-scoped projection of recorded actions and charges."""
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from aicl.agent_workspace.execution import WorkspaceExecution
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.workflow.runtime_projection import RuntimeAuditProjection
from test_agent_runtime_session import envelope
from test_workspace_execution import complete, setup
from test_workspace_setup_accounting import attempt


def test_work_log_is_run_scoped_exact_read_only_and_available_without_runtime(build_env, base_env):
    env, ctx, auth, inst, workspace_id, model, _ = setup(build_env, base_env)
    execution = WorkspaceExecution(ctx)
    first = envelope(actions=[{"name": "fixture.read", "arguments": {"key": "page"}},
                              {"name": "fixture.read", "arguments": {"key": "missing"}}])
    model.responses = [first, complete, complete]
    decide = model.decide
    model.decide = lambda *args: replace(decide(*args), usage=MeasuredUsage(20, 10, 0),
                                       model="test-model", response_id="private-provider-response-id")
    tool = ctx.agent_runtime.tools.get("fixture.read")
    execute = tool.execute

    def error_receipt(arguments, invocation_id):
        receipt = execute(arguments, invocation_id)
        return replace(receipt, payload={"error": "Untrusted error with private-diagnostic-token"}) if arguments["key"] == "missing" else receipt

    tool.execute = error_receipt
    run = execution.start(auth, workspace_id, "logged-run")
    ctx.agent_runtime.advance_slice(auth, run["id"], max_operations=10)
    first_log = execution.view(auth, workspace_id)["run"]["activity_log"]
    assert first_log["schema_version"] == 1 and first_log["run_id"] == run["id"]
    assert first_log["status"] == "completed" and first_log["summary"]["settled_micro_usd"] == 100
    assert first_log["totals"] == {"model_decisions": 2, "tool_calls": 2, "input_tokens": 40,
                                   "output_tokens": 20, "web_search_calls": 0}
    assert [step["sequence"] for step in first_log["steps"]] == [1, 2, 3, 4]
    assert [step["label"] for step in first_log["steps"] if step["kind"] == "decision"] == ["Model decision"] * 2
    tools = [step for step in first_log["steps"] if step["kind"] == "tool"]
    assert len(tools) == 2 and all(step["cost_summary"]["total_micro_usd"] == 0 for step in tools)
    assert all(step["usage"]["input_tokens"] == step["usage"]["output_tokens"] == 0 for step in tools)
    assert all(step["usage"]["cost_micro_usd"] == 0 for step in tools)
    assert tools[0]["error"] is None and tools[1]["error"]
    assert all(step["evidence_url"].startswith(first_log["audit_url"] + "#step-") for step in first_log["steps"])
    assert "private-provider-response-id" not in json.dumps(first_log)
    assert "private-diagnostic-token" not in json.dumps(first_log)
    assert "Public evidence" not in json.dumps(first_log)
    assert all(not {"input_ref", "output_ref", "receipt_metadata", "arguments", "request"} & set(step)
               for step in first_log["steps"])

    # Setup costs and another run on the very same instance must not enter this log.
    attempt(ctx, auth, workspace_id)
    other = execution.start(auth, workspace_id, "other-run")
    ctx.agent_runtime.advance_slice(auth, other["id"], max_operations=10)
    projection = RuntimeAuditProjection(env.db, env.clock)
    with env.db.transaction() as conn:
        before = conn.total_changes
        assert projection.activity_log(conn, auth, run["id"]) == first_log
        assert projection.job(conn, auth, run["id"])["cost_summary"] == first_log["summary"]
        ledger = conn.execute("SELECT SUM(u.inference_micro_usd+u.compute_micro_usd) FROM agent_step s "
                              "JOIN budget_usage u ON u.hold_id=s.hold_id WHERE s.run_id=?", (run["id"],)).fetchone()[0]
        assert ledger == sum(step["cost_summary"]["total_micro_usd"] for step in first_log["steps"])
        assert conn.total_changes == before

    ctx.agent_runtime = None
    latest = WorkspaceExecution(ctx).view(auth, workspace_id)["run"]["activity_log"]
    assert latest["run_id"] == other["id"] and latest["summary"]["settled_micro_usd"] == 50
    with env.db.reader() as conn:
        for foreign in (replace(auth, tenant_id="other-tenant"), replace(auth, owner_id="other-owner")):
            with pytest.raises(AiclError, match="not_found"):
                projection.activity_log(conn, foreign, run["id"])
        with pytest.raises(AiclError, match="unauthenticated"):
            projection.activity_log(conn, replace(auth, expires_at=env.clock.now() - timedelta(seconds=1)), run["id"])


@pytest.mark.parametrize("unknown", [False, True])
def test_work_log_keeps_unresolved_reservations_separate_from_unrecorded_usage(build_env, base_env, unknown):
    env, ctx, auth, _, workspace_id, model, _ = setup(build_env, base_env)
    execution = WorkspaceExecution(ctx)
    run = execution.start(auth, workspace_id, "held-run")

    def interrupt(stage, _step):
        if stage == "after_dispatch_intent":
            raise RuntimeError("worker interrupted")

    with pytest.raises(RuntimeError, match="worker interrupted"):
        ctx.agent_runtime.advance_slice(auth, run["id"], fault=interrupt)
    if unknown:
        with env.db.transaction() as conn:
            step = conn.execute("SELECT id,hold_id FROM agent_step WHERE run_id=?", (run["id"],)).fetchone()
            ctx.agent_runtime.accounting.mark_unknown(conn, step["hold_id"])
            conn.execute("UPDATE agent_step SET state='unknown' WHERE id=?", (step["id"],))
    with env.db.transaction() as conn:
        before = conn.total_changes
        log = execution.view(auth, workspace_id)["run"]["activity_log"]
        assert conn.total_changes == before
    step, = log["steps"]
    assert step["state"] == ("unknown" if unknown else "dispatching")
    assert step["usage"] is None and step["cost_summary"]["held_micro_usd"] == 400
    assert log["summary"]["settled_micro_usd"] == log["summary"]["total_micro_usd"] == 0
    assert log["summary"]["held_micro_usd"] == 400
    assert log["totals"] == {"model_decisions": 1, "tool_calls": 0, "input_tokens": 0,
                             "output_tokens": 0, "web_search_calls": 0}
    assert model.calls == []


def test_work_log_counts_bundled_search_usage_once_and_keeps_compute_estimates_distinct(build_env):
    from test_runtime_agent_research import agent_setup

    env, auth, _, runtime, model, _, run, _, _, _ = agent_setup(build_env)
    model.estimate = Estimate(100, 100, 1)
    decide = model.decide
    model.decide = lambda *args: replace(decide(*args), usage=MeasuredUsage(20, 10, 1))
    runtime.advance_slice(auth, run["id"])
    with env.db.reader() as conn:
        log = RuntimeAuditProjection(env.db, env.clock).activity_log(conn, auth, run["id"])
        ledger = conn.execute("SELECT SUM(u.inference_micro_usd),SUM(u.compute_micro_usd) FROM agent_step s "
                              "JOIN budget_usage u ON u.hold_id=s.hold_id WHERE s.run_id=?", (run["id"],)).fetchone()
    assert log["status"] == "waiting_owner"
    assert log["steps"][0]["label"] == "Public web research"
    assert log["totals"] == {"model_decisions": 1, "tool_calls": 1, "input_tokens": 320,
                             "output_tokens": 70, "web_search_calls": 1}
    assert log["summary"]["settled_micro_usd"] == ledger[0] > 0
    assert log["summary"]["estimated_micro_usd"] == ledger[1] > 0
    assert log["summary"]["total_micro_usd"] == sum(ledger)
    combined, = [c for c in log["summary"]["components"] if c["component"] == "model_and_tools"]
    assert combined["settled_micro_usd"] == 6200
    assert all(c["coverage"] == "bundled" for c in log["summary"]["components"] if c["component"] in {"model", "tools"})
    assert sum(step["cost_summary"]["total_micro_usd"] for step in log["steps"]) == sum(ledger)

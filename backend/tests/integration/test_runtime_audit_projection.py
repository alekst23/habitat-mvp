"""Durable runtime evidence remains visible through the owner audit boundary."""
from dataclasses import replace

import pytest

from aicl.agent_runtime.storage import Repository
from aicl.control.budget import Estimate, MeasuredUsage
from aicl.control.errors import AiclError
from aicl.workflow.service import MockWorkflowService
from test_agent_runtime_session import batch, definition, envelope, finish, setup_runtime
from test_mock_commerce import ready


def test_runtime_audit_recovers_saved_versions_actions_and_exact_costs_without_writes(build_env):
    env, commerce, auth, inst, _ = ready(build_env)

    def draft(context):
        return envelope(artifacts=[{"local_ref": "comparison", "content": "First draft",
                                    "evidence_refs": [item["ref"] for item in context["observations"]]}],
                        control={"next": "continue_draft", "requirement_ids": ["r1"], "reason": "Finish both views"})

    runtime, model, tool = setup_runtime(env, [batch(), draft, finish])
    model.estimate = Estimate(100, 100, 0)
    decide = model.decide
    model.decide = lambda *args: replace(decide(*args), usage=MeasuredUsage(20, 10, 0), model="test-model")
    run = runtime.create_run(auth, inst.id, "audit-run", definition())
    runtime.advance_slice(auth, run["id"], max_operations=4)
    workflow = MockWorkflowService(env.db, env.clock, commerce)
    saved_draft, = workflow.overview(auth, inst.id)["deliverables"]
    assert saved_draft["content"] == "First draft" and saved_draft["state"] == "draft"
    completed = runtime.advance_slice(auth, run["id"], max_operations=10)
    assert completed["status"] == "completed"
    with env.db.reader() as conn:
        before = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("agent_content", "agent_step", "agent_event", "budget_usage", "audit_event")}

    overview = workflow.overview(auth, inst.id)
    assert overview["totals"]["run_count"] == 1
    job_id = "runtime:" + run["id"]
    assert overview["runs"][0]["id"] == job_id
    assert overview["totals"]["accepted_count"] == 0
    assert overview["totals"]["inference_cost_micro_usd"] == 150
    assert sum(row["amount_usd"] for row in overview["cost_rows"] if row["category"] == "Inference usage") == pytest.approx(.00015)
    assert sum(row["event_type"] == "runtime.tool" for row in overview["events"]) == 2
    assert sum(row["event_type"] == "runtime.decision" for row in overview["events"]) == 3
    assert all(row["evidence_url"] for row in overview["events"] if row.get("runtime"))
    job = workflow.job(auth, job_id)
    assert len(job["steps"]) == 5 and job["inference_cost_micro_usd"] == 150
    assert job["steps"][0]["usage"]["cost_micro_usd"] == 50
    comparison = next(item for item in overview["deliverables"] if item["name"] == "comparison" and item["latest"])
    assert comparison["content"] == "Compared both sources" and comparison["state"] == "completed"
    item = workflow.deliverable(auth, comparison["id"])
    assert [(v["version"], v["state"], v["content"]) for v in item["versions"]] == [
        (2, "completed", "Compared both sources"), (1, "draft", "First draft")]
    assert len(item["evidence"]) == 2 and all(row["tool_name"] == "fixture.read" for row in item["evidence"])
    assert item["criteria"] == [] and len(item["criterion_assessments"]) == 2
    with pytest.raises(AiclError) as rejected:
        workflow.review(auth, item["id"], "accept", "", item["version"])
    assert rejected.value.error == "invalid_transition"
    foreign, _ = env.new_instance()
    assert workflow.overview(foreign)["deliverables"] == []
    for read in (lambda: workflow.job(foreign, job_id), lambda: workflow.deliverable(foreign, item["id"]),
                 lambda: workflow.job(replace(auth, owner_id=foreign.owner_id), job_id)):
        with pytest.raises(AiclError) as denied:
            read()
        assert denied.value.error == "not_found"
    with env.db.reader() as conn:
        assert before == {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}


def test_runtime_unknown_dispatch_is_visible_without_inventing_settled_usage(build_env):
    env, commerce, auth, inst, _ = ready(build_env)
    runtime, model, _ = setup_runtime(env, [batch()])
    model.estimate = Estimate(100, 100, 0)
    run = runtime.create_run(auth, inst.id, "uncertain-audit", definition())

    def interrupted(stage, _step):
        if stage == "after_dispatch_intent":
            raise RuntimeError("lost worker before receipt")

    with pytest.raises(RuntimeError):
        runtime.advance_slice(auth, run["id"], fault=interrupted)
    workflow = MockWorkflowService(env.db, env.clock, commerce)
    overview = workflow.overview(auth, inst.id)
    assert overview["totals"]["run_count"] == 1
    job = workflow.job(auth, "runtime:" + run["id"])
    assert job["held_micro_usd"] == 400 and job["inference_cost_micro_usd"] == 0
    assert job["steps"][0]["state"] == "dispatching" and job["steps"][0]["usage"] is None
    assert not overview["deliverables"]
    assert not [row for row in overview["cost_rows"] if row["category"] == "Inference usage"]
    reservation, = [row for row in overview["cost_rows"] if row["category"] == "Inference reservation"]
    assert reservation["amount_micro_usd"] == 400 and reservation["status"] == "held"
    assert overview["cost_summary"]["total_micro_usd"] == 0
    assert overview["cost_summary"]["held_micro_usd"] == job["cost_summary"]["held_micro_usd"] == 400
    assert reservation["charge_kind"] == "reservation" and reservation["pricing"] == "reserved"
    assert overview["totals"]["inference_cost_micro_usd"] == overview["totals"]["compute_estimate_micro_usd"] == 0
    assert any(row["event_type"] == "runtime.decision" and row["outcome"] == "dispatching" for row in overview["events"])


def test_audit_observes_one_snapshot_while_worker_finishes(build_env, monkeypatch):
    env, commerce, auth, inst, _ = ready(build_env)
    runtime, _, _ = setup_runtime(env, [batch(), finish])
    run = runtime.create_run(auth, inst.id, "concurrent-audit", definition())
    original = Repository.get_content
    advanced = False

    def advance_after_definition(self, conn, *args):
        nonlocal advanced
        content = original(self, conn, *args)
        if not advanced and args[-1] == run["definition_ref"]:
            advanced = True
            runtime.advance_slice(auth, run["id"], max_operations=10)
        return content

    monkeypatch.setattr(Repository, "get_content", advance_after_definition)
    workflow = MockWorkflowService(env.db, env.clock, commerce)
    first = workflow.overview(auth, inst.id)
    assert advanced and first["runs"][0]["state"] == "queued"
    assert first["deliverables"] == [] and first["runs"][0]["steps"] == []
    second = workflow.overview(auth, inst.id)
    assert second["runs"][0]["state"] == "completed" and len(second["deliverables"]) == 2


def test_setup_usage_matches_operations_without_counting_waivers_or_holds_as_spend(build_env, base_env):
    from aicl.agent_workspace.setup_accounting import WorkspaceSetupAccounting
    from aicl.studio.data import StudioData
    from test_workspace_execution import setup
    from test_workspace_setup_accounting import attempt

    env, ctx, auth, inst, identity, _, _ = setup(build_env, base_env)
    workflow = MockWorkflowService(env.db, env.clock)
    accounting = WorkspaceSetupAccounting(ctx)
    attempt(ctx, auth, identity)
    assert workflow.overview(auth, inst.id)["totals"]["inference_cost_micro_usd"] == 600
    accounting.waive(auth, identity, "audit-waiver", "owner_requested_reset")
    attempt(ctx, auth, identity, input_tokens=200, output_tokens=60)
    accounting.charge(auth, identity)
    attempt(ctx, auth, identity)
    attempt(ctx, auth, identity, outcome="unknown")

    audit = workflow.overview(auth, inst.id)
    operations = StudioData(ctx).snapshot(auth, instance_id=inst.id)
    setup_rows = [row for row in audit["cost_rows"] if row["category"].startswith("Setup")]
    assert {row["status"] for row in setup_rows} == {"waived", "charged", "pending_attribution", "unknown"}
    assert all(row["evidence_url"] == "/agent-workspaces/" + identity for row in setup_rows)
    assert audit["totals"]["inference_cost_micro_usd"] == 1600
    assert operations["totals"]["inference_usd"] == .0016
    assert audit["totals"]["service_balance_micro_usd"] / 1_000_000 == operations["current"]["service_credit_usd"]
    assert sum(row["event_type"] == "assistant.setup_inference" for row in audit["events"]) == 4

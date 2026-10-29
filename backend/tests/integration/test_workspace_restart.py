"""Owner-reviewed replacement runs preserve history and never widen old grants."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import uuid

import pytest
from fastapi.testclient import TestClient

from aicl.agent_runtime.worker import LocalRuntimeWorker
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.agent_runtime.adapters import ScriptedTool, ToolRegistry
from aicl.agent_workspace.execution import WorkspaceExecution
from aicl.agent_workspace.service import WorkspaceService
from aicl.app import FIXTURE_CSRF_TOKEN, create_app
from aicl.control.errors import AiclError
from aicl.control.budget import Estimate
from aicl.db import from_iso
from test_runtime_chat import spend_fixture_credit
from test_workspace_execution import setup


def waiting(build_env, base_env):
    env, ctx, auth, instance, workspace_id, model, _ = setup(build_env, base_env)
    model.responses.insert(0, {"schema_version": 1, "output": {"artifacts": [
        {"local_ref": "draft", "content": "An earlier saved draft."}]},
        "control": {"next": "wait_owner", "question": "Supply sources?", "options": []}})
    execution, core = WorkspaceExecution(ctx), WorkspaceService(ctx)
    run = execution.start(auth, workspace_id, "original")
    execution.message(auth, workspace_id, run["id"], "guidance", "Find public sources and save them for the report.")
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    state = execution.view(auth, workspace_id)
    assert state["run"]["status"] == "waiting_owner"
    edited = core.update_draft(auth, workspace_id, 1, {"tools": []}, actor="owner")
    return env, ctx, auth, instance, workspace_id, model, execution, core, edited


def test_restart_requires_apply_then_preserves_old_results_and_recent_guidance(build_env, base_env):
    env, ctx, auth, instance, workspace_id, model, execution, core, edited = waiting(build_env, base_env)
    before = execution.view(auth, workspace_id)["run"]
    assert before["allowed_tools"] == ["fixture.read"] and not before["settings_changed"]
    assert not before["can_restart"]
    assert "unapplied_changes" in {item["reason"] for item in before["restart_blockers"]}
    applied = core.apply(auth, workspace_id, edited["version"])
    current = execution.view(auth, workspace_id)["run"]
    assert current["settings_changed"] and current["can_restart"]
    original = ctx.agent_runtime.read(auth, current["id"])
    replacement = execution.restart(auth, workspace_id, current["id"], "restart", applied["version"], current["version"])
    assert replacement["id"] != current["id"] and len(model.calls) == 1
    old = ctx.agent_runtime.read(auth, current["id"])
    assert old["status"] == "cancelled" and old["checkpoint"] == original["checkpoint"]
    assert old["definition_ref"] == original["definition_ref"]
    assert execution.view(auth, workspace_id)["run"]["allowed_tools"] == []
    assert len(execution.view(auth, workspace_id)["history"]) == 2
    assert execution.restart(auth, workspace_id, current["id"], "restart", applied["version"], current["version"])["id"] == replacement["id"]
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    assert model.calls[-1]["definition"]["allowed_tools"] == []
    assert any("Find public sources" in item["text"] for item in model.calls[-1]["owner_messages"])


def test_restart_failed_admission_and_stale_versions_leave_old_run_intact(build_env, base_env):
    env, ctx, auth, instance, workspace_id, _, execution, core, edited = waiting(build_env, base_env)
    applied = core.apply(auth, workspace_id, edited["version"])
    run = execution.view(auth, workspace_id)["run"]
    for version, run_version in ((applied["version"] - 1, run["version"]), (applied["version"], run["version"] - 1)):
        with pytest.raises(AiclError, match="conflict"):
            execution.restart(auth, workspace_id, run["id"], str(uuid.uuid4()), version, run_version)
    foreign = replace(auth, owner_id=str(uuid.uuid4()))
    with pytest.raises(AiclError, match="not_found"):
        execution.restart(foreign, workspace_id, run["id"], "foreign", applied["version"], run["version"])
    spend_fixture_credit(env, instance.id, 5_000_000)
    with pytest.raises(AiclError) as caught:
        execution.restart(auth, workspace_id, run["id"], "unfunded", applied["version"], run["version"])
    assert caught.value.extra["reason"] == "credit_insufficient"
    state = execution.view(auth, workspace_id)
    assert state["run"]["id"] == run["id"] and state["run"]["status"] == "waiting_owner"
    assert len(state["history"]) == 1


@pytest.mark.parametrize("step_state", ["prepared", "dispatching", "received", "unknown"])
def test_restart_rejects_unresolved_steps_without_erasing_receipts(build_env, base_env, step_state):
    env, ctx, auth, _, workspace_id, _, execution, core, edited = waiting(build_env, base_env)
    applied = core.apply(auth, workspace_id, edited["version"])
    run = execution.view(auth, workspace_id)["run"]
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_step SET state=? WHERE run_id=?", (step_state, run["id"]))
        original = dict(conn.execute("SELECT * FROM agent_step WHERE run_id=?", (run["id"],)).fetchone())
    assert not execution.view(auth, workspace_id)["run"]["can_restart"]
    with pytest.raises(AiclError) as caught:
        execution.restart(auth, workspace_id, run["id"], "pending", applied["version"], run["version"])
    assert caught.value.extra["reason"] == "restart_pending_work"
    with env.db.reader() as conn:
        assert dict(conn.execute("SELECT * FROM agent_step WHERE run_id=?", (run["id"],)).fetchone()) == original
        assert conn.execute("SELECT status FROM agent_run WHERE id=?", (run["id"],)).fetchone()[0] == "waiting_owner"


def test_restart_can_abandon_never_dispatched_read_after_its_grant_is_removed(build_env, base_env):
    env, ctx, auth, instance, workspace_id, model, _ = setup(build_env, base_env)
    execution, core = WorkspaceExecution(ctx), WorkspaceService(ctx)
    read = ctx.agent_runtime.tools.get("fixture.read")
    model.responses.insert(0, {"schema_version": 1, "actions": [{"name": "fixture.read", "arguments": {"key": "page"}}],
                               "control": {"next": "continue"}})
    original = execution.start(auth, workspace_id, "original")
    ctx.agent_runtime.advance_slice(auth, original["id"], max_operations=1)
    edited = core.update_draft(auth, workspace_id, 1, {"tools": []}, actor="owner")
    applied = core.apply(auth, workspace_id, edited["version"])
    blocked = ctx.agent_runtime.advance_slice(auth, original["id"])
    assert blocked["status"] == "blocked" and blocked["reason"] == "capability_disabled"
    with env.db.reader() as conn:
        planned = dict(conn.execute("SELECT * FROM agent_step WHERE run_id=? AND state='prepared'", (original["id"],)).fetchone())
        assert planned["hold_id"] is None and planned["output_ref"] is None and planned["usage_json"] is None
        holds = [dict(row) for row in conn.execute("SELECT * FROM budget_hold WHERE instance_id=?", (instance.id,))]
    state = execution.view(auth, workspace_id)["run"]
    assert state["can_restart"]
    replacement = execution.restart(auth, workspace_id, original["id"], "remove-read", applied["version"], state["version"])
    assert replacement["id"] != original["id"]
    with env.db.reader() as conn:
        assert dict(conn.execute("SELECT * FROM agent_step WHERE id=?", (planned["id"],)).fetchone()) == planned
        for hold in holds:
            assert dict(conn.execute("SELECT * FROM budget_hold WHERE id=?", (hold["id"],)).fetchone()) == hold
    assert LocalRuntimeWorker(ctx.agent_runtime).tick() == 1
    assert execution.view(auth, workspace_id)["run"]["status"] == "completed"
    assert ctx.agent_runtime.read(auth, original["id"])["status"] == "cancelled" and read.calls == []


def test_competing_restart_replay_creates_one_replacement(build_env, base_env):
    _, _, auth, _, workspace_id, model, execution, core, edited = waiting(build_env, base_env)
    applied = core.apply(auth, workspace_id, edited["version"])
    run = execution.view(auth, workspace_id)["run"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execution.restart(auth, workspace_id, run["id"], "same", applied["version"], run["version"]), range(2)))
    assert results[0]["id"] == results[1]["id"] and len(model.calls) == 1
    assert len(execution.view(auth, workspace_id)["history"]) == 2


@pytest.mark.parametrize("status", ["paused", "blocked"])
def test_restart_accepts_safe_paused_or_blocked_run(build_env, base_env, status):
    env, _, auth, _, workspace_id, _, execution, core, edited = waiting(build_env, base_env)
    applied = core.apply(auth, workspace_id, edited["version"])
    run = execution.view(auth, workspace_id)["run"]
    with env.db.transaction() as conn:
        conn.execute("UPDATE agent_run SET status=?,version=version+1 WHERE id=?", (status, run["id"]))
    current = execution.view(auth, workspace_id)["run"]
    assert current["can_restart"]
    assert execution.restart(auth, workspace_id, current["id"], status, applied["version"], current["version"])["id"] != run["id"]


def test_oversized_owner_guidance_rolls_back_cancellation_and_replacement(build_env, base_env):
    env, ctx, auth, _, workspace_id, _, execution, core, edited = waiting(build_env, base_env)
    applied = core.apply(auth, workspace_id, edited["version"])
    run_id = execution.view(auth, workspace_id)["run"]["id"]
    execution.message(auth, workspace_id, run_id, "large-one", "First guidance " + "x" * 11_900)
    execution.message(auth, workspace_id, run_id, "large-two", "Second guidance " + "y" * 11_900)
    current = execution.view(auth, workspace_id)["run"]
    original = ctx.agent_runtime.read(auth, run_id)
    with pytest.raises(AiclError) as caught:
        execution.restart(auth, workspace_id, run_id, "oversized", applied["version"], current["version"])
    assert caught.value.extra["reason"] == "context_limit"
    assert ctx.agent_runtime.read(auth, run_id) == original
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_run WHERE instance_id=?", (current["instance_id"],)).fetchone()[0] == 1


def test_new_search_grant_is_used_only_by_replacement_and_prices_pending_search(build_env, base_env):
    env, ctx, auth, _, workspace_id, model, execution, core, edited = waiting(build_env, base_env)
    env.clock.set(from_iso("2026-10-27T12:00:00Z"))
    auth = replace(auth, expires_at=env.clock.now() + timedelta(hours=1))
    search = ScriptedTool("fixture.search", {"news": "Public evidence"})
    search.capability = "network.search"
    search.price_version = "gpt-6-sol-web-2026-10-25"
    search.estimate = Estimate(168000, 6000, 0, 1)
    search.descriptor = {"name": "fixture.search", "description": "Find public sources", "parameters": {}}
    ctx.agent_runtime.tools = ToolRegistry([ctx.agent_runtime.tools.get("fixture.read"), search]).with_artifact_reader(ctx.agent_runtime.repo)
    updated = core.update_draft(auth, workspace_id, edited["version"], {"tools": ["fixture.search"], "network_domains": []}, actor="owner")
    applied = core.apply(auth, workspace_id, updated["version"])
    old = execution.view(auth, workspace_id)["run"]
    assert old["allowed_tools"] == ["fixture.read"] and old["can_restart"] and old["settings_changed"]
    replacement = execution.restart(auth, workspace_id, old["id"], "enable-search", applied["version"], old["version"])
    model.responses.insert(0, {"schema_version": 1, "actions": [{"name": "fixture.search", "arguments": {"key": "news"}}],
                               "control": {"next": "continue"}})
    ctx.agent_runtime.advance_slice(auth, replacement["id"], max_operations=1)
    state = execution.view(auth, workspace_id)["run"]
    assert state["allowed_tools"] == ["fixture.search"] and state["readiness"]["required_micro_usd"] == 406_000
    assert search.calls == []
    with env.db.reader() as conn:
        assert ctx.agent_runtime._definition(conn, auth, ctx.agent_runtime.repo.owned_run(conn, auth, old["id"])).allowed_tools == ["fixture.read"]


def test_restart_route_requires_both_versions_and_preserves_replay(build_env, base_env, monkeypatch):
    env, ctx, auth, _, workspace_id, _, execution, core, edited = waiting(build_env, base_env)
    applied = core.apply(auth, workspace_id, edited["version"])
    run = execution.view(auth, workspace_id)["run"]
    from aicl.agent_runtime import factory
    monkeypatch.setattr(factory, "build_runtime", lambda app_ctx: AgentRuntime(
        app_ctx.db, app_ctx.clock, ctx.agent_runtime.model, ctx.agent_runtime.tools))
    app = create_app(ctx.settings.model_copy(update={"environment": "test", "test_mode": True, "database_url": env.db.database_url}))
    app.state.ctx.auth_provider.contexts["workspace-cookie"] = auth
    app.state.ctx.csrf_verifier.fixture_session_ids |= {auth.session_id}
    client = TestClient(app, base_url="http://127.0.0.1:4173")
    client.cookies.set("aicl_session", "workspace-cookie")
    headers = {"Origin": "http://127.0.0.1:4173", "X-CSRF-Token": FIXTURE_CSRF_TOKEN}
    body = {"command": "restart", "request_id": str(uuid.uuid4()), "expected_version": applied["version"],
            "arguments": {"run_id": run["id"], "expected_run_version": run["version"]}}
    endpoint = f"/api/agent-workspaces/{workspace_id}/commands"
    assert client.post(endpoint, json={**body, "arguments": {"run_id": run["id"]}}, headers=headers).status_code == 409
    first = client.post(endpoint, json=body, headers=headers)
    assert first.status_code == 200, first.text
    new_id = first.json()["state"]["execution"]["run"]["id"]
    assert new_id != run["id"]
    assert client.post(endpoint, json=body, headers=headers).json()["state"]["execution"]["run"]["id"] == new_id


def failed_research(build_env, monkeypatch):
    """Use a real failed AICL batch with a settled receipt, all HTTP mocked."""
    from test_runtime_research_prelude import setup as research_setup
    from test_runtime_agent_research import PublicPlanner

    env, auth, instance, runtime, model, research, unused, outbound, _, ctx = research_setup(
        build_env, sources=(), queries=("Legacy news", "Legacy chips"))
    research.planner = PublicPlanner([
        [{"kind": "search", "query": "Public AI news"}],
        [{"kind": "page", "url": "https://news.example/article"}]])
    runtime.cancel(auth, unused["id"])
    # Mock only advisory containment availability; actual I/O remains in the
    # broker's mandatory FixtureResearchWorker + MockTransport offline seam.
    monkeypatch.setattr(research, "_status_observation", {
        "page_available": True, "search_available": True, "reason": None, "search_reason": None})
    core = WorkspaceService(ctx)
    state = core.open(auth, instance_id=instance.id)
    state = core.update_draft(auth, state["id"], state["version"], {
        "name": "Public report", "goal": "Summarize public AI news", "inputs": "Private notes stay here.",
        "deliverables": [{"key": "report", "name": "Report", "description": "Public findings", "criteria": ["Cite sources"]}],
        "tools": ["web.search"], "network_domains": [], "web_access": {"mode": "off", "domains": []},
        "web_search": {"mode": "all", "domains": []},
        "public_research": {"purpose": "Research public AI news", "queries": ["Public AI news"], "source_urls": []},
        "limits": {"inference_daily_micro_usd": 1_000_000, "inference_monthly_micro_usd": 10_000_000,
                   "compute_daily_micro_usd": 1_000_000, "compute_monthly_micro_usd": 10_000_000}})
    state = core.apply(auth, state["id"], state["version"],
                       approved_public_research_digest=state["public_research_release"]["draft_digest"])
    execution = WorkspaceExecution(ctx)
    run = execution.start(auth, state["id"], "failed-original")
    result = runtime.advance_slice(auth, run["id"], max_operations=1)
    assert result["status"] == "blocked" and result["reason"] == "public_research_failed"
    return env, auth, instance, runtime, model, outbound, core, state, execution, result


def test_failed_research_requires_explicit_new_run_with_same_settings_and_preserves_settlement(build_env, monkeypatch):
    env, auth, _, runtime, model, outbound, _, state, execution, failed = failed_research(build_env, monkeypatch)
    workspace_id = state["id"]
    run = execution.view(auth, workspace_id)["run"]
    assert run["research_restart_required"] and run["can_restart"]
    assert not run["settings_changed"] and not run["can_resume"] and not run["can_advance"]
    with env.db.reader() as conn:
        before_steps = [dict(row) for row in conn.execute("SELECT * FROM agent_step WHERE run_id=?", (run["id"],))]
        before_holds = [dict(row) for row in conn.execute("SELECT * FROM budget_hold")]
        before_usage = [dict(row) for row in conn.execute("SELECT * FROM budget_usage")]
        before_content = [dict(row) for row in conn.execute("SELECT * FROM agent_content WHERE run_id=?", (run["id"],))]
    assert before_holds and all(row["state"] == "settled" for row in before_holds)
    for action in ("resume", "advance"):
        with pytest.raises(AiclError) as caught:
            execution.control(auth, workspace_id, run["id"], action)
        assert caught.value.extra["reason"] == "research_restart_required"
        assert runtime.read(auth, run["id"])["version"] == failed["version"]
    assert len(outbound) == 1 and model.calls == []
    replacement = execution.restart(auth, workspace_id, run["id"], "explicit-research-retry", state["version"], run["version"])
    assert replacement["id"] != run["id"] and replacement["status"] == "queued"
    assert runtime.read(auth, run["id"])["status"] == "cancelled"
    assert execution.restart(auth, workspace_id, run["id"], "explicit-research-retry", state["version"], run["version"])["id"] == replacement["id"]
    with env.db.reader() as conn:
        assert [dict(row) for row in conn.execute("SELECT * FROM agent_step WHERE run_id=?", (run["id"],))] == before_steps
        assert [dict(row) for row in conn.execute("SELECT * FROM budget_hold")] == before_holds
        assert [dict(row) for row in conn.execute("SELECT * FROM budget_usage")] == before_usage
        for content in before_content:
            assert dict(conn.execute("SELECT * FROM agent_content WHERE id=?", (content["id"],)).fetchone()) == content
        old_definition = runtime.repo.get_content(conn, auth, run["id"], failed["definition_ref"])
        new_definition = runtime.repo.get_content(conn, auth, replacement["id"], replacement["definition_ref"])
        assert old_definition == new_definition
    assert len(outbound) == 1 and model.calls == []  # Only later worker dispatch may perform new research.
    assert len(execution.view(auth, workspace_id)["history"]) == 2


@pytest.mark.parametrize("blocker", ["unfunded", "revoked", "pending", "stale_workspace", "stale_run"])
def test_failed_research_retry_rechecks_admission_and_keeps_old_run_when_denied(build_env, monkeypatch, blocker):
    env, auth, instance, runtime, model, outbound, _, state, execution, failed = failed_research(build_env, monkeypatch)
    workspace_version, run_version = state["version"], failed["version"]
    if blocker == "unfunded":
        spend_fixture_credit(env, instance.id, 5_000_000)
    elif blocker == "revoked":
        with env.db.transaction() as conn:
            conn.execute("UPDATE capability_grant SET enabled=0 WHERE instance_id=? AND capability='network.search'", (instance.id,))
    elif blocker == "pending":
        with env.db.transaction() as conn:
            conn.execute("UPDATE budget_hold SET state='unknown' WHERE id=(SELECT hold_id FROM agent_step WHERE run_id=? AND tool_name='public.research')", (failed["id"],))
    elif blocker == "stale_workspace":
        workspace_version -= 1
    elif blocker == "stale_run":
        run_version -= 1
    before = runtime.read(auth, failed["id"])
    with pytest.raises(AiclError):
        execution.restart(auth, state["id"], failed["id"], "rejected-retry", workspace_version, run_version)
    assert runtime.read(auth, failed["id"]) == before
    assert len(execution.view(auth, state["id"])["history"]) == 1
    assert len(outbound) == 1 and model.calls == []

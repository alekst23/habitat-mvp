"""Owner action inspection exposes retained evidence without replaying effects."""
from dataclasses import replace
from datetime import timedelta
import json

import pytest
from fastapi.testclient import TestClient

from aicl.app import create_app
from aicl.control.errors import AiclError
from aicl.control.budget import Estimate
from aicl.workflow.runtime_projection import RuntimeAuditProjection
from test_agent_runtime_session import batch, definition, finish, setup_runtime
from test_mock_commerce import ready
from test_work_review import protected_state
from test_workspace_execution import setup


def test_action_details_http_exact_context_and_result_owner_only_no_side_effects(build_env, base_env, monkeypatch):
    env, ctx, auth, inst, workspace, model, _ = setup(build_env, base_env)
    from aicl.agent_workspace.execution import WorkspaceExecution
    run = WorkspaceExecution(ctx).start(auth, workspace, "details-http")
    ctx.agent_runtime.advance_slice(auth, run["id"], max_operations=5)
    from aicl.agent_runtime import factory
    monkeypatch.setattr(factory, "build_runtime", lambda _: None)
    app = create_app(ctx.settings.model_copy(update={"environment": "test", "test_mode": True,
                                                   "database_url": env.db.database_url}))
    client = TestClient(app, base_url="http://127.0.0.1:4173")
    projection = RuntimeAuditProjection(env.db, env.clock)
    with env.db.reader() as conn:
        step = projection.job(conn, auth, run["id"])["steps"][0]
        assert projection.activity_log(conn, auth, run["id"])["steps"][0]["details_url"] == step["details_url"]
        row = conn.execute("SELECT * FROM agent_step WHERE id=?", (step["id"],)).fetchone()
        saved_input = projection.repo.get_content(conn, auth, run["id"], row["input_ref"])
        saved_output = projection.repo.get_content(conn, auth, run["id"], row["output_ref"])
    before, calls = protected_state(env.db), len(model.calls)
    response = client.get(step["details_url"])
    assert response.status_code == 401 and response.headers["cache-control"] == "no-store"
    app.state.ctx.auth_provider.contexts["details-owner"] = auth
    client.cookies.set("aicl_session", "details-owner")
    response = client.get(step["details_url"])
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    detail = response.json()
    assert detail["request"]["content"] == saved_input["request"] == model.calls[0]
    assert detail["request"]["estimate"] == saved_input["estimate"]
    assert detail["response"]["content"] == saved_output
    assert "provider" in detail["request"]["note"] and "not retained" in detail["request"]["note"]
    assert detail["step"]["cost_summary"] == step["cost_summary"]
    assert detail["request"]["status"] == detail["response"]["status"] == "retained"
    assert detail["records"] == []
    for foreign in (replace(auth, tenant_id="foreign"), replace(auth, owner_id="foreign")):
        app.state.ctx.auth_provider.contexts["details-owner"] = foreign
        response = client.get(step["details_url"])
        assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
        assert "definition" not in response.text
    app.state.ctx.auth_provider.contexts["details-owner"] = replace(auth, expires_at=env.clock.now() - timedelta(seconds=1))
    assert client.get(step["details_url"]).status_code == 401
    app.state.ctx.auth_provider.contexts["details-owner"] = auth
    assert client.get(step["details_url"].replace(run["id"], "different-run")).status_code == 404
    assert protected_state(env.db) == before and len(model.calls) == calls


def test_action_details_incomplete_receipt_keeps_reservations_unsettled(build_env):
    env, _, auth, inst, _ = ready(build_env)
    runtime, model, _ = setup_runtime(env, [batch()])
    model.estimate = Estimate(100, 100, 0)
    run = runtime.create_run(auth, inst.id, "unknown-details", definition())
    def interrupted(stage, step):
        if stage == "after_dispatch_intent":
            raise RuntimeError("lost worker")
    with pytest.raises(RuntimeError):
        runtime.advance_slice(auth, run["id"], fault=interrupted)
    projection = RuntimeAuditProjection(env.db, env.clock)
    with env.db.reader() as conn:
        step, = projection.repo.steps(conn, auth, run["id"])
        detail = projection.step_details(conn, auth, run["id"], step["id"])
    assert detail["request"]["status"] == "retained"
    assert detail["response"]["status"] == "not_retained" and detail["response"]["content"] is None
    assert detail["step"]["usage"] is None and model.calls == []
    assert detail["step"]["cost_summary"]["settled_micro_usd"] == 0
    assert detail["step"]["cost_summary"]["held_micro_usd"] == 400


def test_action_details_reject_cross_run_step_and_content_and_corrupt_payloads(build_env):
    env, _, auth, inst, _ = ready(build_env)
    runtime, _, _ = setup_runtime(env, [batch(), finish, batch(), finish])
    first = runtime.create_run(auth, inst.id, "details-first", definition())
    runtime.advance_slice(auth, first["id"], max_operations=10)
    other = runtime.create_run(auth, inst.id, "details-other", definition())
    runtime.advance_slice(auth, other["id"], max_operations=10)
    projection = RuntimeAuditProjection(env.db, env.clock)
    with env.db.reader() as conn:
        a = projection.repo.steps(conn, auth, first["id"])[0]
        b = projection.repo.steps(conn, auth, other["id"])[0]
        with pytest.raises(AiclError, match="not_found"):
            projection.step_details(conn, auth, first["id"], b["id"])
    for field in ("input_ref", "output_ref"):
        with env.db.reader() as conn:
            # Simulate damaged imported storage; normal composite foreign keys already reject this.
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(f"UPDATE agent_step SET {field}=? WHERE id=?", (b[field], a["id"]))
            with pytest.raises(AiclError, match="not_found"):
                projection.step_details(conn, auth, first["id"], a["id"])
            conn.execute(f"UPDATE agent_step SET {field}=? WHERE id=?", (a[field], a["id"]))
    with env.db.transaction() as conn:
        conn.execute("DROP TRIGGER agent_content_no_update")
        for field in ("input_ref", "output_ref"):
            original = conn.execute("SELECT digest FROM agent_content WHERE id=?", (a[field],)).fetchone()[0]
            conn.execute("UPDATE agent_content SET digest='corrupt' WHERE id=?", (a[field],))
            with pytest.raises(AiclError, match="unavailable"):
                projection.step_details(conn, auth, first["id"], a["id"])
            conn.execute("UPDATE agent_content SET digest=? WHERE id=?", (original, a[field]))


def test_research_detail_full_saved_evidence_scoped_planner_usage_and_integrity(build_env):
    from test_runtime_agent_research import agent_setup
    from aicl.agent_runtime.storage import canonical, _digest
    env, auth, _, runtime, model, research, run, outbound, _, planner = agent_setup(build_env)
    runtime.advance_slice(auth, run["id"])
    projection = RuntimeAuditProjection(env.db, env.clock)
    with env.db.transaction() as conn:
        row = next(step for step in projection.repo.steps(conn, auth, run["id"]) if step["tool_name"] == "public.research")
        # Exercise the retained full-source path even with this small fixture.
        source = projection.repo.put_content(conn, auth, run["id"], "public_research_source", {
            "source_kind": "public_page", "url": "https://news.example/full", "text": "Full saved page <script>unsafe()</script>",
            "instruction_authority": "untrusted_evidence"})
        manifest = projection.repo.put_content(conn, auth, run["id"], "public_research_evidence", {"evidence_refs": [source]})
        conn.execute("DROP TRIGGER agent_content_no_update")
        original = projection.repo.get_content(conn, auth, run["id"], row["output_ref"])
        payload = canonical({**original, "full_evidence_ref": manifest})
        conn.execute("UPDATE agent_content SET payload_json=?,digest=? WHERE id=?", (payload, _digest(payload), row["output_ref"]))
    before = protected_state(env.db)
    counts = len(outbound), len(model.calls), len(planner.calls)
    with env.db.reader() as conn:
        detail = projection.step_details(conn, auth, run["id"], row["id"])
        evidence = [record for record in detail["records"] if record["kind"] == "research_evidence"]
        assert len(evidence) == 1 and evidence[0]["response"]["content"]["text"].endswith("<script>unsafe()</script>")
        rounds = [record for record in detail["records"] if record["kind"] == "research_planner"]
        assert len(rounds) == 3 and all(record["metadata"]["usage"]["inference_input_tokens"] == 100 for record in rounds)
        assert [record["request"]["content"] for record in rounds] == planner.calls
        assert rounds[0]["response"]["content"] == {"operations": [{"kind": "search", "query": "Current public AI news"}]}
        requests = [record for record in detail["records"] if record["kind"] == "research_network"]
        assert len(requests) == 2
        assert [record["request"]["content"]["url"] for record in requests] == [str(request.url) for request in outbound]
        assert all(record["request"]["content"]["method"] == "GET" for record in requests)
        assert all(record["response"]["content"]["http_status"] == 200 for record in requests)
        assert requests[0]["response"]["content"]["evidence"]["source_kind"] == "public_search"
        assert requests[1]["response"]["content"]["evidence"]["source_kind"] == "public_page"
        assert not any("subscription" in header.lower() for record in requests for header in record["request"]["content"]["headers"])
        assert "credential_binding" not in json.dumps(detail)
    assert protected_state(env.db) == before
    assert counts == (len(outbound), len(model.calls), len(planner.calls))
    with env.db.transaction() as conn:
        for ref in (source, manifest, rounds[0]["content_ref"]):
            digest = conn.execute("SELECT digest FROM agent_content WHERE id=?", (ref,)).fetchone()[0]
            conn.execute("UPDATE agent_content SET digest='corrupt' WHERE id=?", (ref,))
            with pytest.raises(AiclError, match="unavailable"):
                projection.step_details(conn, auth, run["id"], row["id"])
            conn.execute("UPDATE agent_content SET digest=? WHERE id=?", (digest, ref))


def test_prepared_action_details_show_proposal_and_no_dispatch_claim(build_env):
    env, _, auth, inst, _ = ready(build_env)
    runtime, model, tool = setup_runtime(env, [batch(), finish])
    run = runtime.create_run(auth, inst.id, "prepared-details", definition())
    runtime.advance_slice(auth, run["id"], max_operations=1)
    projection = RuntimeAuditProjection(env.db, env.clock)
    with env.db.reader() as conn:
        row = next(step for step in projection.repo.steps(conn, auth, run["id"]) if step["state"] == "prepared")
        detail = projection.step_details(conn, auth, run["id"], row["id"])
    assert detail["step"]["state"] == "prepared" and detail["step"]["usage"] is None
    assert detail["request"]["content"] == {"key": "one"}
    assert detail["request"]["estimate"] is None and detail["response"]["status"] == "not_retained"
    assert "not been dispatched" in detail["response"]["note"]
    assert len(model.calls) == 1 and tool.calls == []

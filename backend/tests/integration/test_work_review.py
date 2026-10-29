"""Long-lived review browsing is owner-only and has no runtime authority."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from aicl.agent_runtime.storage import Repository
from aicl.agent_workspace.execution import WorkspaceExecution
from aicl.app import FIXTURE_CSRF_TOKEN, create_app
from aicl.control.errors import AiclError
from aicl.db import to_iso
from aicl.work_review.service import WorkReviewService
from test_workspace_execution import setup


def saved_run(ctx, auth, inst, workspace, key, *, state="completed", bodies=()):
    repo = Repository(ctx.db, ctx.clock)
    run = repo.create_run(auth, inst.id, key, {"objective": "Review " + key, "requirements": []}, {})
    with ctx.db.transaction() as conn:
        conn.execute("INSERT INTO agent_workspace_run(workspace_id,run_id,created_at) VALUES (?,?,?)",
                     (workspace, run["id"], run["created_at"]))
        checkpoint = repo.get_content(conn, auth, run["id"], run["checkpoint_ref"])
        for name, text in bodies:
            ref = repo.put_content(conn, auth, run["id"], "artifact", {"local_ref": name, "content": text, "evidence_refs": []})
            checkpoint["artifacts"][name] = {"ref": ref}
        if state == "completed":
            checkpoint["completed_artifacts"] = list(checkpoint["artifacts"])
        return repo.save_checkpoint(conn, auth, run, checkpoint, {"status": state})


def protected_state(db):
    with db.reader() as conn:
        return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("agent_run", "agent_content", "agent_step", "agent_event", "agent_wakeup", "budget_hold",
                              "budget_usage", "capability_grant", "mock_commerce_ledger", "audit_event")}


def test_inbox_pages_all_history_and_metadata_filters_without_loading_report_bodies(build_env, base_env, monkeypatch):
    env, ctx, auth, inst, workspace, model, _ = setup(build_env, base_env)
    service, repo = WorkReviewService(ctx), Repository(ctx.db, ctx.clock)
    start = env.clock.now()
    runs = []
    for number in range(36):
        env.clock.set(start + timedelta(days=number))
        # The fixture owner session is intentionally long lived for this history.
        auth = replace(auth, expires_at=env.clock.now() + timedelta(days=100))
        runs.append(saved_run(ctx, auth, inst, workspace, f"week {number:02d}",
                             state="blocked" if number == 0 else "completed",
                             bodies=[("dated_report", "body-only-secret-search-term")]))
    original = repo.get_content

    def metadata_only(self, conn, owner, run_id, ref):
        kind = conn.execute("SELECT kind FROM agent_content WHERE id=?", (ref,)).fetchone()[0]
        assert kind != "artifact", "The inbox must not load every report body"
        return original(conn, owner, run_id, ref)

    monkeypatch.setattr(Repository, "get_content", metadata_only)
    before = protected_state(env.db)
    page = service.list(auth, limit=13)
    seen = list(page["items"])
    while page["next_cursor"]:
        page = service.list(auth, limit=13, cursor=page["next_cursor"])
        seen.extend(page["items"])
    assert [item["run_id"] for item in seen] == [run["id"] for run in reversed(runs)]
    assert len({item["run_id"] for item in seen}) == 36
    assert all(item["recorded_micro_usd"] is None and "content" not in item["outputs"][0] for item in seen)
    assert service.list(auth, q="dated_report")["counts"]["all"] == 36
    assert service.list(auth, q="body-only-secret-search-term")["items"] == []
    assert service.list(auth, q="week 00", view="needs_attention")["items"][0]["run_id"] == runs[0]["id"]
    first_date = start.date().isoformat()
    assert len(service.list(auth, from_date=first_date, to_date=first_date)["items"]) == 1
    empty = service.list(auth, q="absent")
    assert empty["agents"] == [{"workspace_id": workspace, "name": inst.name}]
    assert empty["counts"] == {"all": 0, "unseen": 0, "saved": 0, "needs_attention": 0}
    assert empty["search_scope"] == "Agent names, goals and saved output names"
    assert service.list(auth, q="%_")["items"] == []  # Literal search, not wildcard discovery.
    assert model.calls == [] and protected_state(env.db) == before
    cursor = service.list(auth, limit=1)["next_cursor"]
    with pytest.raises(AiclError, match="validation_failed"):
        service.list(auth, cursor=cursor, q="different")


def test_marks_are_only_personal_navigation_and_new_versions_return_to_unseen(build_env, base_env):
    env, ctx, auth, inst, workspace, model, _ = setup(build_env, base_env)
    service, repo = WorkReviewService(ctx), Repository(env.db, env.clock)
    run = saved_run(ctx, auth, inst, workspace, "unfinished", state="blocked")
    before = protected_state(env.db)
    assert service.list(auth, view="needs_attention")["items"][0]["output_count"] == 0
    mark = service.mark(auth, run["id"], {"seen": True, "saved": True, "expected_version": run["version"]})
    assert mark == {"run_id": run["id"], "seen": True, "saved": True, "version": run["version"]}
    assert not service.list(auth, view="unseen")["items"]
    assert len(service.list(auth, view="saved")["items"]) == 1
    assert protected_state(env.db) == before and model.calls == []
    for invalid in ({"seen": 1}, {"saved": "false"}, {"approve": True}, {}, {"seen": True, "expected_version": True}):
        with pytest.raises(AiclError, match="validation_failed"):
            service.mark(auth, run["id"], invalid)
    # Simulate a worker saving the next version; saved survives, seen does not.
    with env.db.transaction() as conn:
        checkpoint = repo.get_content(conn, auth, run["id"], run["checkpoint_ref"])
        updated = repo.save_checkpoint(conn, auth, run, checkpoint, {"reason": "New evidence available"})
    item = service.list(auth, view="unseen")["items"][0]
    assert item["saved"] and not item["seen"] and item["version"] == updated["version"]
    with pytest.raises(AiclError, match="conflict"):
        service.mark(auth, run["id"], {"seen": True, "expected_version": run["version"]})
    service.mark(auth, run["id"], {"saved": False})
    assert not service.list(auth, view="saved")["items"]


def test_detail_keeps_versions_partial_work_sources_and_exact_existing_cost_projection(build_env, base_env):
    env, ctx, auth, inst, workspace, model, _ = setup(build_env, base_env)
    execution, service = WorkspaceExecution(ctx), WorkReviewService(ctx)
    run = execution.start(auth, workspace, "measured")
    ctx.agent_runtime.advance_slice(auth, run["id"], max_operations=5)
    with env.db.transaction() as conn:
        repo = Repository(env.db, env.clock)
        source = repo.put_content(conn, auth, run["id"], "public_research_source", {
            "source_kind": "public_search", "instruction_authority": "untrusted_evidence", "sources": [
                {"url": "https://example.org/article", "title": "Original source", "text": "Excluded body"},
                {"url": "javascript:alert(1)", "title": "Unsafe"},
                {"url": "https://secret@example.org/", "title": "Credential authority"},
                {"url": "https://127.0.0.1/", "title": "Local address"}]})
        repo.put_content(conn, auth, run["id"], "memory", {"source_kind": "public_page", "url": "https://forged.test"})
    before = protected_state(env.db)
    detail = service.detail(auth, run["id"])
    assert detail["item"]["status"] == "completed" and detail["outputs"][0]["content"] == "A queue preserves order."
    assert detail["sources"] == [{"url": "https://example.org/article", "title": "Original source", "kind": "search_result",
                                  "unavailable": False, "evidence_ref": source, "recorded_at": to_iso(env.clock.now()),
                                  "instruction_authority": "untrusted_evidence"}]
    assert detail["item"]["recorded_micro_usd"] == detail["activity"]["summary"]["settled_micro_usd"]
    assert detail["item"]["recorded_micro_usd"] is not None
    assert detail["activity"]["totals"]["model_decisions"] == 1
    assert detail["snapshot"]["objective"].startswith("Explain the supplied design")
    assert protected_state(env.db) == before
    partial = saved_run(ctx, auth, inst, workspace, "partial", state="failed",
                        bodies=[("draft", "First version"), ("draft", "Second version")])
    detail = service.detail(auth, partial["id"])
    assert [(output["version"], output["state"], output["latest"], output["content"]) for output in detail["outputs"]] == [
        (2, "draft", True, "Second version"), (1, "draft", False, "First version")]
    assert detail["item"]["needs_attention"] and detail["item"]["recorded_micro_usd"] is None
    # Corruption remains a hard failure, never rendered as a valid result.
    with env.db.transaction() as conn:
        conn.execute("DROP TRIGGER agent_content_no_update")
        conn.execute("UPDATE agent_content SET digest='corrupt' WHERE id=?", (detail["outputs"][0]["id"].split(":")[-1],))
    with pytest.raises(AiclError, match="unavailable"):
        service.detail(auth, partial["id"])


def test_review_http_owner_scope_csrf_and_no_implicit_marks(build_env, base_env, monkeypatch):
    env, ctx, auth, inst, workspace, model, _ = setup(build_env, base_env)
    run = saved_run(ctx, auth, inst, workspace, "http", state="blocked",
                    bodies=[("report", "First saved version"), ("report", "Latest saved version")])
    env.clock.set(env.clock.now() + timedelta(minutes=1))
    newer = saved_run(ctx, auth, inst, workspace, "newer work", state="blocked")
    from aicl.agent_runtime import factory
    monkeypatch.setattr(factory, "build_runtime", lambda _: ctx.agent_runtime)
    settings = ctx.settings.model_copy(update={"environment": "test", "test_mode": True, "database_url": env.db.database_url})
    app = create_app(settings)
    app.state.ctx.auth_provider.contexts["review-owner"] = auth
    app.state.ctx.csrf_verifier.fixture_session_ids |= {auth.session_id}
    client = TestClient(app, base_url="http://127.0.0.1:4173")
    assert client.get("/api/work-review").status_code == 401
    client.cookies.set("aicl_session", "review-owner")
    before = protected_state(env.db)
    assert client.get("/api/work-review").json()["items"][0]["run_id"] == newer["id"]
    historical = client.get("/api/work-review/" + run["id"])
    assert historical.status_code == 200
    assert [(output["version"], output["content"]) for output in historical.json()["outputs"]] == [
        (2, "Latest saved version"), (1, "First saved version")]
    assert historical.json()["item"]["run_id"] == run["id"]
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_review_mark").fetchone()[0] == 0
    path = "/api/work-review/" + run["id"] + "/marks"
    assert client.post(path, json={"seen": True}).status_code == 403
    headers = {"X-CSRF-Token": FIXTURE_CSRF_TOKEN, "Origin": "http://127.0.0.1:4173"}
    assert client.post(path, json={"seen": True}, headers={**headers, "Origin": "https://attacker.test"}).status_code == 403
    assert client.post(path, json={"seen": True, "saved": True}, headers=headers).status_code == 200
    for foreign in (replace(auth, owner_id=str(uuid.uuid4())), replace(auth, tenant_id=str(uuid.uuid4()))):
        app.state.ctx.auth_provider.contexts["review-owner"] = foreign
        assert client.get("/api/work-review").json()["items"] == []
        assert client.get("/api/work-review/" + run["id"]).status_code == 404
        assert client.post(path, json={"seen": False}, headers=headers).status_code == 404
    assert protected_state(env.db) == before and model.calls == []


@pytest.mark.parametrize("target,malformed", [("definition", False), ("artifact", False), ("artifact", True)])
def test_metadata_integrity_precedes_even_nonmatching_filters_and_is_owner_scoped(build_env, base_env, target, malformed):
    env, ctx, auth, inst, workspace, _, _ = setup(build_env, base_env)
    run = saved_run(ctx, auth, inst, workspace, "integrity", bodies=[("report", "Preserved body")])
    service = WorkReviewService(ctx)
    with env.db.transaction() as conn:
        row = conn.execute("SELECT id,payload_json FROM agent_content WHERE run_id=? AND kind=?", (run["id"], target)).fetchone()
        payload = json.loads(row["payload_json"])
        payload["objective" if target == "definition" else "local_ref"] = 42 if malformed else "forged metadata"
        encoded = json.dumps(payload)
        conn.execute("DROP TRIGGER agent_content_no_update")
        if malformed:
            # Even a matching digest cannot make a non-string output name valid.
            conn.execute("UPDATE agent_content SET payload_json=?,digest=? WHERE id=?",
                         (encoded, hashlib.sha256(encoded.encode()).hexdigest(), row["id"]))
        else:
            conn.execute("UPDATE agent_content SET payload_json=? WHERE id=?", (encoded, row["id"]))
    for query in ("", "forged metadata", "no match anywhere"):
        with pytest.raises(AiclError, match="unavailable"):
            service.list(auth, q=query)
    for operation in (lambda: service.detail(auth, run["id"]), lambda: service.mark(auth, run["id"], {"seen": True})):
        with pytest.raises(AiclError, match="unavailable"):
            operation()
    for foreign in (replace(auth, owner_id=str(uuid.uuid4())), replace(auth, tenant_id=str(uuid.uuid4()))):
        assert service.list(foreign)["items"] == []
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_review_mark").fetchone()[0] == 0


def test_sources_use_actual_broker_receipt_without_new_egress_or_inference(build_env):
    from test_runtime_research_prelude import setup as research_setup

    env, auth, inst, runtime, model, _, run, outbound, _, ctx = research_setup(build_env)
    runtime.advance_slice(auth, run["id"], max_operations=1)
    assert len(outbound) == 2 and model.calls == []
    with env.db.transaction() as conn:
        workspace = conn.execute("SELECT id FROM agent_workspace WHERE instance_id=?", (inst.id,)).fetchone()[0]
        conn.execute("INSERT INTO agent_workspace_run(workspace_id,run_id,created_at) VALUES (?,?,?)",
                     (workspace, run["id"], run["created_at"]))
        step = conn.execute("SELECT output_ref FROM agent_step WHERE run_id=? AND tool_name='public.research'", (run["id"],)).fetchone()
        receipt = runtime.repo.get_content(conn, auth, run["id"], step["output_ref"])
        assert [evidence["source_kind"] for evidence in receipt["evidence"]] == ["public_search", "public_page"]
    before = protected_state(env.db)
    detail = WorkReviewService(ctx).detail(auth, run["id"])
    assert {(source["url"], source["title"], source["kind"]) for source in detail["sources"]} == {
        ("https://news.example/article", "Untrusted search evidence", "search_result"),
        ("https://news.example/article", "Public report", "page")}
    assert all(source["evidence_ref"] == step["output_ref"] for source in detail["sources"])
    assert detail["item"]["recorded_micro_usd"] == 5000
    assert len(outbound) == 2 and model.calls == [] and protected_state(env.db) == before

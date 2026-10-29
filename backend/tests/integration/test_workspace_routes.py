"""The owner's actual workspace -> checkout -> run path, with fixture providers."""
import json
import uuid
from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from aicl.agent_runtime.adapters import ToolRegistry
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.app import FIXTURE_CSRF_TOKEN, create_app
from aicl.control.budget import Estimate
from test_runtime_chat import setup


def test_unified_entry_funding_return_readiness_and_single_start(build_env, base_env, monkeypatch):
    env, ctx, _, _, _, auth, inst, _, model = setup(build_env, base_env, funded=False)
    model.estimate = Estimate(1000, 1000, 0)
    from aicl.agent_runtime import factory
    monkeypatch.setattr(factory, "build_runtime", lambda c: AgentRuntime(c.db, c.clock, model, ToolRegistry()))
    app = create_app(ctx.settings.model_copy(update={"environment": "test", "test_mode": True, "database_url": env.db.database_url}))
    app.state.ctx.auth_provider.contexts["workspace-cookie"] = auth
    app.state.ctx.csrf_verifier.fixture_session_ids |= {auth.session_id}
    client = TestClient(app, base_url="http://127.0.0.1:4173")
    client.cookies.set("aicl_session", "workspace-cookie")
    origin = {"Origin": "http://127.0.0.1:4173"}
    headers = {**origin, "X-CSRF-Token": FIXTURE_CSRF_TOKEN}
    page = client.get(f"/instances/{inst.id}")
    assert page.status_code == 200, page.text
    path = page.url.path
    assert path.startswith("/agent-workspaces/")
    assert client.get(f"/instances/{inst.id}/workflow").url.path == path
    assert client.get(f"/chat?instance={inst.id}").url.path == path
    assert 'id="workspace-assistant"' in page.text and 'id="workspace-funding"' in page.text
    api = "/api" + path
    state = client.get(api).json()["state"]
    assert not state["execution"]["readiness"]["ready"]
    old_body = {"chat_session_id": state["session_id"], "instance_id": inst.id, "request_id": str(uuid.uuid4()), "tools": []}
    assert client.post("/chat/runs/start", json=old_body, headers=headers).status_code == 409
    assert client.post("/chat/messages", json={**old_body, "text": "Create another agent"}, headers=headers).status_code == 409

    def command(name, args=None, request_id=None, version=None):
        return client.post(api + "/commands", json={"command": name, "request_id": request_id or str(uuid.uuid4()),
                           "expected_version": state["version"] if version is None else version, "arguments": args or {}}, headers=headers)

    denied = client.post(api + "/commands", json={"command": "fund", "request_id": str(uuid.uuid4()), "arguments": {"amount_minor": 500}}, headers=origin)
    assert denied.status_code == 403
    applied = command("apply")
    assert applied.status_code == 200, applied.text
    state = applied.json()["state"]
    assert command("start").status_code == 403
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0
    checkout = command("fund", {"amount_minor": 500})
    assert checkout.status_code == 200, checkout.text
    order_path = checkout.json()["redirect_url"]
    assert command("fund", {"amount_minor": 500}).json()["redirect_url"] == order_path
    assert "Return to workspace" in client.get(order_path).text
    paid = client.post(order_path + "/checkout", data={"csrf_token": FIXTURE_CSRF_TOKEN, "outcome": "complete", "buyer_id": "demo-buyer"}, headers=origin, follow_redirects=False)
    assert paid.status_code == 303 and paid.headers["location"].startswith(path + "?"), paid.text
    assert "Payment completed" in client.get(paid.headers["location"]).text
    state = client.get(api).json()["state"]
    assert state["execution"]["readiness"]["ready"]
    assert model.calls == []
    request_id = str(uuid.uuid4())
    started = command("start", request_id=request_id)
    assert started.status_code == 200, started.text
    run_id = started.json()["state"]["execution"]["run"]["id"]
    assert command("start", request_id=request_id).json()["state"]["execution"]["run"]["id"] == run_id
    assert command("start").status_code == 409
    app.state.ctx.auth_provider.contexts["workspace-cookie"] = replace(auth, owner_id=str(uuid.uuid4()))
    assert client.get(api).status_code == 404
    assert command("pause", {"run_id": run_id}).status_code == 404
    assert model.calls == []


def test_new_agent_and_chat_share_workspace_draft_with_stale_write_protection(build_env, base_env, monkeypatch):
    env, ctx, _, _, _, auth, _, _, model = setup(build_env, base_env)
    from aicl.agent_runtime import factory
    monkeypatch.setattr(factory, "build_runtime", lambda c: AgentRuntime(c.db, c.clock, model, ToolRegistry()))
    app = create_app(ctx.settings.model_copy(update={"environment": "test", "test_mode": True, "database_url": env.db.database_url}))
    app.state.ctx.auth_provider.contexts["workspace-cookie"] = auth
    app.state.ctx.csrf_verifier.fixture_session_ids |= {auth.session_id}
    client = TestClient(app, base_url="http://127.0.0.1:4173")
    client.cookies.set("aicl_session", "workspace-cookie")
    page = client.get("/agents/new")
    assert page.status_code == 200
    api = "/api" + page.url.path
    state = client.get(api).json()["state"]
    assert state["instance_id"] is None
    assert client.get('/chat?session=' + state["session_id"]).url.path == page.url.path
    headers = {"X-CSRF-Token": FIXTURE_CSRF_TOKEN, "Origin": "http://127.0.0.1:4173"}
    body = {"command": "update_draft", "request_id": str(uuid.uuid4()), "expected_version": state["version"], "arguments": {"patch": {"name": "Shared draft"}}}
    assert client.post(api + "/commands", json=body, headers=headers).status_code == 200
    assert client.post(api + "/commands", json={**body, "arguments": {"patch": {"name": "Stale"}}}, headers=headers).status_code == 409
    assert client.get(api).json()["state"]["draft"]["name"] == "Shared draft"
    assert "Shared draft" in client.get("/workspace").text
    assert model.calls == []


@pytest.mark.parametrize("outcome", ["completed", "failed", "unknown"])
def test_assistant_terminal_receipt_replays_after_saved_draft_without_dispatch(build_env, base_env, monkeypatch, outcome):
    """A lost final response must not turn an accepted draft edit into a new model turn."""
    from aicl.agent_runtime import factory
    from aicl.agent_workspace.assistant import WorkspaceAssistantService
    from aicl.chat.sdk_agent import SDKInterviewError

    env, ctx, _, _, _, auth, _, _, worker = setup(build_env, base_env)
    monkeypatch.setattr(factory, "build_runtime", lambda c: AgentRuntime(c.db, c.clock, worker, ToolRegistry()))

    class DraftThenReply:
        calls = 0

        async def run(self, history, *, tools, invoke, meter):
            self.calls += 1
            attempt = meter.reserve()
            meter.settle(attempt, "fixture_workspace_reply", "gpt-6-sol", 100, 20)
            current = invoke("read_workspace", {"section": "overview", "offset": 0})
            saved = invoke("update_draft", {"expected_version": current["version"],
                                           "patch": {"name": "Saved before final reply", "inputs": "Keep this saved draft."}})
            assert saved["version"] == current["version"] + 1
            invoke("show_section", {"section": "outcome"})
            if outcome == "unknown":
                meter.reserve()  # An uncertain follow-up keeps its reservation after failure.
                raise SDKInterviewError("provider_unknown")
            if outcome == "failed":
                raise SDKInterviewError("context_too_large")
            return "The draft is saved on screen. Review it before applying settings."

    model = DraftThenReply()
    monkeypatch.setattr(WorkspaceAssistantService, "_model", lambda self: model)
    app = create_app(ctx.settings.model_copy(update={"environment": "test", "test_mode": True,
                                                      "database_url": env.db.database_url}))
    app.state.ctx.auth_provider.contexts["workspace-cookie"] = auth
    app.state.ctx.csrf_verifier.fixture_session_ids |= {auth.session_id}
    client = TestClient(app, base_url="http://127.0.0.1:4173")
    client.cookies.set("aicl_session", "workspace-cookie")
    page = client.get("/agents/new")
    api = "/api" + page.url.path
    state = client.get(api).json()["state"]
    origin = {"Origin": "http://127.0.0.1:4173"}
    headers = {**origin, "X-CSRF-Token": FIXTURE_CSRF_TOKEN}
    body = {"request_id": str(uuid.uuid4()), "expected_version": state["version"], "text": "Fill in my agent draft"}
    denied = client.post(api + "/messages", json=body, headers=origin)
    assert denied.status_code == 403 and model.calls == 0

    response = client.post(api + "/messages", json=body, headers=headers)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["turn"]["accepted"] is True
    assert receipt["turn"]["status"] == outcome
    assert receipt["turn"]["request_id"] == body["request_id"]
    assert receipt["state"]["version"] == state["version"] + 1
    assert receipt["state"]["draft"]["name"] == "Saved before final reply"
    assert receipt["state"]["dirty"] and receipt["state"]["published"] is None
    assert [item["role"] for item in receipt["messages"]] == ["user", "assistant"]
    assert receipt["messages"][0]["text"] == body["text"]
    if outcome == "completed":
        assert receipt["messages"][-1]["text"].startswith("The draft is saved")
    else:
        assert receipt["messages"][-1]["kind"] == "recovery"
        assert receipt["messages"][-1]["text"]
    assert receipt["usage"]["unknown"] == (outcome == "unknown")
    assert (receipt["usage"]["held_micro_usd"] > 0) == (outcome == "unknown")

    # Use the exact original body, including its now-old version, as a browser retries a lost response.
    replay = client.post(api + "/messages", json=body, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["turn"]["status"] == outcome
    assert replay.json()["messages"] == receipt["messages"]
    assert replay.json()["state"]["version"] == receipt["state"]["version"]
    assert replay.json()["usage"] == receipt["usage"]
    assert model.calls == 1 and worker.calls == []

    changed_text = client.post(api + "/messages", json={**body, "text": "A different message"}, headers=headers)
    assert changed_text.status_code == 409
    stale_new = client.post(api + "/messages", json={**body, "request_id": str(uuid.uuid4())}, headers=headers)
    assert stale_new.status_code == 409
    assert model.calls == 1 and worker.calls == []
    with env.db.reader() as conn:
        turns = conn.execute("SELECT state FROM assistant_turn WHERE session_id=?", (state["session_id"],)).fetchall()
        assert [row["state"] for row in turns] == [outcome]
        stored = conn.execute("SELECT role,text,metadata_json FROM assistant_message WHERE session_id=? ORDER BY id",
                              (state["session_id"],)).fetchall()
        assert [row["role"] for row in stored] == ["user", "assistant"]
        assert stored[-1]["text"] == receipt["messages"][-1]["text"]
        if outcome != "completed":
            assert json.loads(stored[-1]["metadata_json"])["kind"] == "recovery"
        assert conn.execute("SELECT COUNT(*) FROM assistant_inference_attempt").fetchone()[0] == (2 if outcome == "unknown" else 1)

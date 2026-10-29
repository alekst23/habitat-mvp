"""Chat funding uses the existing payment flow without starting paid work."""
import uuid
from dataclasses import replace

from fastapi.testclient import TestClient

from aicl.agent_runtime.adapters import ToolRegistry
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.app import FIXTURE_CSRF_TOKEN, create_app
from aicl.chat.assistant_service import AssistantService
from test_runtime_chat import setup


def test_chat_funding_is_owned_csrf_protected_and_preserves_saved_work(build_env, base_env, monkeypatch):
    env, ctx, _, _, _, auth, inst, _, model = setup(build_env, base_env)
    from aicl.agent_runtime import factory
    monkeypatch.setattr(factory, "build_runtime", lambda c: AgentRuntime(c.db, c.clock, model, ToolRegistry()))
    app = create_app(ctx.settings.model_copy(update={"environment": "test", "test_mode": True,
                                                   "database_url": env.db.database_url}))
    app.state.ctx.auth_provider.contexts["funding-cookie"] = auth
    app.state.ctx.csrf_verifier.fixture_session_ids |= {auth.session_id}
    client = TestClient(app, base_url="http://127.0.0.1:4173")
    client.cookies.set("aicl_session", "funding-cookie")
    # Legacy payment API remains valid for saved pre-workspace conversations.
    session = AssistantService(app.state.ctx).new_session(auth)
    fields = {"chat_session_id": session, "instance_id": inst.id, "request_id": str(uuid.uuid4()), "amount_minor": "500"}
    origin = {"Origin": "http://127.0.0.1:4173"}
    assert client.post("/chat/funding", data=fields, headers=origin).status_code == 403
    fields["csrf_token"] = FIXTURE_CSRF_TOKEN
    app.state.ctx.auth_provider.contexts["funding-cookie"] = replace(auth, owner_id=str(uuid.uuid4()))
    assert client.post("/chat/funding", data=fields, headers=origin).status_code == 404
    app.state.ctx.auth_provider.contexts["funding-cookie"] = auth
    result = client.post("/chat/funding", data=fields, headers=origin, follow_redirects=False)
    assert result.status_code == 303, result.text
    path = result.headers["location"]
    assert path.startswith("/commerce/orders/")
    assert client.post("/chat/funding", data=fields, headers=origin, follow_redirects=False).headers["location"] == path
    assert client.post("/chat/funding", data={**fields, "request_id": str(uuid.uuid4())},
                       headers=origin, follow_redirects=False).headers["location"] == path
    assert "Pay $5.00 with PayPal" in client.get(path).text
    paid = client.post(path + "/checkout", data={"csrf_token": FIXTURE_CSRF_TOKEN, "outcome": "complete", "buyer_id": "demo-buyer"},
                       headers=origin, follow_redirects=False)
    assert paid.headers["location"] == f"/chat?session={session}&instance={inst.id}&notice=funded"
    assert "Payment completed" in client.get(paid.headers["location"]).text
    assert model.calls == []
    with env.db.reader() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM budget_hold").fetchone()[0] == 0
